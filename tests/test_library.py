def test_likes_are_idempotent(client, catalog, factory):
    h = factory.headers(factory.user())
    sid = catalog["songs"][0]["id"]
    for _ in range(2):
        assert client.put(f"/api/v1/me/liked-songs/{sid}", headers=h).status_code == 200
    liked = client.get("/api/v1/me/liked-songs", headers=h).json()
    assert liked["total"] == 1 and liked["items"][0]["song"]["liked"] is True
    other = catalog["songs"][1]["id"]
    contains = client.get("/api/v1/me/liked-songs/contains", params={"ids": f"{sid},{other},junk"}, headers=h).json()
    assert contains["ids"] == {sid: True, other: False}
    assert client.get(f"/api/v1/songs/{sid}", headers=h).json()["liked"] is True
    for _ in range(2):
        assert client.delete(f"/api/v1/me/liked-songs/{sid}", headers=h).status_code == 200
    assert client.get("/api/v1/me/liked-songs", headers=h).json()["total"] == 0


def test_follow_and_save(client, catalog, factory):
    h = factory.headers(factory.user())
    artist, album = catalog["artist"]["id"], catalog["album"]["id"]
    client.put(f"/api/v1/me/following/{artist}", headers=h)
    assert client.get(f"/api/v1/artists/{artist}", headers=h).json()["is_followed"] is True
    assert client.get(f"/api/v1/artists/{artist}").json()["follower_count"] == 1
    assert [a["id"] for a in client.get("/api/v1/me/following", headers=h).json()] == [artist]

    client.put(f"/api/v1/me/albums/{album}", headers=h)
    assert client.get(f"/api/v1/albums/{album}", headers=h).json()["is_saved"] is True
    assert len(client.get("/api/v1/me/albums", headers=h).json()) == 1
    client.delete(f"/api/v1/me/albums/{album}", headers=h)
    assert client.get("/api/v1/me/albums", headers=h).json() == []
    assert client.put("/api/v1/me/following/00000000-0000-0000-0000-000000000000", headers=h).status_code == 404


def test_saved_playlists_respect_visibility(client, factory):
    owner, fan = factory.user(), factory.user()
    pl = client.post("/api/v1/playlists", json={"name": "Hits"}, headers=factory.headers(owner)).json()
    assert client.put(f"/api/v1/me/saved-playlists/{pl['id']}", headers=factory.headers(fan)).status_code == 200
    assert len(client.get("/api/v1/me/saved-playlists", headers=factory.headers(fan)).json()) == 1
    client.patch(f"/api/v1/playlists/{pl['id']}", json={"is_public": False}, headers=factory.headers(owner))
    assert client.get("/api/v1/me/saved-playlists", headers=factory.headers(fan)).json() == []


def test_history_and_play_counts(client, catalog, factory):
    h = factory.headers(factory.user())
    song = catalog["songs"][0]
    short = client.post("/api/v1/me/history", json={"song_id": song["id"], "ms_played": 200}, headers=h)
    assert short.status_code == 201
    assert client.get(f"/api/v1/songs/{song['id']}").json()["play_count"] == 0
    client.post("/api/v1/me/history", json={"song_id": song["id"], "ms_played": 1250, "completed": True,
                                            "context_type": "album", "context_id": catalog["album"]["id"]}, headers=h)
    assert client.get(f"/api/v1/songs/{song['id']}").json()["play_count"] == 1

    hist = client.get("/api/v1/me/history", headers=h).json()
    assert hist["total"] == 2 and hist["items"][0]["context_type"] == "album"
    recent = client.get("/api/v1/me/recently-played", headers=h).json()
    assert [s["id"] for s in recent] == [song["id"]]  # distinct songs
    # every context the web player reports must be accepted (regression: these were rejected with 422)
    for ctx in ("recommendations", "trending", "history", "liked", "genre", "language", "chart", "podcast", "private-album", "mix"):
        res = client.post("/api/v1/me/history", json={"song_id": song["id"], "ms_played": 10, "context_type": ctx}, headers=h)
        assert res.status_code == 201, ctx
    client.delete("/api/v1/me/history", headers=h)
    client.post("/api/v1/me/history", json={"song_id": song["id"], "ms_played": 200}, headers=h)
    client.post("/api/v1/me/history", json={"song_id": song["id"], "ms_played": 1250, "completed": True,
                                            "context_type": "album", "context_id": catalog["album"]["id"]}, headers=h)
    bad = client.post("/api/v1/me/history", json={"song_id": song["id"], "ms_played": 1, "context_type": "evil"}, headers=h)
    assert bad.status_code == 422
    client.delete("/api/v1/me/history", headers=h)
    assert client.get("/api/v1/me/history", headers=h).json()["total"] == 0


