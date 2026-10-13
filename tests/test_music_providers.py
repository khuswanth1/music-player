"""Provider adapters against recorded-shape responses, and the shared HTTP layer (cache, quota, retries)."""

import httpx
import pytest
from sqlalchemy import select

from app.db.session import SessionLocal
from app.models import ProviderUsage
from app.music import http as music_http
from app.music.http import ProviderClient, ProviderError
from app.music.providers import get_provider, reset_providers
from tests.music_fakes import routes


@pytest.fixture
def mock_http(no_provider_network):
    """Install a routing table for this test; the network guard still catches anything unrouted."""
    def install(table):
        music_http.set_transport(routes(table))
        reset_providers()
    return install


# --- shared HTTP layer --------------------------------------------------------------------------

def test_responses_are_cached(mock_http):
    hits = []

    def answer(request):
        hits.append(request.url)
        return httpx.Response(200, json={"ok": True})

    mock_http({"api.test/x": answer})
    client = ProviderClient("testprov", rate_per_second=100, burst=10)
    assert client.get_json("https://api.test/x", {"q": "a"}) == {"ok": True}
    assert client.get_json("https://api.test/x", {"q": "a"}) == {"ok": True}
    assert len(hits) == 1
    client.get_json("https://api.test/x", {"q": "b"})  # different params, different cache entry
    assert len(hits) == 2


def test_daily_quota_is_enforced_before_sending(mock_http):
    hits = []
    mock_http({"api.test/": lambda r: (hits.append(1), httpx.Response(200, json={}))[1]})
    client = ProviderClient("quotaprov", rate_per_second=100, burst=10, daily_quota=2)
    client.get_json("https://api.test/1", cache=False)
    client.get_json("https://api.test/2", cache=False)
    with pytest.raises(ProviderError) as exc:
        client.get_json("https://api.test/3", cache=False)
    assert exc.value.kind == "quota_exceeded" and len(hits) == 2
    with SessionLocal() as db:
        assert db.scalar(select(ProviderUsage.requests).where(ProviderUsage.provider == "quotaprov")) == 2


def test_rate_limit_responses_and_retries(mock_http):
    attempts = []

    def flaky(request):
        attempts.append(1)
        return httpx.Response(500) if len(attempts) == 1 else httpx.Response(200, json={"n": len(attempts)})

    mock_http({"api.test/flaky": flaky, "api.test/limited": lambda r: httpx.Response(429, headers={"retry-after": "120"})})
    client = ProviderClient("retryprov", rate_per_second=100, burst=10)
    assert client.get_json("https://api.test/flaky") == {"n": 2}  # one retry after a 5xx
    with pytest.raises(ProviderError) as exc:
        client.get_json("https://api.test/limited")
    assert exc.value.kind == "rate_limited"
    with SessionLocal() as db:
        usage = db.scalar(select(ProviderUsage).where(ProviderUsage.provider == "retryprov"))
        assert usage.errors == 1 and "429" in usage.last_error


def test_unreachable_provider_reports_unavailable(mock_http):
    def boom(request):
        raise httpx.ConnectError("refused", request=request)

    mock_http({"api.test/": boom})
    with pytest.raises(ProviderError) as exc:
        ProviderClient("downprov", rate_per_second=100, burst=10).get_json("https://api.test/x")
    assert exc.value.kind == "unavailable"


# --- Jamendo ------------------------------------------------------------------------------------

JAMENDO_TRACK = {
    "id": "1532771", "name": "Kaadhal Kanave", "duration": 214, "artist_id": "7801", "artist_name": "Indie Collective",
    "album_name": "Monsoon", "album_id": "180001", "releasedate": "2024-07-01", "album_image": "https://img.jamendo.test/a.jpg",
    "audio": "https://prod-1.storage.jamendo.com/?trackid=1532771&format=mp31", "audiodownload": "https://dl.jamendo.test/1532771",
    "audiodownload_allowed": True, "license_ccurl": "http://creativecommons.org/licenses/by-nc-sa/3.0/",
    "shareurl": "https://www.jamendo.com/track/1532771",
    "musicinfo": {"vocalinstrumental": "vocal", "lang": "ta", "tags": {"genres": ["pop"], "vartags": ["romantic"]}},
}


