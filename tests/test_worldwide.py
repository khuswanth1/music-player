"""Podcasts, soundtracks, artists, private albums, unified search and query understanding (provider traffic mocked)."""

import httpx
import pytest

from app.db.session import SessionLocal
from app.models import Song
from app.music import http as music_http
from app.music import queryparse
from app.music.providers import register_provider, unregister_provider
from app.podcasts import providers as podcast_providers
from app.podcasts import rss
from tests.music_fakes import FakeProvider, routes, track

FEED = """<?xml version="1.0"?>
<rss version="2.0" xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd">
<channel>
  <title>Telugu Talks</title><language>te-IN</language><itunes:author>Test Studio</itunes:author>
  <description>&lt;p&gt;Weekly talks&lt;/p&gt;</description>
  <itunes:image href="https://img.test/cover.jpg"/>
  <item><title>Episode 2</title><guid>g2</guid><pubDate>Mon, 05 Oct 2026 03:00:00 GMT</pubDate>
    <itunes:duration>01:02:03</itunes:duration>
    <enclosure url="https://cdn.test/ep2.mp3" type="audio/mpeg" length="1"/></item>
  <item><title>Episode 1</title><guid>g1</guid><pubDate>Mon, 28 Sep 2026 03:00:00 GMT</pubDate>
    <enclosure url="https://cdn.test/ep1.mp3" type="audio/mpeg" length="1"/></item>
  <item><title>No audio</title><guid>g0</guid><enclosure url="javascript:alert(1)" type="audio/mpeg"/></item>
</channel></rss>"""

ITUNES_PODCAST = {
    "collectionId": 42,
    "trackId": 42,
    "collectionName": "Telugu Talks",
    "artistName": "Test Studio",
    "feedUrl": "https://feeds.test/telugu.xml",
    "artworkUrl600": "https://img.test/cover.jpg",
    "genres": ["Society & Culture"],
    "trackCount": 2,
    "releaseDate": "2026-10-05T03:00:00Z",
    "collectionViewUrl": "https://podcasts.apple.com/podcast/id42",
    "country": "IND",
}


@pytest.fixture
def podcasts_net(monkeypatch):
    monkeypatch.setattr(podcast_providers, "public_http_url", lambda url: True)

    def itunes(request: httpx.Request) -> httpx.Response:
        import json

        return httpx.Response(
            200, content=json.dumps({"resultCount": 1, "results": [ITUNES_PODCAST]}), headers={"content-type": "application/json"}
        )

    def feed(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=FEED, headers={"content-type": "application/rss+xml"})

    music_http.set_transport(routes({"itunes.apple.com/search": itunes, "itunes.apple.com/lookup": itunes, "feeds.test/telugu.xml": feed}))


@pytest.fixture
def listener(factory):
    user = factory.user()
    return user, factory.headers(user)


# --- query understanding ---------------------------------------------------------------------


def test_query_hints():
    h = queryparse.parse("Telugu old songs 1990")
    assert (h.language, h.era, h.year_from, h.year_to, h.rest) == ("te", "old", 1990, 1990, "")
    h = queryparse.parse("korean movie soundtracks")
    assert (h.language, h.movie, h.rest) == ("ko", True, "")
    h = queryparse.parse("latest podcasts")
    assert (h.podcast, h.era, h.rest) == (True, "latest", "")
    h = queryparse.parse("hindi 90s songs in india")
    assert (h.language, h.country, h.year_from, h.year_to) == ("hi", "IN", 1990, 1999)
    assert queryparse.parse("Arijit Singh").rest == "Arijit Singh"  # names are never swallowed by hints


# --- RSS ---------------------------------------------------------------------------------------


def test_rss_parsing_keeps_only_playable_http_enclosures():
    meta, episodes = rss.parse_feed(FEED)
    assert meta["title"] == "Telugu Talks" and meta["language"] == "te-IN" and meta["description"] == "Weekly talks"
    assert [e["title"] for e in episodes] == ["Episode 2", "Episode 1", "No audio"]
    assert episodes[0]["duration_s"] == 3723 and episodes[0]["audio_url"] == "https://cdn.test/ep2.mp3"
    assert episodes[2]["audio_url"] is None  # javascript: is never accepted as an audio URL


