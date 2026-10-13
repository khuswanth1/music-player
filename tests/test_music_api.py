"""End-to-end API behaviour of the open-catalog features, driven by an in-memory provider."""

import json
import uuid
from datetime import timedelta

import pytest

from app.billing.signature import sign_payload
from app.core.permissions import RoleName
from app.core.security import utcnow
from app.db.session import SessionLocal
from app.models import ListeningHistory, Song
from app.music.providers import register_provider, unregister_provider
from tests.music_fakes import CC_BY_NC, FakeProvider, routes, track


@pytest.fixture
def fake(settings, monkeypatch):
    FakeProvider.catalog = {}
    FakeProvider.calls = []
    register_provider(FakeProvider)
    monkeypatch.setattr(settings, "music_providers", ["fake"])
    yield FakeProvider
    unregister_provider("fake")


@pytest.fixture
def listener(factory):
    user = factory.user()
    return user, factory.headers(user)


def add(*tracks):
    for t in tracks:
        FakeProvider.catalog[t.provider_track_id] = t


def song_by_pid(pid: str) -> Song:
    with SessionLocal() as db:
        return db.query(Song).filter(Song.source == "fake", Song.provider_track_id == pid).one()


def search(client, headers, q, **params):
    res = client.get("/api/v1/search/global", params={"q": q, **params}, headers=headers)
    assert res.status_code == 200, res.text
    return res.json()


# --- languages ----------------------------------------------------------------------------------

def test_languages_are_listed_with_native_names_and_counts(client, fake, listener):
    _, h = listener
    langs = {lang["code"]: lang for lang in client.get("/api/v1/languages").json()}
    assert len(langs) > 190
    assert langs["te"]["native_name"] == "తెలుగు" and langs["te"]["featured"] and langs["te"]["track_count"] == 0
    assert langs["ar"]["rtl"] is True and langs["kok"]["name"] == "Konkani"

    add(track("t1", "Pallelona Song"), track("t2", "Godari Song", license_url=None))  # second one can't be verified
    search(client, h, "song")
    te = client.get("/api/v1/languages/tel").json()  # 639-3 codes resolve too
    assert te["code"] == "te" and te["track_count"] == 2 and te["playable_count"] == 1 and te["sources"] == {"fake": 1}
    assert [g["name"] for g in te["top_genres"]] == ["Folk"]
    with_tracks = client.get("/api/v1/languages", params={"with_tracks": True}).json()
    assert [lang["code"] for lang in with_tracks] == ["te"]
    assert client.get("/api/v1/languages/xx").status_code == 404


def test_language_page_tops_itself_up_from_providers_once(client, fake, listener):
    _, h = listener
    add(*(track(f"te{i}", f"Telugu song {i}") for i in range(5)), track("hi1", "Hindi song", language="hi"))
    page = client.get("/api/v1/languages/te/tracks").json()
    assert page["total"] == 5 and {s["language"] for s in page["items"]} == {"te"}
    assert all(s["source"] == "fake" and s["source_name"] == "Fake FM" and s["playable"] for s in page["items"])
    assert ("browse", "te", 0) in fake.calls
    fake.calls.clear()
    client.get("/api/v1/languages/te/tracks")
    assert fake.calls == []  # within the cooldown: no provider traffic
    res = client.post("/api/v1/languages/te/fetch", headers=h)  # explicit "load more" pages forward
    assert res.status_code == 200 and fake.calls == [("browse", "te", 20)]
    assert res.json()["providers"][0]["status"] == "ok"


def test_preferred_languages(client, listener):
    _, h = listener
    res = client.put("/api/v1/me/languages", json={"languages": ["te", "Hindi", "tel", "kok"]}, headers=h)
    assert res.json() == {"languages": ["te", "hi", "kok"]}
    assert client.get("/api/v1/me", headers=h).json()["preferred_languages"] == ["te", "hi", "kok"]
    bad = client.put("/api/v1/me/languages", json={"languages": ["klingon"]}, headers=h)
    assert bad.status_code == 422