def test_jamendo_needs_a_client_id(settings, monkeypatch, mock_http):
    monkeypatch.setattr(settings, "jamendo_client_id", None)
    mock_http({})
    jamendo = get_provider("jamendo")
    assert jamendo.is_configured() is False
    with pytest.raises(ProviderError) as exc:
        jamendo.search("x")
    assert exc.value.kind == "not_configured"


def test_jamendo_maps_tracks_and_language_filters(settings, monkeypatch, mock_http):
    monkeypatch.setattr(settings, "jamendo_client_id", "test-client")
    seen = []

    def answer(request):
        seen.append(dict(request.url.params))
        return httpx.Response(200, json={"headers": {"status": "success", "code": 0}, "results": [JAMENDO_TRACK]})

    mock_http({"api.jamendo.com/v3.0/tracks": answer})
    jamendo = get_provider("jamendo")
    [t] = jamendo.browse(language="ta", limit=10)
    assert seen[0]["lang"] == "ta" and seen[0]["client_id"] == "test-client" and seen[0]["order"] == "popularity_month"
    assert (t.title, t.artist_name, t.album_title, t.duration_ms, t.language) == ("Kaadhal Kanave", "Indie Collective", "Monsoon", 214_000, "ta")
    assert t.license.code == "cc-by-nc-sa" and t.provider_download_allowed and t.popularity == 1.0
    jamendo.browse(language="zxx", limit=10)
    assert seen[1]["vocalinstrumental"] == "instrumental" and "lang" not in seen[1]
    with pytest.raises(ProviderError) as exc:
        jamendo.browse(language="kok")  # Jamendo only filters ISO 639-1
    assert exc.value.kind == "unsupported"


def test_jamendo_invalid_key_is_reported_as_not_configured(settings, monkeypatch, mock_http):
    monkeypatch.setattr(settings, "jamendo_client_id", "bad")
    mock_http({"api.jamendo.com/": {"headers": {"status": "failed", "code": 5, "error_message": "Invalid Client Id"}, "results": []}})
    with pytest.raises(ProviderError) as exc:
        get_provider("jamendo").search("x")
    assert exc.value.kind == "not_configured"


# --- Internet Archive ---------------------------------------------------------------------------

def _ia_item(identifier, *, license_url="https://creativecommons.org/licenses/by-sa/4.0/", restricted=False, files=None):
    meta = {"identifier": identifier, "title": "Melukolupu Patalu", "creator": "Rallabandi Family", "date": "2015-11-20",
            "language": "tel", "subject": ["songs", "telugu songs"]}
    if license_url:
        meta["licenseurl"] = license_url
    if restricted:
        meta["access-restricted-item"] = "true"
    return {"metadata": meta, "files": files if files is not None else [
        {"name": "01 Suprabhatam.flac", "format": "Flac", "source": "original", "length": "201.5", "title": "Suprabhatam"},
        {"name": "01 Suprabhatam.mp3", "format": "VBR MP3", "source": "derivative", "original": "01 Suprabhatam.flac", "length": "201.5"},
        {"name": "01 Suprabhatam.ogg", "format": "Ogg Vorbis", "source": "derivative", "original": "01 Suprabhatam.flac", "length": "201.5"},
        {"name": "02.mp3", "format": "VBR MP3", "source": "original", "length": "03:05"},
        {"name": "secret.mp3", "format": "VBR MP3", "source": "original", "private": "true", "length": "10"},
        {"name": "cover.jpg", "format": "JPEG", "source": "original"},
    ]}


