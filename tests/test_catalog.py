from app.core.permissions import RoleName
from tests.conftest import PNG_1PX, make_ogg


def test_listeners_cannot_edit_catalog(client, factory):
    h = factory.headers(factory.user())
    assert client.post("/api/v1/artists", json={"name": "X"}, headers=h).status_code == 403
    assert client.post("/api/v1/genres", json={"name": "X"}, headers=h).status_code == 403
    assert client.post("/api/v1/artists", json={"name": "X"}).status_code == 401


def test_catalog_crud(client, catalog):
    h = catalog["headers"]
    artist = catalog["artist"]
    assert artist["slug"] == "neon-drift"
    twin = client.post("/api/v1/artists", json={"name": "Neon Drift"}, headers=h).json()
    assert twin["slug"] == "neon-drift-2"

    album = client.get(f"/api/v1/albums/{catalog['album']['id']}").json()
    assert [s["title"] for s in album["songs"]] == ["Midnight Run", "Chrome Hearts", "Afterglow"]
    assert album["total_duration_ms"] == sum(s["duration_ms"] for s in album["songs"])
    assert album["songs"][0]["duration_ms"] == 1250  # read from the audio file itself

    upd = client.patch(f"/api/v1/albums/{album['id']}", json={"title": "Night Drive (Deluxe)"}, headers=h)
    assert upd.json()["title"] == "Night Drive (Deluxe)"
    cover = client.post(f"/api/v1/albums/{album['id']}/cover", headers=h, files={"file": ("c.png", PNG_1PX, "image/png")})
    assert cover.status_code == 200 and cover.json()["cover_url"].startswith("/api/v1/media/images/covers/")

    # Artists with content can't be deleted; empty ones can.
    blocked = client.delete(f"/api/v1/artists/{artist['id']}", headers=h)
    assert blocked.status_code == 409 and blocked.json()["error"]["code"] == "artist_has_content"
    assert client.delete(f"/api/v1/artists/{twin['id']}", headers=h).status_code == 200

    detail = client.get(f"/api/v1/artists/{artist['id']}").json()
    assert detail["follower_count"] == 0 and detail["is_followed"] is None
    top = client.get(f"/api/v1/artists/{artist['id']}/top-songs").json()
    assert len(top) == 3


def test_song_listing_filters_and_sorting(client, catalog):
    page = client.get("/api/v1/songs", params={"genre": "synthwave", "sort": "title", "page_size": 2}).json()
    assert page["total"] == 3 and page["pages"] == 2
    assert [s["title"] for s in page["items"]] == ["Afterglow", "Chrome Hearts"]
    assert client.get("/api/v1/songs", params={"genre": "jazz"}).json()["total"] == 0
    assert client.get("/api/v1/songs", params={"page_size": 101}).status_code == 422


def test_unpublished_songs_are_hidden_from_listeners(client, catalog, factory):
    song = catalog["songs"][0]
    client.patch(f"/api/v1/songs/{song['id']}", json={"is_published": False}, headers=catalog["headers"])
    assert client.get(f"/api/v1/songs/{song['id']}").status_code == 404
    assert client.get(f"/api/v1/songs/{song['id']}", headers=catalog["headers"]).status_code == 200
    listed = client.get("/api/v1/songs", params={"include_unpublished": True}).json()
    assert listed["total"] == 2  # flag ignored for non-staff


def test_invalid_audio_upload_rejected(client, catalog):
    res = client.post("/api/v1/songs", headers=catalog["headers"],
                      data={"title": "Bad", "artist_id": catalog["artist"]["id"]},
                      files={"file": ("bad.mp3", b"not really audio" * 100, "audio/mpeg")})
    assert res.status_code == 422 and res.json()["error"]["code"] == "invalid_upload"


def test_streaming_with_range_requests(client, catalog, factory):
    user = factory.user()
    h = factory.headers(user)
    song = catalog["songs"][0]
    assert client.get(f"/api/v1/songs/{song['id']}/stream-url").status_code == 401
    info = client.get(f"/api/v1/songs/{song['id']}/stream-url", headers=h).json()
    assert info["mime_type"] == "audio/ogg"

    full = client.get(info["url"])
    assert full.status_code == 200 and full.headers["accept-ranges"] == "bytes"
    size = int(full.headers["content-length"])
    assert full.content[:4] == b"OggS" and len(full.content) == size

    part = client.get(info["url"], headers={"Range": "bytes=100-199"})
    assert part.status_code == 206
    assert part.headers["content-range"] == f"bytes 100-199/{size}"
    assert part.content == full.content[100:200]

    tail = client.get(info["url"], headers={"Range": "bytes=-50"})
    assert tail.content == full.content[-50:]
    bad = client.get(info["url"], headers={"Range": f"bytes={size}-"})
    assert bad.status_code == 416

    # The token is scoped to one song.
    other = catalog["songs"][1]["id"]
    assert client.get(info["url"].replace(song["id"], other, 1)).status_code == 403
    assert client.get(f"/api/v1/stream/{song['id']}?token=forged").status_code == 401
    head = client.head(info["url"])
    assert head.status_code == 200 and int(head.headers["content-length"]) == size


def test_premium_only_songs_require_entitlement(client, catalog, factory):
    premium_song = catalog["songs"][2]
    free_user, premium_user = factory.user(), factory.user(premium=True)
    denied = client.get(f"/api/v1/songs/{premium_song['id']}/stream-url", headers=factory.headers(free_user))
    assert denied.status_code == 402 and denied.json()["error"]["code"] == "premium_required"
    allowed = client.get(f"/api/v1/songs/{premium_song['id']}/stream-url", headers=factory.headers(premium_user))
    assert allowed.status_code == 200


def test_audio_is_not_exposed_through_media(client, catalog, db):
    from app.models import Song

    key = db.get(Song, catalog["songs"][0]["id"]).audio_key
    assert client.get(f"/api/v1/media/{key}").status_code == 404
    assert client.get("/api/v1/media/images/../audio/x.ogg").status_code == 404


def test_replace_audio_and_delete_song(client, catalog):
    h = catalog["headers"]
    song = catalog["songs"][0]
    res = client.put(f"/api/v1/songs/{song['id']}/audio", headers=h,
                     files={"file": ("new.ogg", make_ogg(3.0), "audio/ogg")})
    assert res.status_code == 200 and res.json()["duration_ms"] == 3000
    assert client.delete(f"/api/v1/songs/{song['id']}", headers=h).status_code == 200
    assert client.get(f"/api/v1/songs/{song['id']}").status_code == 404


def test_genres(client, catalog, factory):
    admin_h = factory.headers(factory.user(RoleName.admin))
    genres = client.get("/api/v1/genres").json()
    assert genres[0]["slug"] == "synthwave"
    dup = client.post("/api/v1/genres", json={"name": "synthwave"}, headers=admin_h)
    assert dup.status_code == 409
    gid = genres[0]["id"]
    assert client.patch(f"/api/v1/genres/{gid}", json={"color": "#00ff00"}, headers=admin_h).json()["color"] == "#00ff00"
    assert client.delete(f"/api/v1/genres/{gid}", headers=admin_h).status_code == 200
    song = client.get(f"/api/v1/songs/{catalog['songs'][0]['id']}").json()
    assert song["genre"] is None  # ON DELETE SET NULL