def test_rss_rejects_entity_expansion():
    bomb = (
        '<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "aaaa"><!ENTITY b "&a;&a;&a;&a;">]><rss><channel><title>&b;</title></channel></rss>'
    )
    with pytest.raises(rss.FeedError):
        rss.parse_feed(bomb)


def test_feed_urls_must_be_public():
    assert not podcast_providers.public_http_url("http://127.0.0.1/feed")
    assert not podcast_providers.public_http_url("file:///etc/passwd")
    assert not podcast_providers.public_http_url("http://localhost:8000/x")


# --- podcasts API --------------------------------------------------------------------------------


def test_podcast_search_episodes_and_listener_state(client, podcasts_net, listener):
    _, h = listener
    res = client.get("/api/v1/podcasts/search", params={"q": "telugu", "language": "te"}, headers=h)
    assert res.status_code == 200, res.text
    body = res.json()
    show = body["podcasts"][0]
    # the language was read from the publisher's own feed, not guessed
    assert show["id"] == "itunes:42" and show["language"] == "te" and show["followed"] is False
    assert {p["key"]: p["status"] for p in body["providers"]}["podcastindex"] == "not_configured"

    eps = client.get("/api/v1/podcasts/itunes:42/episodes", headers=h).json()
    assert eps["total"] == 3 and eps["items"][0]["title"] == "Episode 2" and eps["items"][0]["playable"] is True
    assert eps["items"][2]["playable"] is False
    ep = eps["items"][0]

    assert client.put("/api/v1/me/podcasts/itunes:42", json={"title": "Telugu Talks"}, headers=h).status_code == 200
    assert [p["id"] for p in client.get("/api/v1/me/podcasts", headers=h).json()] == ["itunes:42"]
    snap = {"podcast_id": "itunes:42", "title": ep["title"], "audio_url": ep["audio_url"], "duration_s": ep["duration_s"]}
    assert client.put("/api/v1/me/episodes/save", params={"episode_id": ep["id"]}, json=snap, headers=h).status_code == 200
    assert (
        client.put("/api/v1/me/episodes/progress", json={**snap, "episode_id": ep["id"], "position_s": 120}, headers=h).status_code == 200
    )

    eps = client.get("/api/v1/podcasts/itunes:42/episodes", headers=h).json()
    assert eps["podcast"]["followed"] is True and eps["items"][0]["saved"] is True and eps["items"][0]["position_s"] == 120
    history = client.get("/api/v1/me/episodes/progress", headers=h).json()
    assert history["items"][0]["position_s"] == 120
    assert client.get("/api/v1/me/episodes", headers=h).json()[0]["position_s"] == 120

    # an episode id must belong to the podcast it is reported under
    bad = client.put("/api/v1/me/episodes/progress", json={**snap, "episode_id": "itunes:99#x", "position_s": 1}, headers=h)
    assert bad.status_code == 422
    assert client.delete("/api/v1/me/podcasts/itunes:42", headers=h).status_code == 200
    assert client.get("/api/v1/me/podcasts", headers=h).json() == []


def test_podcast_state_requires_sign_in(client):
    assert client.get("/api/v1/me/podcasts").status_code == 401
    assert client.put("/api/v1/me/episodes/progress", json={}).status_code == 401


# --- private albums ------------------------------------------------------------------------------


@pytest.fixture
def fake(settings, monkeypatch):
    FakeProvider.catalog = {}
    FakeProvider.calls = []
    register_provider(FakeProvider)
    monkeypatch.setattr(settings, "music_providers", ["fake"])
    yield FakeProvider
    unregister_provider("fake")


def _song_ids(client, h, fake, *titles):
    for i, t in enumerate(titles):
        fake.catalog[f"p{i}"] = track(f"p{i}", t)
    client.get("/api/v1/search/global", params={"q": "Alpha", "categories": "songs"}, headers=h)
    with SessionLocal() as db:
        return [str(s.id) for s in db.query(Song).filter(Song.source == "fake").order_by(Song.title)]