def test_recommendations_and_home_favour_preferred_languages(client, fake, listener):
    _, h = listener
    add(track("ta1", "Tamil hit", language="ta", popularity=0.1), track("en1", "English hit", language="en", popularity=0.9))
    search(client, h, "hit")
    client.put("/api/v1/me/languages", json={"languages": ["ta"]}, headers=h)
    recs = client.get("/api/v1/me/recommendations", headers=h).json()
    assert recs[0]["title"] == "Tamil hit"
    home = client.get("/api/v1/browse/home", headers=h).json()
    assert [s["title"] for s in home["in_your_languages"]] == ["Tamil hit"]
    assert {lang["code"] for lang in home["languages"]} == {"ta", "en"}


# --- federated search ---------------------------------------------------------------------------

def test_global_search_imports_with_rights_and_reports_each_provider(client, fake, settings, monkeypatch, listener):
    _, h = listener
    monkeypatch.setattr(settings, "music_providers", ["fake", "jamendo"])
    monkeypatch.setattr(settings, "jamendo_client_id", None)
    add(track("a", "Monsoon Raga"), track("b", "Monsoon Rain", license_url=None),
        track("c", "Monsoon Gated", restrictions=["The artist requires a purchase"]),
        track("d", "Monsoon No Length", duration_ms=None))
    body = search(client, h, "monsoon")
    songs = {s["title"]: s for s in body["songs"]}
    assert set(songs) == {"Monsoon Raga", "Monsoon Rain", "Monsoon Gated"}  # unknown duration is skipped, not invented
    assert body["songs"][0]["title"] == "Monsoon Raga"  # playable first
    raga = songs["Monsoon Raga"]
    assert raga["playable"] and raga["license_code"] == "cc-by" and raga["download_allowed"]
    assert raga["attribution"] == '"Monsoon Raga" by Fake Artist, licensed under CC BY 4.0, via Fake FM.'
    assert raga["source_url"] == "https://fake.test/track/a" and raga["language"] == "te"
    assert songs["Monsoon Rain"]["availability"] == "restricted" and songs["Monsoon Rain"]["restriction_reason"]
    assert songs["Monsoon Gated"]["restriction_reason"] == "The artist requires a purchase"
    statuses = {p["key"]: p for p in body["providers"]}
    assert statuses["fake"]["status"] == "ok" and statuses["fake"]["count"] == 3
    assert statuses["jamendo"]["status"] == "not_configured"

    again = search(client, h, "monsoon")  # idempotent: same rows, refreshed
    assert {s["id"] for s in again["songs"]} == {s["id"] for s in body["songs"]}
    local = client.get("/api/v1/search", params={"q": "monsoon", "type": "song"}, headers=h).json()
    assert local["songs"]["total"] == 3  # imported tracks are part of the regular catalog


def test_global_search_language_filter_keeps_only_confident_matches(client, fake, listener):
    _, h = listener
    add(track("x1", "Prema", language="te"), track("x2", "Prema", language=None))
    body = search(client, h, "prema", language="te")
    assert [s["language"] for s in body["songs"]] == ["te"]


def test_script_detection_labels_unlabelled_tracks(client, fake, listener):
    _, h = listener
    add(track("k1", "ಹೊಸ ಹಾಡು", language=None))
    [song] = search(client, h, "ಹಾಡು")["songs"]
    assert (song["language"], song["language_source"]) == ("kn", "script")


def test_failing_provider_does_not_fail_the_search(client, fake, listener, monkeypatch):
    _, h = listener

    def boom(*args, **kwargs):
        raise RuntimeError("provider bug")

    monkeypatch.setattr(FakeProvider, "search", boom)
    body = search(client, h, "anything")
    assert body["songs"] == [] and body["providers"][0]["status"] == "error"


def test_metadata_only_results(client, fake, settings, monkeypatch, listener, no_provider_network):
    from app.music import http as music_http
    from app.music.providers import reset_providers

    _, h = listener
    monkeypatch.setattr(settings, "music_providers", ["fake", "musicbrainz"])
    music_http.set_transport(routes({"musicbrainz.org/ws/2/recording": {"recordings": [
        {"id": str(uuid.uuid4()), "score": 100, "title": "Naatu Naatu", "length": 215000,
         "artist-credit": [{"name": "Rahul Sipligunj"}], "releases": [{"title": "RRR"}]},
        {"id": str(uuid.uuid4()), "score": 100, "title": "Open Song", "artist-credit": [{"name": "Fake Artist"}]}]}}))
    reset_providers()
    add(track("o1", "Open Song"))
    body = search(client, h, "song")
    assert [m["title"] for m in body["metadata_only"]] == ["Naatu Naatu"]  # the playable one isn't repeated
    assert body["metadata_only"][0]["url"].startswith("https://musicbrainz.org/recording/")