def test_player_state_roundtrip(client, catalog, factory):
    h = factory.headers(factory.user())
    empty = client.get("/api/v1/me/player", headers=h).json()
    assert empty["current_song"] is None and empty["volume"] == 0.8
    ids = [s["id"] for s in catalog["songs"]]
    body = {"current_song_id": ids[0], "position_ms": 500, "queue": ids[1:], "shuffle": True,
            "repeat_mode": "all", "volume": 0.5, "context": {"type": "album", "id": catalog["album"]["id"]}}
    assert client.put("/api/v1/me/player", json=body, headers=h).status_code == 200
    body["position_ms"] = 900
    client.put("/api/v1/me/player", json=body, headers=h)  # upsert
    state = client.get("/api/v1/me/player", headers=h).json()
    assert state["current_song"]["id"] == ids[0] and state["position_ms"] == 900
    assert [s["id"] for s in state["queue"]] == ids[1:]
    assert state["shuffle"] and state["repeat_mode"] == "all" and state["volume"] == 0.5
    assert client.put("/api/v1/me/player", json={**body, "volume": 2}, headers=h).status_code == 422


def test_search(client, catalog, factory):
    owner = factory.user()
    client.post("/api/v1/playlists", json={"name": "Neon Nights"}, headers=factory.headers(owner))
    res = client.get("/api/v1/search", params={"q": "neon"}).json()
    assert res["artists"]["items"][0]["name"] == "Neon Drift"
    assert res["songs"]["total"] == 3  # matched through the artist name
    assert res["playlists"]["items"][0]["name"] == "Neon Nights"

    partial = client.get("/api/v1/search", params={"q": "chro", "type": "song"}).json()
    assert partial["songs"]["items"][0]["title"] == "Chrome Hearts" and partial["artists"] is None
    sorted_ = client.get("/api/v1/search", params={"q": "neon", "type": "song", "sort": "title"}).json()
    assert [s["title"] for s in sorted_["songs"]["items"]] == ["Afterglow", "Chrome Hearts", "Midnight Run"]
    assert client.get("/api/v1/search", params={"q": "%_%", "type": "song"}).json()["songs"]["total"] == 0
    assert client.get("/api/v1/search", params={"q": "neon", "genre": "synthwave", "type": "album"}).json()["albums"]["total"] == 1


def test_home_feed_and_recommendations(client, catalog, factory):
    h = factory.headers(factory.user())
    client.put(f"/api/v1/me/liked-songs/{catalog['songs'][0]['id']}", headers=h)
    anon = client.get("/api/v1/browse/home").json()
    assert anon["featured"][0]["title"] == "Night Drive" and anon["recommended"] == []
    feed = client.get("/api/v1/browse/home", headers=h).json()
    rec_ids = {s["id"] for s in feed["recommended"]}
    assert catalog["songs"][0]["id"] not in rec_ids  # already liked
    assert {catalog["songs"][1]["id"], catalog["songs"][2]["id"]} <= rec_ids  # same genre/artist
    assert len(client.get("/api/v1/me/recommendations", headers=h).json()) == 2