def test_private_albums_are_owner_only_until_shared(client, factory, fake):
    owner, other = factory.user(), factory.user()
    oh, xh = factory.headers(owner), factory.headers(other)
    ids = _song_ids(client, oh, fake, "Alpha A", "Alpha B")

    album = client.post("/api/v1/private-albums", json={"name": "Road trip"}, headers=oh).json()
    aid = album["id"]
    assert album["is_public"] is False and album["share_code"] is None
    res = client.post(f"/api/v1/private-albums/{aid}/tracks", json={"song_ids": ids}, headers=oh)
    assert res.status_code == 200, res.text
    detail = res.json()
    assert [t["song"]["title"] for t in detail["tracks"]] == ["Alpha A", "Alpha B"]
    assert (
        client.post(f"/api/v1/private-albums/{aid}/tracks", json={"song_ids": ids[:1]}, headers=oh).json()["track_count"] == 2
    )  # idempotent

    # nobody else can see, change or share it - and they can't tell it exists
    assert client.get(f"/api/v1/private-albums/{aid}", headers=xh).status_code == 404
    assert client.get(f"/api/v1/private-albums/{aid}").status_code == 401
    assert client.patch(f"/api/v1/private-albums/{aid}", json={"name": "Mine now"}, headers=xh).status_code == 404
    assert client.delete(f"/api/v1/private-albums/{aid}", headers=xh).status_code == 404
    assert client.get("/api/v1/private-albums", headers=xh).json() == []

    shared = client.patch(f"/api/v1/private-albums/{aid}", json={"is_public": True, "name": "Road trip 2"}, headers=oh).json()
    code = shared["share_code"]
    assert shared["name"] == "Road trip 2" and code
    public = client.get(f"/api/v1/private-albums/shared/{code}")  # no sign-in needed
    assert public.status_code == 200 and public.json()["share_code"] is None and len(public.json()["tracks"]) == 2
    assert client.get(f"/api/v1/private-albums/shared/{code}", headers=xh).json()["is_owner"] is False

    new_code = client.post(f"/api/v1/private-albums/{aid}/share", headers=oh).json()["share_code"]
    assert new_code != code and client.get(f"/api/v1/private-albums/shared/{code}").status_code == 404
    client.patch(f"/api/v1/private-albums/{aid}", json={"is_public": False}, headers=oh)
    assert client.get(f"/api/v1/private-albums/shared/{new_code}").status_code == 404

    item = detail["tracks"][0]["id"]
    after = client.delete(f"/api/v1/private-albums/{aid}/tracks/{item}", headers=oh).json()
    assert [t["position"] for t in after["tracks"]] == [0]
    client.patch(f"/api/v1/private-albums/{aid}", json={"is_favorite": True}, headers=oh)
    assert [a["is_favorite"] for a in client.get("/api/v1/private-albums", params={"favorites": True}, headers=oh).json()] == [True]
    assert client.delete(f"/api/v1/private-albums/{aid}", headers=oh).status_code == 200


# --- unified search ------------------------------------------------------------------------------