def test_internet_archive_verifies_each_item(mock_http):
    queries = []

    def search(request):
        queries.append(request.url.params["q"])
        return httpx.Response(200, json={"response": {"docs": [
            {"identifier": "good-item", "downloads": 999}, {"identifier": "no-license"}, {"identifier": "restricted"},
            {"identifier": "gone"}]}})

    mock_http({
        "archive.org/advancedsearch.php": search,
        "archive.org/metadata/good-item": _ia_item("good-item"),
        "archive.org/metadata/no-license": _ia_item("no-license", license_url=None),
        "archive.org/metadata/restricted": _ia_item("restricted", restricted=True),
        "archive.org/metadata/gone": {},
    })
    tracks = get_provider("internet_archive").browse(language="te", limit=20)
    q = queries[0]
    assert "language:(" in q and "tel" in q and '"Telugu"' in q and "licenseurl:*creativecommons.org*" in q
    assert "-collection:(librivoxaudio" in q and "subject:(" in q

    by_item = {}
    for t in tracks:
        by_item.setdefault(t.provider_album_id, []).append(t)
    good = by_item["good-item"]
    assert [t.title for t in good] == ["Suprabhatam", "Melukolupu Patalu (02)"]  # MP3 chosen once; private skipped
    assert good[0].stream_url == "https://archive.org/download/good-item/01%20Suprabhatam.mp3"
    assert good[0].duration_ms == 201_500 and good[1].duration_ms == 185_000
    assert good[0].license.code == "cc-by-sa" and good[0].language == "tel" and good[0].release_date.isoformat() == "2015-11-20"
    assert all(t.license.code == "unknown" for t in by_item["no-license"])  # imported as restricted, never playable
    assert all(t.restrictions for t in by_item["restricted"])
    assert "gone" not in by_item


# --- Audius -------------------------------------------------------------------------------------

def _audius(track_id, **extra):
    return {"id": track_id, "title": f"Track {track_id}", "duration": 200, "genre": "Electronic", "license": "All rights reserved",
            "permalink": f"/artist/{track_id}", "play_count": 12000, "is_streamable": True, "user": {"id": "u1", "name": "DJ Test", "handle": "djtest"},
            "artwork": {"480x480": "https://img.audius.test/480.jpg"}, **extra}


def test_audius_is_stream_only_and_honors_artist_restrictions(mock_http):
    mock_http({"api.audius.co/v1/tracks/search": {"data": [
        _audius("ok"), _audius("gated", is_stream_gated=True), _audius("apps", allowed_api_keys=["0xabc"]),
        _audius("unlisted", is_unlisted=True), _audius("cc", license="Attribution CC BY")]}})
    tracks = {t.provider_track_id: t for t in get_provider("audius").search("x")}
    assert "unlisted" not in tracks
    ok = tracks["ok"]
    assert ok.license.code == "platform" and ok.stream_url.startswith("https://api.audius.co/v1/tracks/ok/stream?app_name=")
    assert ok.download_url is None and not ok.restrictions
    assert tracks["gated"].restrictions and tracks["apps"].restrictions
    assert tracks["cc"].license.code == "cc-by"
    with pytest.raises(ProviderError) as exc:
        get_provider("audius").search("x", language="te")
    assert exc.value.kind == "unsupported"


# --- ccMixter / Openverse / MusicBrainz -----------------------------------------------------------

def test_ccmixter_language_only_from_exact_language_tags(mock_http):
    def upload(uid, tags, license_url="http://creativecommons.org/licenses/by/3.0/", files=True):
        return {"upload_id": uid, "upload_name": f"Song {uid}", "user_name": "mixer", "user_real_name": "Mixer",
                "license_url": license_url, "file_page_url": f"https://ccmixter.org/files/mixer/{uid}",
                "upload_extra": {"usertags": tags}, "upload_date_format": "Sat, Aug 19, 2006 @ 9:50 PM", "upload_num_scores": 5,
                "files": [{"download_url": f"https://ccmixter.org/content/{uid}.mp3",
                           "file_format_info": {"media-type": "audio", "mime_type": "audio/mpeg", "ps": "3:20"}}] if files else []}

    mock_http({"ccmixter.org/api/query": [
        upload(1, "hindi,sitar,remix"), upload(2, "it,pop"), upload(3, "ambient", "http://creativecommons.org/licenses/sampling+/1.0/"),
        upload(4, "samples", files=False)]})
    tracks = {t.provider_track_id: t for t in get_provider("ccmixter").search("x")}
    assert tracks["1"].language == "hi" and tracks["1"].language_source == "tag" and tracks["1"].duration_ms == 200_000
    assert tracks["2"].language is None  # "it" is a word, not proof of Italian
    assert tracks["3"].license.code == "unknown"
    assert "4" not in tracks


