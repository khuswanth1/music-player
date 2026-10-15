"""Several accounts at once: everything personal stays with its owner, and the personal features follow each person."""

API = "/api/v1"


def _sid(catalog, i=0):
    return catalog["songs"][i]["id"]


def test_one_persons_library_is_invisible_to_everyone_else(client, catalog, factory):
    a, b = factory.user(), factory.user()
    ha, hb = factory.headers(a), factory.headers(b)
    song, artist = _sid(catalog), catalog["artist"]["id"]

    client.put(f"{API}/me/liked-songs/{song}", headers=ha)
    client.put(f"{API}/me/following/{artist}", headers=ha)
    client.post(f"{API}/me/history", json={"song_id": song, "ms_played": 45000}, headers=ha)
    client.put(f"{API}/me/languages", json={"languages": ["te"]}, headers=ha)
    client.put(f"{API}/me/settings", json={"home_hidden": ["genres"], "density": "compact"}, headers=ha)
    secret = client.post(f"{API}/playlists", json={"name": "Only mine", "is_public": False}, headers=ha).json()
    client.post(f"{API}/playlists/{secret['id']}/tracks", json={"song_ids": [song]}, headers=ha)

    # A sees all of it …
    assert client.get(f"{API}/me/liked-songs", headers=ha).json()["total"] == 1
    assert [p["name"] for p in client.get(f"{API}/me/playlists", headers=ha).json()] == ["Only mine"]
    # … B sees none of it
    assert client.get(f"{API}/me/liked-songs", headers=hb).json()["total"] == 0
    assert client.get(f"{API}/me/following", headers=hb).json() == []
    assert client.get(f"{API}/me/history", headers=hb).json()["total"] == 0
    assert client.get(f"{API}/me/playlists", headers=hb).json() == []
    me_b = client.get(f"{API}/me", headers=hb).json()
    assert me_b["preferred_languages"] == [] and me_b["ui_prefs"]["home_hidden"] == [] and me_b["ui_prefs"]["density"] == "comfortable"
    # B can't open, change or delete A's private playlist, and A's data is untouched by B's attempts
    assert client.get(f"{API}/playlists/{secret['id']}", headers=hb).status_code == 404
    assert client.patch(f"{API}/playlists/{secret['id']}", json={"name": "Hacked"}, headers=hb).status_code in (403, 404)
    assert client.post(f"{API}/playlists/{secret['id']}/tracks", json={"song_ids": [song]}, headers=hb).status_code in (403, 404)
    assert client.delete(f"{API}/playlists/{secret['id']}", headers=hb).status_code in (403, 404)
    assert client.get(f"{API}/playlists/{secret['id']}", headers=ha).json()["name"] == "Only mine"
    # B's own actions don't reach A either
    client.put(f"{API}/me/liked-songs/{_sid(catalog, 1)}", headers=hb)
    assert client.get(f"{API}/me/liked-songs", headers=ha).json()["total"] == 1
    # nothing personal without signing in
    for path in ("/me/liked-songs", "/me/playlists", "/me/history", "/me/mixes", "/me/for-you"):
        assert client.get(f"{API}{path}").status_code == 401, path


def test_playlist_management_by_its_owner(client, catalog, factory):
    owner = factory.user()
    h = factory.headers(owner)
    ids = [s["id"] for s in catalog["songs"][:2]]
    pl = client.post(f"{API}/playlists", json={"name": "Road trip"}, headers=h).json()
    client.patch(f"{API}/playlists/{pl['id']}", json={"name": "Night drive", "is_public": False}, headers=h)
    detail = client.post(f"{API}/playlists/{pl['id']}/tracks", json={"song_ids": ids}, headers=h).json()
    assert detail["name"] == "Night drive" and detail["is_public"] is False and len(detail["tracks"]) == 2
    first, second = detail["tracks"][0]["id"], detail["tracks"][1]["id"]
    moved = client.patch(f"{API}/playlists/{pl['id']}/tracks/reorder", json={"from_index": 1, "to_index": 0}, headers=h)
    assert moved.status_code == 200 and moved.json()["tracks"][0]["id"] == second
    left = client.delete(f"{API}/playlists/{pl['id']}/tracks/{first}", headers=h).json()
    assert len(left["tracks"]) == 1
    assert client.delete(f"{API}/playlists/{pl['id']}", headers=h).status_code == 200
    assert client.get(f"{API}/playlists/{pl['id']}", headers=h).status_code == 404


def test_display_settings_are_saved_per_person_and_validated(client, factory):
    a, b = factory.user(), factory.user()
    ha, hb = factory.headers(a), factory.headers(b)
    saved = client.put(f"{API}/me/settings", headers=ha,
                       json={"home_order": ["trending", "mixes", "mixes"], "home_hidden": ["new"], "density": "compact"})
    assert saved.status_code == 200 and saved.json()["home_order"] == ["trending", "mixes"]  # duplicates dropped
    prefs = client.get(f"{API}/me", headers=ha).json()["ui_prefs"]  # comes back with the profile after login
    assert prefs == {"home_order": ["trending", "mixes"], "home_hidden": ["new"], "density": "compact"}
    assert client.get(f"{API}/me", headers=hb).json()["ui_prefs"]["home_order"] == []
    assert client.put(f"{API}/me/settings", json={"home_order": ["not-a-shelf"]}, headers=ha).status_code == 422
    assert client.put(f"{API}/me/settings", json={"density": "huge"}, headers=ha).status_code == 422
    assert client.put(f"{API}/me/settings", json={}).status_code == 401


def test_for_you_picks_follow_each_person_and_skip_what_they_already_follow(client, catalog, factory):
    fan, newcomer = factory.user(), factory.user()
    hf, hn = factory.headers(fan), factory.headers(newcomer)
    artist = catalog["artist"]["id"]
    client.put(f"{API}/me/liked-songs/{_sid(catalog)}", headers=hf)  # the genre of this song becomes their taste

    picks = client.get(f"{API}/me/for-you", headers=hf).json()
    assert artist in {a["id"] for a in picks["artists"]}
    assert catalog["album"]["id"] in {a["id"] for a in picks["albums"]}
    client.put(f"{API}/me/following/{artist}", headers=hf)
    assert artist not in {a["id"] for a in client.get(f"{API}/me/for-you", headers=hf).json()["artists"]}
    # someone who follows nobody is still offered the artist: a follow by the fan doesn't affect them
    assert artist in {a["id"] for a in client.get(f"{API}/me/for-you", headers=hn).json()["artists"]}
    # and a person's own playlists never come back as "other people's"
    mine = client.post(f"{API}/playlists", json={"name": "Mine"}, headers=hf).json()
    client.post(f"{API}/playlists/{mine['id']}/tracks", json={"song_ids": [_sid(catalog)]}, headers=hf)
    assert mine["id"] not in {p["id"] for p in client.get(f"{API}/me/for-you", headers=hf).json()["playlists"]}
    assert mine["id"] in {p["id"] for p in client.get(f"{API}/me/for-you", headers=hn).json()["playlists"]}