def test_global_search_returns_labelled_songs_and_facets(client, factory, fake):
    user = factory.user()
    h = factory.headers(user)
    fake.catalog["a"] = track("a", "Pallelona Song", language="te")
    fake.catalog["b"] = track("b", "Pallelona Song", language="te", artist="Other")  # same title, different artist: kept
    res = client.get(
        "/api/v1/search/global", params={"q": "telugu pallelona", "categories": "songs,facets,private_albums,playlists"}, headers=h
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["interpreted"]["language"] == "te" and body["interpreted"]["text"] == "pallelona"
    assert {s["access"] for s in body["songs"]} == {"full"} and len(body["songs"]) == 2
    assert [lang["code"] for lang in body["languages"]] == ["te"]
    assert client.get("/api/v1/search/global", params={"q": "x"}, headers=h).status_code == 422
    assert client.get("/api/v1/search/global", params={"q": "abc", "categories": "nope"}, headers=h).status_code == 422


def test_search_suggestions_and_history(client, factory, fake):
    user = factory.user()
    h = factory.headers(user)
    fake.catalog["a"] = track("a", "Pallelona Song", language="te")
    client.get("/api/v1/search/global", params={"q": "pallelona", "categories": "songs"}, headers=h)

    assert client.post("/api/v1/me/search-history", json={"query": "pallelona"}, headers=h).status_code == 201
    client.post("/api/v1/me/search-history", json={"query": "pallelona"}, headers=h)  # repeat doesn't duplicate
    client.post("/api/v1/me/search-history", json={"query": "telugu songs"}, headers=h)
    assert [r["query"] for r in client.get("/api/v1/me/search-history", headers=h).json()] == ["telugu songs", "pallelona"]

    items = client.get("/api/v1/search/suggestions", params={"q": "pall"}, headers=h).json()["items"]
    assert {i["type"] for i in items} >= {"recent", "song"}
    langs = client.get("/api/v1/search/suggestions", params={"q": "tel"}).json()["items"]
    assert any(i["type"] == "language" and i["href"] == "/language/te" for i in langs)

    client.delete("/api/v1/me/search-history", params={"query": "pallelona"}, headers=h)
    assert [r["query"] for r in client.get("/api/v1/me/search-history", headers=h).json()] == ["telugu songs"]
    client.delete("/api/v1/me/search-history", headers=h)
    assert client.get("/api/v1/me/search-history", headers=h).json() == []


# --- soundtracks ---------------------------------------------------------------------------------


def test_soundtracks_are_labelled_preview_and_language_comes_from_the_provider(client, settings, monkeypatch):
    monkeypatch.setattr(settings, "music_providers", ["itunes", "musicbrainz"])
    import json

    albums = {
        "resultCount": 3,
        "results": [
            {
                "wrapperType": "collection",
                "collectionId": 1,
                "collectionName": "Mallanna (Original Motion Picture Soundtrack)",
                "artistName": "Devi Sri Prasad",
                "primaryGenreName": "Telugu",
                "releaseDate": "2009-01-01T08:00:00Z",
                "trackCount": 8,
                "artworkUrl100": "https://img.test/a/100x100bb.jpg",
                "collectionViewUrl": "https://music.apple.com/album/1",
            },
            {
                "wrapperType": "collection",
                "collectionId": 2,
                "collectionName": "Some Pop Album",
                "artistName": "X",
                "primaryGenreName": "Pop",
                "releaseDate": "2020-01-01T08:00:00Z",
            },  # not a soundtrack: dropped
            {
                "wrapperType": "collection",
                "collectionId": 3,
                "collectionName": 'Fear Song (From "Devara Part 1") - Single',
                "artistName": "Anirudh",
                "primaryGenreName": "Soundtrack",
                "releaseDate": "2024-09-01T08:00:00Z",
            },  # language unknown
        ],
    }
    music_http.set_transport(
        routes(
            {
                "itunes.apple.com/search": lambda r: httpx.Response(
                    200, content=json.dumps(albums), headers={"content-type": "application/json"}
                ),
                "musicbrainz.org/ws/2/release": {"releases": []},
            }
        )
    )
    res = client.get("/api/v1/music/soundtracks", params={"q": "telugu movie songs"})
    assert res.status_code == 200, res.text
    items = {i["id"]: i for i in res.json()["items"]}
    # "Soundtrack" genre says nothing about language, so with a Telugu filter that album is excluded rather than mislabelled
    assert set(items) == {"itunes:1"}
    m = items["itunes:1"]
    assert (m["movie_title"], m["language"], m["release_year"], m["access"], m["country"]) == ("Mallanna", "te", 2009, "preview", None)
    assert m["credited_artist"] == "Devi Sri Prasad"

    movies = client.get("/api/v1/music/movies", params={"q": "movie soundtracks"}).json()["items"]
    assert {mv["title"] for mv in movies} >= {"Mallanna", "Devara Part 1"}
    assert next(mv for mv in movies if mv["title"] == "Devara Part 1")["language"] is None  # Unknown, not guessed


def test_itunes_language_comes_only_from_language_named_genres():
    from app.music.providers.itunes import ITunesProvider, track_language

    assert track_language("Telugu") == "te" and track_language("Tamil") == "ta" and track_language("Bollywood") == "hi"
    # broad genres and regional umbrellas say nothing reliable about language
    assert track_language("Soundtrack") is None and track_language("K-Pop") is None and track_language("Regional Indian") is None
    assert track_language(None) is None
    t = ITunesProvider()._to_track(
        {
            "trackId": 9,
            "trackName": "Song",
            "artistName": "A",
            "trackTimeMillis": 1000,
            "primaryGenreName": "Telugu",
            "previewUrl": "https://audio.test/p.m4a",
        }
    )
    assert t.language == "te" and t.language_source == "provider" and t.license.code == "preview"


def test_hosting_platform_database_urls_use_the_psycopg_driver():
    from app.core.config import Settings

    assert Settings(database_url="postgres://u:p@h:5432/d").database_url == "postgresql+psycopg://u:p@h:5432/d"
    assert Settings(database_url="postgresql://u:p@h/d").database_url == "postgresql+psycopg://u:p@h/d"
    assert Settings(database_url="postgresql+psycopg://u:p@h/d").database_url == "postgresql+psycopg://u:p@h/d"


def test_feed_redirects_to_internal_addresses_are_refused(monkeypatch):
    import socket

    import pytest

    from app.music.http import ProviderError

    def resolve(host, port, *a, **kw):  # feeds.test is public; internal.test points at loopback
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1" if host == "internal.test" else "93.184.216.34", port))]

    monkeypatch.setattr(socket, "getaddrinfo", resolve)
    hit_internal = []

    def handler(request):
        if request.url.host == "internal.test":
            hit_internal.append(str(request.url))
            return httpx.Response(200, content=FEED)
        return httpx.Response(302, headers={"location": "http://internal.test/secret"})

    music_http.set_transport(httpx.MockTransport(handler))
    with pytest.raises(ProviderError):
        podcast_providers.fetch_feed("https://feeds.test/redirects-inside")
    assert hit_internal == []  # the request to the internal host was never sent


def test_oversized_feeds_are_refused(monkeypatch, settings):
    import pytest

    from app.music.http import ProviderError

    monkeypatch.setattr(podcast_providers, "public_http_url", lambda url: True)
    monkeypatch.setattr(settings, "rss_max_bytes", 1000)
    music_http.set_transport(httpx.MockTransport(lambda r: httpx.Response(200, content=FEED, headers={"content-length": "999999"})))
    with pytest.raises(ProviderError):
        podcast_providers.fetch_feed("https://feeds.test/huge.xml")


def test_genre_fetch_reaches_empty_genres_and_lists_every_genre(client, settings, monkeypatch, factory):
    monkeypatch.setattr(settings, "music_previews_visible", True)  # iTunes only has previews; this test is about genre paging
    import json

    monkeypatch.setattr(settings, "music_providers", ["itunes"])
    h = factory.headers(factory.user())
    rows = {
        "resultCount": 2,
        "results": [
            {
                "trackId": 1,
                "trackName": "Blue Note",
                "artistName": "Quartet",
                "trackTimeMillis": 200000,
                "primaryGenreName": "Jazz",
                "previewUrl": "https://audio.test/1.m4a",
                "releaseDate": "1959-08-17T07:00:00Z",
                "collectionName": "Kind",
                "collectionId": 5,
            },
            {
                "trackId": 2,
                "trackName": "Jazz Hands",
                "artistName": "Pop Act",
                "trackTimeMillis": 200000,
                "primaryGenreName": "Pop",
                "previewUrl": "https://audio.test/2.m4a",
            },  # only matches the word "jazz": not filed under Jazz, so it is not imported
        ],
    }
    music_http.set_transport(
        routes(
            {
                "itunes.apple.com/search": lambda r: httpx.Response(
                    200, content=json.dumps(rows), headers={"content-type": "application/json"}
                )
            }
        )
    )

    empty = {g["name"]: g for g in client.get("/api/v1/music/genres", params={"include_empty": True}).json()}
    assert len(empty) > 40 and empty["Jazz"]["id"] is None and empty["Jazz"]["playable_count"] == 0

    assert client.post("/api/v1/music/genres/fetch", json={"genre": "Jazz"}).status_code == 401
    assert client.post("/api/v1/music/genres/fetch", json={"genre": "Nonsense"}, headers=h).status_code == 404
    res = client.post("/api/v1/music/genres/fetch", json={"genre": "jazz"}, headers=h)
    assert res.status_code == 200, res.text
    assert (res.json()["genre"], res.json()["slug"], res.json()["imported"]) == ("Jazz", "jazz", 1)
    after = {g["name"]: g for g in client.get("/api/v1/music/genres").json()}
    assert after["Jazz"]["playable_count"] == 1 and "Pop" not in after


def test_previews_are_hidden_by_default_and_never_replaced_by_another_stream(client, settings, monkeypatch, factory):
    from app.music.providers.itunes import ITunesProvider

    monkeypatch.setattr(settings, "music_providers", ["itunes"])
    h = factory.headers(factory.user())
    t = ITunesProvider()._to_track(
        {
            "trackId": 7,
            "trackName": "Clip",
            "artistName": "A",
            "trackTimeMillis": 30000,
            "primaryGenreName": "Pop",
            "previewUrl": "https://audio.test/preview.m4a",
        }
    )
    from app.db.session import SessionLocal
    from app.music.ingest import ingest

    with SessionLocal() as db:
        [song] = ingest(db, [t]).songs
        song_id = str(song.id)
    music_http.set_transport(
        routes(
            {
                "itunes.apple.com/lookup": {
                    "results": [
                        {
                            "trackId": 7,
                            "trackName": "Clip",
                            "artistName": "A",
                            "trackTimeMillis": 30000,
                            "primaryGenreName": "Pop",
                            "previewUrl": "https://audio.test/preview.m4a",
                        }
                    ]
                }
            }
        )
    )
    # default: a 30-second clip is not offered at all - not playable, not listed, not searchable, not in charts
    res = client.get(f"/api/v1/songs/{song_id}/stream-url", headers=h)
    assert res.status_code == 451
    shown = client.get(f"/api/v1/songs/{song_id}", headers=h).json()
    assert shown["playable"] is False and shown["access"] == "metadata" and "30-second" in shown["restriction_reason"]
    assert client.get("/api/v1/music/tracks").json()["total"] == 0
    assert (
        client.get("/api/v1/search/global", params={"q": "Clip", "categories": "songs", "live": "false"}, headers=h).json()["songs"] == []
    )

    # switched on: it plays the provider's own preview URL, labelled Preview, and nothing else
    monkeypatch.setattr(settings, "music_previews_visible", True)
    res = client.get(f"/api/v1/songs/{song_id}/stream-url", headers=h)
    assert res.status_code == 200 and res.json()["url"] == "https://audio.test/preview.m4a"
    assert client.get(f"/api/v1/songs/{song_id}", headers=h).json()["access"] == "preview"


def test_browse_tracks_albums_and_countries_use_the_artists_country_when_the_release_has_none(client, factory, fake):
    from app.db.session import SessionLocal
    from app.models import Artist

    h = factory.headers(factory.user())
    fake.catalog["a"] = track("a", "Alpha One", language="te", artist="Indian Singer")
    fake.catalog["b"] = track("b", "Alpha Two", language="ko", artist="Korean Singer", album="Seoul Album")
    client.get("/api/v1/search/global", params={"q": "Alpha", "categories": "songs"}, headers=h)
    with SessionLocal() as db:
        for name, code in (("Indian Singer", "IN"), ("Korean Singer", "KR")):
            db.query(Artist).filter(Artist.name == name).one().country = code
        db.commit()

    countries = {c["code"]: c for c in client.get("/api/v1/music/countries").json()}
    assert countries["IN"]["playable_count"] == 1 and countries["KR"]["name"] == "South Korea" and countries[None]["track_count"] == 0

    res = client.get("/api/v1/music/tracks", params={"country": "kr"}).json()
    assert [s["title"] for s in res["items"]] == ["Alpha Two"] and res["total"] == 1
    both = client.get("/api/v1/music/tracks").json()
    assert both["total"] == 2
    assert [s["title"] for s in client.get("/api/v1/music/tracks", params={"language": "te"}).json()["items"]] == ["Alpha One"]

    albums = client.get("/api/v1/music/albums").json()
    assert {a["title"] for a in albums} == {"Fake Album", "Seoul Album"}
    assert [a["title"] for a in client.get("/api/v1/music/albums", params={"language": "ko"}).json()] == ["Seoul Album"]
    assert (
        client.get("/api/v1/music/albums", params={"limit": 1, "page": 2}).json()
        != client.get("/api/v1/music/albums", params={"limit": 1}).json()
    )


def test_musicbrainz_needs_real_contact_details_in_the_user_agent(monkeypatch, settings):
    from app.music.providers.musicbrainz import MusicBrainzProvider

    monkeypatch.setattr(settings, "music_user_agent", "Wavely/1.0 (+https://github.com/your-org/wavely)")
    assert MusicBrainzProvider().is_configured() is False
    monkeypatch.setattr(settings, "music_user_agent", "Wavely/1.0 (+https://example.org/contact)")
    assert MusicBrainzProvider().is_configured() is True


def test_wikimedia_commons_keeps_only_music_with_verified_licenses_and_labels_language_from_audio_categories():
    from app.music.providers.wikimedia import WikimediaCommonsProvider

    def page(pid, title, mime, duration, license_url, short, categories, artist="<a href='x'>Some Singer</a>"):
        return {
            "pageid": pid,
            "title": f"File:{title}",
            "imageinfo": [
                {
                    "url": f"https://upload.test/{pid}",
                    "descriptionurl": f"https://commons.test/{pid}",
                    "mime": mime,
                    "duration": duration,
                    "extmetadata": {
                        "LicenseUrl": {"value": license_url},
                        "LicenseShortName": {"value": short},
                        "Categories": {"value": categories},
                        "Artist": {"value": artist},
                    },
                }
            ],
        }

    p = WikimediaCommonsProvider()
    cc = "https://creativecommons.org/licenses/by-sa/4.0"
    ok = p._to_track(page(1, "Bhajan.ogg", "application/ogg", 200.0, cc, "CC BY-SA 4.0", "Folk music|Audio files in Hindi"))
    assert ok.title == "Bhajan" and ok.artist_name == "Some Singer" and ok.license.code == "cc-by-sa" and ok.language == "hi"
    assert ok.duration_ms == 200_000 and ok.stream_url == "https://upload.test/1"

    # "closed captioning in Hindi" is a subtitle track, not the sung language
    assert (
        p._to_track(
            page(2, "Anthem.ogg", "audio/ogg", 90.0, cc, "CC BY-SA 4.0", "Anthems|Audio files with closed captioning in Hindi")
        ).language
        is None
    )
    # not music / too short / not browser audio / unverifiable license
    assert p._to_track(page(3, "En-us-hello.ogg", "audio/ogg", 120.0, cc, "CC BY-SA 4.0", "Pronunciation")) is None
    assert p._to_track(page(4, "Clip.ogg", "audio/ogg", 12.0, cc, "CC BY-SA 4.0", "Folk music")) is None
    assert p._to_track(page(5, "Tune.mid", "audio/midi", 120.0, cc, "CC BY-SA 4.0", "Folk music")) is None
    assert p._to_track(page(6, "Article.ogg", "audio/ogg", 600.0, cc, "CC BY-SA 4.0", "Spoken Wikipedia")) is None
    unknown = p._to_track(page(7, "Mystery.ogg", "audio/ogg", 120.0, "", "Custom license", "Folk music"))
    assert unknown.license.code == "unknown"  # imported as metadata, never playable
    pd = p._to_track(page(8, "Old record.ogg", "audio/ogg", 120.0, "", "Public domain", "Folk music"))
    assert pd.license.code == "pdm"