def test_openverse_keeps_music_and_drops_clips(mock_http):
    def item(i, **extra):
        return {"id": f"ov{i}", "title": f"Piece {i}", "url": f"https://upload.wikimedia.test/{i}.ogg", "creator": "Composer",
                "license": "by-sa", "license_version": "4.0", "license_url": "https://creativecommons.org/licenses/by-sa/4.0/",
                "source": "wikimedia_audio", "duration": 120_000, "foreign_landing_url": f"https://commons.test/{i}", **extra}

    mock_http({"api.openverse.org/v1/audio": {"results": [
        item(1), item(2, category="pronunciation"), item(3, duration=5000), item(4, source="jamendo")]}})
    tracks = get_provider("openverse").search("piano")
    assert [t.provider_track_id for t in tracks] == ["ov1"]
    assert tracks[0].license.name == "CC BY-SA 4.0" and tracks[0].provider_download_allowed


def test_musicbrainz_search_and_confident_enrichment(mock_http):
    rec = {"id": "758cfc94-e193-46be-86de-c21913463810", "score": 100, "title": "Naatu Naatu", "length": 215000,
           "artist-credit": [{"name": "Rahul Sipligunj", "joinphrase": " & ", "artist": {"id": "7c8ba630-14b6-4e81-b29b-7dddb2f6524c"}},
                             {"name": "Kaala Bhairava", "joinphrase": ""}],
           "releases": [{"id": "11111111-1111-1111-1111-111111111111", "title": "RRR", "country": "IN", "date": "2022-03-25"}],
           "isrcs": ["INS182200123"]}
    mock_http({"musicbrainz.org/ws/2/recording": {"recordings": [rec]},
               "musicbrainz.org/ws/2/release/": {"text-representation": {"language": "tel"}}})
    mb = get_provider("musicbrainz")
    [found] = mb.search_recordings("Naatu Naatu")
    assert (found.title, found.artist_name, found.release_title) == ("Naatu Naatu", "Rahul Sipligunj & Kaala Bhairava", "RRR")
    enriched = mb.enrich("Naatu Naatu", "Rahul Sipligunj", 214_000)
    assert (enriched.language, enriched.country, enriched.isrc) == ("te", "IN", "INS182200123")
    assert mb.enrich("Naatu Naatu", "Rahul Sipligunj", 400_000) is None  # duration mismatch: no guess


def test_musicbrainz_conflict_needs_same_title_length_and_another_artist(mock_http):
    def rec(title, artist, length, status="Official"):
        return {"id": "00000000-0000-0000-0000-000000000001", "score": 100, "title": title, "length": length,
                "artist-credit": [{"name": artist}], "releases": [{"title": "Album", "status": status}]}

    mock_http({"musicbrainz.org/ws/2/recording": {"recordings": [
        rec("Friends", "Famous Band", 180_000), rec("Srivalli", "Sid Sriram", 220_000)]}})
    mb = get_provider("musicbrainz")
    assert mb.find_conflict("Srivalli", "Random Uploader", 221_000).artist_name == "Sid Sriram"
    assert mb.find_conflict("Srivalli", "Sid Sriram Official", 221_000) is None  # the artist themself
    assert mb.find_conflict("Friends", "Indie Person", 320_000) is None  # same title, different length
    assert mb.find_conflict("Friends", "Indie Person", None) is None
