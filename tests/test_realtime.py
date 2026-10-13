import pytest
from starlette.websockets import WebSocketDisconnect

from app.core.security import create_access_token

WS = "/api/v1/ws"


def _auth(sock, user):
    sock.send_json({"type": "auth", "token": create_access_token(user.id, user.role_name)})
    ready = sock.receive_json()
    assert ready["type"] == "ready" and ready["user_id"] == str(user.id)
    return sock


def _until(sock, msg_type, where=None, **match):
    """Read frames until one of the given type (and matching fields / predicate) arrives."""
    for _ in range(20):
        msg = sock.receive_json()
        if (msg.get("type") == msg_type and all(msg.get(k) == v for k, v in match.items())
                and (where is None or where(msg))):
            return msg
    raise AssertionError(f"no {msg_type} message")


def test_rejects_unauthenticated(client):
    with client.websocket_connect("/api/v1/ws") as ws:
        ws.send_json({"type": "auth", "token": "invalid"})
        with pytest.raises(WebSocketDisconnect) as exc:
            ws.receive_json()
        assert exc.value.code == 4401
    with client.websocket_connect("/api/v1/ws") as ws:
        ws.send_json({"type": "subscribe", "channel": "user:me"})  # not an auth frame
        with pytest.raises(WebSocketDisconnect) as exc:
            ws.receive_json()
        assert exc.value.code == 4401


def test_ping_and_errors(client, factory):
    with client.websocket_connect(WS) as ws:
        _auth(ws, factory.user())
        ws.send_json({"type": "ping"})
        assert ws.receive_json()["type"] == "pong"
        ws.send_text("not json")
        assert ws.receive_json()["code"] == "invalid_json"
        ws.send_json({"type": "subscribe", "channel": "bogus:1", "id": "r1"})
        err = ws.receive_json()
        assert err["code"] == "invalid_channel" and err["ref"] == "r1"
        ws.send_json({"type": "subscribe", "channel": "user:00000000-0000-0000-0000-000000000000"})
        assert ws.receive_json()["code"] == "forbidden"


def test_playlist_live_updates_and_presence(client, catalog, factory):
    owner, friend, stranger = factory.user(premium=True), factory.user(), factory.user()
    pl = client.post("/api/v1/playlists", json={"name": "Live", "is_public": False, "is_collaborative": True},
                     headers=factory.headers(owner)).json()
    client.post(f"/api/v1/playlists/{pl['id']}/join", json={"code": pl["collab_invite_code"]}, headers=factory.headers(friend))
    channel = f"playlist:{pl['id']}"

    with client.websocket_connect(WS) as ws_s:
        _auth(ws_s, stranger)
        ws_s.send_json({"type": "subscribe", "channel": channel})
        assert ws_s.receive_json()["code"] == "not_found"  # private playlist

    with client.websocket_connect(WS) as ws_o, client.websocket_connect(WS) as ws_f:
        _auth(ws_o, owner)
        _auth(ws_f, friend)
        ws_o.send_json({"type": "subscribe", "channel": channel})
        _until(ws_o, "subscribed")
        ws_f.send_json({"type": "subscribe", "channel": channel})
        _until(ws_f, "subscribed")
        presence = _until(ws_o, "presence")
        while len(presence["users"]) < 2:
            presence = _until(ws_o, "presence")
        assert {u["user_id"] for u in presence["users"]} == {str(owner.id), str(friend.id)}

        # A REST edit by the collaborator reaches the owner's socket.
        client.post(f"/api/v1/playlists/{pl['id']}/tracks", json={"song_ids": [catalog["songs"][0]["id"]]},
                    headers=factory.headers(friend))
        update = _until(ws_o, "playlist.updated")
        assert update["action"] == "tracks_added" and update["by"]["user_id"] == str(friend.id)

        ws_f.send_json({"type": "unsubscribe", "channel": channel})
        presence = _until(ws_o, "presence")
        assert [u["user_id"] for u in presence["users"]] == [str(owner.id)]


