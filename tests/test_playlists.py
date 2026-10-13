from sqlalchemy import select

from app.models import PlaylistTrack


def _titles(playlist):
    return [t["song"]["title"] for t in playlist["tracks"]]


def test_playlist_lifecycle_and_reorder(client, catalog, factory, db):
    user = factory.user()
    h = factory.headers(user)
    ids = [s["id"] for s in catalog["songs"][:2]]
    pl = client.post("/api/v1/playlists", json={"name": "Road Trip"}, headers=h).json()
    assert pl["is_owner"] and pl["can_edit"] and pl["track_count"] == 0

    pl = client.post(f"/api/v1/playlists/{pl['id']}/tracks", json={"song_ids": ids}, headers=h).json()
    assert _titles(pl) == ["Midnight Run", "Chrome Hearts"]
    pl = client.post(f"/api/v1/playlists/{pl['id']}/tracks", json={"song_ids": [ids[1]], "position": 0}, headers=h).json()
    assert _titles(pl) == ["Chrome Hearts", "Midnight Run", "Chrome Hearts"]  # duplicates allowed

    pl = client.patch(f"/api/v1/playlists/{pl['id']}/tracks/reorder", json={"from_index": 0, "to_index": 2}, headers=h).json()
    assert _titles(pl) == ["Midnight Run", "Chrome Hearts", "Chrome Hearts"]
    pl = client.patch(f"/api/v1/playlists/{pl['id']}/tracks/reorder", json={"from_index": 2, "to_index": 0}, headers=h).json()
    assert _titles(pl) == ["Chrome Hearts", "Midnight Run", "Chrome Hearts"]
    assert client.patch(f"/api/v1/playlists/{pl['id']}/tracks/reorder", json={"from_index": 0, "to_index": 9},
                        headers=h).status_code == 422

    pl = client.delete(f"/api/v1/playlists/{pl['id']}/tracks/{pl['tracks'][1]['id']}", headers=h).json()
    assert _titles(pl) == ["Chrome Hearts", "Chrome Hearts"]
    positions = db.scalars(select(PlaylistTrack.position).where(PlaylistTrack.playlist_id == pl["id"])
                           .order_by(PlaylistTrack.position)).all()
    assert positions == [0, 1]  # no gaps after removal

    missing = client.post(f"/api/v1/playlists/{pl['id']}/tracks",
                          json={"song_ids": ["00000000-0000-0000-0000-000000000000"]}, headers=h)
    assert missing.status_code == 404

    mine = client.get("/api/v1/me/playlists", headers=h).json()
    assert mine[0]["name"] == "Road Trip" and mine[0]["track_count"] == 2
    assert client.delete(f"/api/v1/playlists/{pl['id']}", headers=h).status_code == 200


def test_private_playlists_are_invisible_and_uneditable(client, catalog, factory):
    owner, stranger = factory.user(), factory.user()
    pl = client.post("/api/v1/playlists", json={"name": "Secret", "is_public": False}, headers=factory.headers(owner)).json()
    assert client.get(f"/api/v1/playlists/{pl['id']}").status_code == 404
    assert client.get(f"/api/v1/playlists/{pl['id']}", headers=factory.headers(stranger)).status_code == 404

    public = client.post("/api/v1/playlists", json={"name": "Open"}, headers=factory.headers(owner)).json()
    view = client.get(f"/api/v1/playlists/{public['id']}", headers=factory.headers(stranger)).json()
    assert view["can_edit"] is False and view["collab_invite_code"] is None
    add = client.post(f"/api/v1/playlists/{public['id']}/tracks", json={"song_ids": [catalog["songs"][0]["id"]]},
                      headers=factory.headers(stranger))
    assert add.status_code == 403
    assert client.delete(f"/api/v1/playlists/{public['id']}", headers=factory.headers(stranger)).status_code == 403


def test_collaborative_playlists(client, catalog, factory):
    free, premium, friend = factory.user(), factory.user(premium=True), factory.user()
    denied = client.post("/api/v1/playlists", json={"name": "Jam", "is_public": False, "is_collaborative": True},
                         headers=factory.headers(free))
    assert denied.status_code == 402
    invalid = client.post("/api/v1/playlists", json={"name": "Jam", "is_collaborative": True}, headers=factory.headers(premium))
    assert invalid.status_code == 422  # collaborative + public

    pl = client.post("/api/v1/playlists", json={"name": "Jam", "is_public": False, "is_collaborative": True},
                     headers=factory.headers(premium)).json()
    code = pl["collab_invite_code"]
    assert code
    assert client.post(f"/api/v1/playlists/{pl['id']}/join", json={"code": "wrong-code"},
                       headers=factory.headers(friend)).status_code == 404
    joined = client.post(f"/api/v1/playlists/{pl['id']}/join", json={"code": code}, headers=factory.headers(friend)).json()
    assert joined["can_edit"] and not joined["is_owner"]
    assert [c["display_name"] for c in joined["collaborators"]] == [friend.display_name]

    added = client.post(f"/api/v1/playlists/{pl['id']}/tracks", json={"song_ids": [catalog["songs"][0]["id"]]},
                        headers=factory.headers(friend)).json()
    assert added["tracks"][0]["added_by"]["id"] == str(friend.id)
    assert any(p["id"] == pl["id"] for p in client.get("/api/v1/me/playlists", headers=factory.headers(friend)).json())

    # Regenerating the code invalidates the old link.
    new = client.post(f"/api/v1/playlists/{pl['id']}/invite", headers=factory.headers(premium)).json()
    assert new["collab_invite_code"] != code
    client.delete(f"/api/v1/playlists/{pl['id']}/collaborators/{friend.id}", headers=factory.headers(premium))
    assert client.get(f"/api/v1/playlists/{pl['id']}", headers=factory.headers(friend)).status_code == 404


def test_free_playlist_limit(client, factory, settings, monkeypatch):
    monkeypatch.setattr(settings, "free_playlist_limit", 2)
    free, premium = factory.user(), factory.user(premium=True)
    for i in range(2):
        assert client.post("/api/v1/playlists", json={"name": f"P{i}"}, headers=factory.headers(free)).status_code == 201
    over = client.post("/api/v1/playlists", json={"name": "P3"}, headers=factory.headers(free))
    assert over.status_code == 402 and over.json()["error"]["details"]["limit"] == 2
    for i in range(3):
        assert client.post("/api/v1/playlists", json={"name": f"Q{i}"}, headers=factory.headers(premium)).status_code == 201


def test_update_playlist_visibility(client, factory):
    owner = factory.user(premium=True)
    h = factory.headers(owner)
    pl = client.post("/api/v1/playlists", json={"name": "Mix"}, headers=h).json()
    upd = client.patch(f"/api/v1/playlists/{pl['id']}", json={"is_collaborative": True}, headers=h).json()
    assert upd["is_collaborative"] and not upd["is_public"] and upd["collab_invite_code"]
    off = client.patch(f"/api/v1/playlists/{pl['id']}", json={"is_collaborative": False, "is_public": True}, headers=h).json()
    assert off["is_public"] and off["collab_invite_code"] is None