# --- playback, downloads, verification ----------------------------------------------------------

def test_stream_url_returns_the_providers_authorized_stream(client, fake, listener):
    _, h = listener
    add(track("p1", "Playable"))
    [song] = search(client, h, "playable")["songs"]
    res = client.get(f"/api/v1/songs/{song['id']}/stream-url", headers=h)
    assert res.status_code == 200
    assert res.json()["url"] == "https://cdn.fake.test/p1.mp3" and res.json()["external"] is True
    assert res.json()["attribution"].startswith('"Playable"')
    # Our own token-gated stream endpoint never serves provider tracks.
    assert client.get(f"/api/v1/stream/{song['id']}", params={"token": "x"}).status_code in (401, 403, 404)


def test_restricted_tracks_are_refused_with_451(client, fake, listener):
    _, h = listener
    add(track("r1", "Unverified", license_url=None))
    [song] = search(client, h, "unverified")["songs"]
    res = client.get(f"/api/v1/songs/{song['id']}/stream-url", headers=h)
    assert res.status_code == 451 and res.json()["error"]["code"] == "playback_restricted"
    assert client.get(f"/api/v1/songs/{song['id']}/download", headers=h).status_code == 403


def test_noncommercial_tracks_excluded_on_commercial_deployments(client, fake, settings, monkeypatch, listener):
    _, h = listener
    add(track("nc1", "NC Track", license_url=CC_BY_NC))
    monkeypatch.setattr(settings, "commercial_deployment", True)
    [song] = search(client, h, "nc track")["songs"]
    assert song["playable"] is False and "non-commercial" in song["restriction_reason"]


def test_stale_rights_are_reverified_before_playback(client, fake, listener):
    _, h = listener
    add(track("v1", "Vanishing"))
    [song] = search(client, h, "vanishing")["songs"]
    with SessionLocal() as db:
        db.query(Song).filter(Song.id == song["id"]).update({"rights_checked_at": utcnow() - timedelta(days=30)})
        db.commit()
    del FakeProvider.catalog["v1"]  # the provider no longer has it
    res = client.get(f"/api/v1/songs/{song['id']}/stream-url", headers=h)
    assert res.status_code == 404 and res.json()["error"]["code"] == "audio_missing"
    assert ("fetch", "v1") in fake.calls
    assert song_by_pid("v1").availability.value == "unavailable"


def test_downloads_only_when_license_and_provider_allow(client, fake, listener):
    _, h = listener
    add(track("d1", "Downloadable Song"), track("d2", "Stream Only Song", download=False))
    songs = {s["title"]: s for s in search(client, h, "song")["songs"]}
    ok = client.get(f"/api/v1/songs/{songs['Downloadable Song']['id']}/download", headers=h)
    assert ok.status_code == 200 and ok.json()["url"] == "https://cdn.fake.test/d1.mp3?download=1"
    assert ok.json()["license_name"] == "CC BY 4.0"
    refused = client.get(f"/api/v1/songs/{songs['Stream Only Song']['id']}/download", headers=h)
    assert refused.status_code == 403 and refused.json()["error"]["code"] == "download_not_permitted"


def test_disabled_source_stops_playback(client, fake, settings, monkeypatch, listener):
    _, h = listener
    add(track("s1", "Switched Off"))
    [song] = search(client, h, "switched")["songs"]
    monkeypatch.setattr(settings, "music_providers", [])
    res = client.get(f"/api/v1/songs/{song['id']}/stream-url", headers=h)
    assert res.status_code == 451 and res.json()["error"]["code"] == "source_disabled"
    listed = client.get(f"/api/v1/songs/{song['id']}", headers=h).json()
    assert listed["playable"] is False and "disabled" in listed["restriction_reason"]
    assert client.get("/api/v1/charts").json()[0]["track_count"] == 0  # charts only offer playable tracks