def test_group_session_sync(client, catalog, factory):
    host, guest, free = factory.user(premium=True), factory.user(), factory.user()
    assert client.post("/api/v1/sessions", json={"name": "Friday"}, headers=factory.headers(free)).status_code == 402
    session = client.post("/api/v1/sessions", json={"name": "Friday"}, headers=factory.headers(host)).json()
    assert session["is_host"]
    channel = f"session:{session['id']}"

    with client.websocket_connect(WS) as ws_g:
        _auth(ws_g, guest)
        ws_g.send_json({"type": "subscribe", "channel": channel})
        assert ws_g.receive_json()["code"] == "not_found"  # must join first
    joined = client.post("/api/v1/sessions/join", json={"invite_code": session["invite_code"]}, headers=factory.headers(guest))
    assert joined.status_code == 200 and not joined.json()["is_host"]

    with client.websocket_connect(WS) as ws_h, client.websocket_connect(WS) as ws_g:
        _auth(ws_h, host)
        _auth(ws_g, guest)
        ws_g.send_json({"type": "subscribe", "channel": channel})
        _until(ws_g, "subscribed")
        snapshot = _until(ws_g, "session.state")
        assert snapshot["session"]["name"] == "Friday" and snapshot["session"]["current_song"] is None
        ws_h.send_json({"type": "subscribe", "channel": channel})
        _until(ws_h, "subscribed")

        song = catalog["songs"][0]["id"]
        ws_h.send_json({"type": "session.control", "session_id": session["id"], "action": "play_song",
                        "song_id": song, "id": "c1"})
        state = _until(ws_g, "session.state")
        assert state["session"]["current_song"]["id"] == song and state["session"]["is_playing"] is True
        assert "liked" not in state["session"]["current_song"] or state["session"]["current_song"]["liked"] is None

        # Guests can add to the shared queue but can't control playback.
        ws_g.send_json({"type": "session.control", "session_id": session["id"], "action": "pause", "id": "c2"})
        assert _until(ws_g, "error", ref="c2")["code"] == "forbidden"
        ws_g.send_json({"type": "session.control", "session_id": session["id"], "action": "queue_add",
                        "song_id": catalog["songs"][1]["id"]})
        state = _until(ws_h, "session.state", where=lambda m: m["session"]["queue"])
        assert [s["id"] for s in state["session"]["queue"]] == [catalog["songs"][1]["id"]]

        ws_h.send_json({"type": "session.control", "session_id": session["id"], "action": "next"})
        state = _until(ws_g, "session.state", where=lambda m: m["session"]["current_song"]["id"] != song)
        assert state["session"]["current_song"]["id"] == catalog["songs"][1]["id"] and state["session"]["queue"] == []

        # REST control path broadcasts too; ending the session notifies everyone.
        client.post(f"/api/v1/sessions/{session['id']}/control", json={"action": "seek", "position_ms": 700},
                    headers=factory.headers(host))
        assert _until(ws_g, "session.state", where=lambda m: m["session"]["position_ms"] == 700)
        client.delete(f"/api/v1/sessions/{session['id']}", headers=factory.headers(host))
        assert _until(ws_g, "session.ended")["session_id"] == session["id"]
    assert client.get("/api/v1/sessions/active", headers=factory.headers(guest)).json() == []


def test_user_channel_receives_subscription_updates(client, factory):
    user = factory.user()
    with client.websocket_connect(WS) as ws:
        _auth(ws, user)
        ws.send_json({"type": "subscribe", "channel": "user:me"})
        _until(ws, "subscribed")
        h = factory.headers(user)
        session = client.post("/api/v1/billing/checkout", json={"plan": "premium_monthly"}, headers=h).json()["url"].split("=")[1]
        client.post("/api/v1/billing/dev/complete", json={"session": session}, headers=h)
        assert _until(ws, "subscription.updated")["status"] == "active"
