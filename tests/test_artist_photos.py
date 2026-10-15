import httpx
import pytest

from app.music import artist_photos


def _wiki(pages):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"query": {"pages": pages}})
    return httpx.MockTransport(handler)


@pytest.fixture(autouse=True)
def _reset():
    artist_photos._cache.clear()
    yield
    artist_photos.set_transport(None)
    artist_photos._cache.clear()


def test_search_name_takes_the_lead_singer_of_a_credit():
    assert artist_photos.search_name("A.R. Rahman & Arijit Singh") == "A.R. Rahman"
    assert artist_photos.search_name("Sagar, M.M. Manasi") == "Sagar"
    assert artist_photos.search_name("Kishore Kumar (singer)") == "Kishore Kumar"


def test_only_a_page_about_that_musician_is_used():
    artist_photos.set_transport(_wiki([
        {"index": 1, "title": "Kishore (film)", "description": "2019 Indian film", "thumbnail": {"source": "https://x/film.jpg"}},
        {"index": 2, "title": "Kishore Kumar", "description": "Indian playback singer", "thumbnail": {"source": "https://x/kk.jpg"}},
    ]))
    assert artist_photos.portrait_url("Kishore Kumar") == "https://x/kk.jpg"


def test_a_namesake_who_is_not_a_musician_or_has_no_photo_gives_nothing():
    artist_photos.set_transport(_wiki([
        {"index": 1, "title": "Pushpa", "description": "Indian film series", "thumbnail": {"source": "https://x/film.jpg"}},
        {"index": 2, "title": "Pushpa Srivatsan", "description": "Indian singer"},  # right person, no image
    ]))
    assert artist_photos.portrait_url("Pushpa Srivatsan") is None
    assert artist_photos.portrait_url("#UPLOAD_CHANNEL") is None  # upload-channel names are never looked up


def test_a_network_failure_is_not_cached_as_a_miss():
    artist_photos.set_transport(httpx.MockTransport(lambda r: httpx.Response(503)))
    assert artist_photos.portrait_url("Shreya Ghoshal") is None
    artist_photos.set_transport(_wiki([{"index": 1, "title": "Shreya Ghoshal", "description": "Indian singer",
                                        "thumbnail": {"source": "https://x/sg.jpg"}}]))
    assert artist_photos.portrait_url("Shreya Ghoshal") == "https://x/sg.jpg"


def test_endpoint_saves_found_photos_and_skips_artists_that_have_one(client, catalog):
    h = catalog["headers"]
    artist_id = catalog["artist"]["id"]
    artist_photos.set_transport(_wiki([{"index": 1, "title": "Neon Drift", "description": "Synthwave musician",
                                        "thumbnail": {"source": "https://x/neon.jpg"}}]))
    res = client.post("/api/v1/music/artists/photos", json={"ids": [artist_id]}, headers=h)
    assert res.status_code == 200 and res.json() == {artist_id: "https://x/neon.jpg"}
    assert client.get(f"/api/v1/artists/{artist_id}").json()["image_url"] == "https://x/neon.jpg"
    artist_photos.set_transport(httpx.MockTransport(lambda r: pytest.fail("already has a photo: must not look it up")))
    assert client.post("/api/v1/music/artists/photos", json={"ids": [artist_id]}, headers=h).json() == {}