def test_open_catalog_tracks_cannot_be_made_premium(client, fake, factory, listener):
    _, h = listener
    editor = factory.headers(factory.user(RoleName.content_manager))
    add(track("m1", "Free Forever"))
    [song] = search(client, h, "free forever")["songs"]
    res = client.patch(f"/api/v1/songs/{song['id']}", json={"is_premium": True}, headers=editor)
    assert res.status_code == 422 and res.json()["error"]["code"] == "premium_not_allowed"
    res = client.patch(f"/api/v1/songs/{song['id']}", json={"language": "kn"}, headers=editor)
    assert res.json()["language"] == "kn" and res.json()["language_source"] == "manual"
    add(track("m1", "Free Forever", language="te"))
    search(client, h, "free forever")  # a provider refresh never overrides a manual correction
    assert song_by_pid("m1").language == "kn"


# --- rights notifications -------------------------------------------------------------------------

def _webhook(client, settings, event: dict, secret: str | None = None):
    body = json.dumps(event).encode()
    sig = sign_payload(body, secret or settings.catalog_webhook_secret)
    return client.post("/api/v1/catalog/webhooks", content=body,
                       headers={"x-wavely-signature": sig, "content-type": "application/json"})


def test_takedown_webhook_blocks_playback_and_future_imports(client, fake, settings, listener):
    _, h = listener
    add(track("w1", "Taken Down"))
    [song] = search(client, h, "taken down")["songs"]
    event = {"id": "evt_1", "type": "track.takedown",
             "data": {"provider": "fake", "provider_track_id": "w1", "reason": "Rights holder request"}}
    assert _webhook(client, settings, event, secret="wrong").status_code == 400
    res = _webhook(client, settings, event)
    assert res.status_code == 200 and res.json()["duplicate"] is False
    assert _webhook(client, settings, event).json()["duplicate"] is True  # redelivery is a no-op
    stream = client.get(f"/api/v1/songs/{song['id']}/stream-url", headers=h)
    assert stream.status_code == 451 and stream.json()["error"]["message"] == "Rights holder request"
    [again] = search(client, h, "taken down")["songs"]  # a provider re-sync doesn't resurrect it
    assert again["playable"] is False

    # A takedown can arrive before the track was ever imported.
    _webhook(client, settings, {"id": "evt_2", "type": "track.takedown", "data": {"provider": "fake", "provider_track_id": "w2"}})
    add(track("w2", "Not Yet Imported"))
    [blocked] = search(client, h, "not yet imported")["songs"]
    assert blocked["playable"] is False

    _webhook(client, settings, {"id": "evt_3", "type": "track.restore", "data": {"provider": "fake", "provider_track_id": "w1"}})
    assert client.get(f"/api/v1/songs/{song['id']}/stream-url", headers=h).status_code == 200


def test_admin_rights_controls(client, fake, factory, listener):
    _, h = listener
    editor = factory.headers(factory.user(RoleName.content_manager))
    add(track("a1", "Admin Managed"))
    [song] = search(client, h, "admin managed")["songs"]
    assert client.post(f"/api/v1/admin/songs/{song['id']}/takedown", json={}, headers=h).status_code == 403
    down = client.post(f"/api/v1/admin/songs/{song['id']}/takedown", json={"reason": "Disputed ownership"}, headers=editor)
    assert down.json()["playable"] is False and down.json()["restriction_reason"] == "Disputed ownership"
    up = client.delete(f"/api/v1/admin/songs/{song['id']}/takedown", headers=editor)
    assert up.json()["playable"] is True
    verified = client.post(f"/api/v1/admin/songs/{song['id']}/verify", headers=editor)
    assert verified.status_code == 200 and ("fetch", "a1") in fake.calls

    providers = {p["key"]: p for p in client.get("/api/v1/admin/providers", headers=editor).json()}
    assert providers["fake"]["track_count"] == 1 and providers["musicbrainz"]["enabled"] is False
    sync = client.post("/api/v1/admin/catalog/sync", json={"language": "te"}, headers=editor)
    assert sync.status_code == 200 and sync.json()["providers"][0]["key"] == "fake"
    assert client.get("/api/v1/admin/providers", headers=h).status_code == 403


def test_public_provider_list(client, fake):
    providers = {p["key"]: p for p in client.get("/api/v1/providers").json()}
    assert {"jamendo", "internet_archive", "audius", "openverse", "ccmixter", "musicbrainz", "fake"} <= set(providers)
    assert providers["musicbrainz"]["policy"]["stream"] is False
    assert providers["audius"]["policy"]["download_links"] is False
    assert providers["jamendo"]["requires_credentials"] is True
    assert providers["fake"]["enabled"] is True and providers["jamendo"]["enabled"] is False


# --- charts -------------------------------------------------------------------------------------

def test_charts_rank_local_listens_then_provider_popularity(client, fake, listener):
    user, h = listener
    add(track("c1", "Popular Upstream", popularity=0.9), track("c2", "Loved Here", popularity=0.1),
        track("c3", "Hindi Track", language="hi", popularity=0.5), track("c4", "Blocked", license_url=None, popularity=1.0))
    for q in ("popular", "loved", "hindi", "blocked"):
        search(client, h, q)
    loved = song_by_pid("c2")
    with SessionLocal() as db:
        for _ in range(5):
            db.add(ListeningHistory(user_id=user.id, song_id=loved.id, ms_played=60_000, completed=True))
        db.commit()

    charts = {c["id"]: c for c in client.get("/api/v1/charts").json()}
    assert charts["global"]["track_count"] == 3  # the unverified track never charts
    assert "language:te" in charts and "language:hi" in charts and "region:south-asia" in charts

    te = client.get("/api/v1/charts/language:te", headers=h).json()
    assert [e["song"]["title"] for e in te["entries"]] == ["Loved Here", "Popular Upstream"]
    assert te["entries"][0]["listens_7d"] == 5 and te["entries"][0]["rank"] == 1 and te["basis"]
    region = client.get("/api/v1/charts/region:south-asia").json()
    assert len(region["entries"]) == 3
    assert client.get("/api/v1/charts/region:atlantis").status_code == 404


def test_recheck_applies_new_rules_without_provider_traffic(client, fake, factory, settings, monkeypatch, listener):
    _, h = listener
    editor = factory.headers(factory.user(RoleName.content_manager))
    add(track("rc1", "Noncommercial Gem", license_url=CC_BY_NC), track("rc2", "Open Gem"))
    search(client, h, "gem")
    fake.calls.clear()
    monkeypatch.setattr(settings, "commercial_deployment", True)
    res = client.post("/api/v1/admin/catalog/recheck", headers=editor)
    assert res.json() == {"checked": 2, "newly_unplayable": 1}
    assert fake.calls == []
    assert song_by_pid("rc1").playable is False and song_by_pid("rc2").playable is True
    assert client.post("/api/v1/admin/catalog/recheck", headers=h).status_code == 403


def test_info_logging_during_import_is_safe(client, fake, listener, caplog):
    """Log `extra` keys must not collide with LogRecord attributes (only visible at INFO level)."""
    import logging

    _, h = listener
    caplog.set_level(logging.INFO)
    add(track("lg1", "Logged Song"))
    assert search(client, h, "logged")["songs"]
    assert any(r.message == "music.ingested" for r in caplog.records)


def test_open_upload_of_a_released_recording_is_blocked_before_first_play(client, fake, settings, monkeypatch, listener):
    from app.music import http as music_http
    from app.music.providers import reset_providers

    _, h = listener
    monkeypatch.setattr(FakeProvider, "open_uploads", True)
    monkeypatch.setattr(settings, "music_providers", ["fake", "musicbrainz"])
    released = {"id": str(uuid.uuid4()), "score": 100, "title": "Srivalli", "length": 220_000,
                "artist-credit": [{"name": "Sid Sriram"}], "releases": [{"title": "Pushpa", "status": "Official"}]}
    music_http.set_transport(routes({"musicbrainz.org/ws/2/recording": {"recordings": [released]}}))
    reset_providers()
    add(track("u1", "Srivalli", duration_ms=221_000, artist="Random Uploader"),
        track("u2", "Srivalli Sunrise", duration_ms=200_000, artist="Indie Person"))
    songs = {s["title"]: s for s in search(client, h, "srivalli")["songs"]}
    assert songs["Srivalli"]["playable"]  # screening alone can't tell

    blocked = client.get(f"/api/v1/songs/{songs['Srivalli']['id']}/stream-url", headers=h)
    assert blocked.status_code == 451 and "Sid Sriram" in blocked.json()["error"]["message"]
    assert client.get(f"/api/v1/songs/{songs['Srivalli Sunrise']['id']}/stream-url", headers=h).status_code == 200
    again = {s["title"]: s for s in search(client, h, "srivalli")["songs"]}
    assert again["Srivalli"]["playable"] is False  # the block survives provider re-syncs
