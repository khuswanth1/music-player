"""Fan requests out to providers in parallel, inside a time budget, and fold the results into the catalog.

A slow or failing provider never fails the request: each one reports its own status (ok, rate limited,
quota exceeded, not configured, unsupported, timeout, error), which the API passes to the client.
"""

import logging
import re
import time
import unicodedata
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import AppError, NotFound
from app.core.security import utcnow
from app.db.session import SessionLocal
from app.models import Artist, Availability, CatalogSyncState, Song
from app.music import languages as langs
from app.music.http import ProviderError
from app.music.ingest import _LANGUAGE_STRENGTH, apply_rights, block_track, ingest
from app.music.licensing import Rights
from app.music.providers import (
    Capability,
    MetadataRecording,
    enabled_providers,
    get_provider,
    is_enabled,
    known_providers,
)
from app.music.providers.musicbrainz import MusicBrainzProvider
from app.realtime.hub import hub

log = logging.getLogger(__name__)

# Shared, bounded pool: provider calls are I/O bound and abandoned calls must not pile up threads.
_POOL = ThreadPoolExecutor(max_workers=16, thread_name_prefix="music-provider")


class PlaybackRestricted(AppError):
    status_code = 451  # Unavailable For Legal Reasons
    code = "playback_restricted"


@dataclass
class ProviderStatus:
    key: str
    name: str
    status: str  # ok | not_configured | unsupported | rate_limited | quota_exceeded | timeout | error
    count: int = 0
    message: str | None = None


@dataclass
class FanOut:
    tracks: list = field(default_factory=list)
    statuses: list[ProviderStatus] = field(default_factory=list)


def _status_from_error(exc: ProviderError) -> str:
    return {"not_configured": "not_configured", "unsupported": "unsupported", "rate_limited": "rate_limited",
            "quota_exceeded": "quota_exceeded"}.get(exc.kind, "error")


def run_parallel(calls: dict[str, Callable[[], Any]], budget: float) -> dict[str, Any]:
    """Run each call on the shared pool; a call still running when the budget ends yields TimeoutError."""
    futures = {key: _POOL.submit(fn) for key, fn in calls.items()}
    deadline = time.monotonic() + budget
    results: dict[str, Any] = {}
    for key, future in futures.items():
        remaining = max(0.05, deadline - time.monotonic())
        try:
            results[key] = future.result(timeout=remaining)
        except FutureTimeout:
            results[key] = TimeoutError()
        except Exception as exc:  # recorded as that provider's status, never raised
            results[key] = exc
    return results


def _fan_out(calls: dict[str, Callable[[], list]], budget: float) -> FanOut:
    out = FanOut()
    for key, result in run_parallel(calls, budget).items():
        provider = get_provider(key)
        if isinstance(result, ProviderError):
            out.statuses.append(ProviderStatus(key, provider.name, _status_from_error(result), message=result.message))
        elif isinstance(result, TimeoutError):
            out.statuses.append(ProviderStatus(key, provider.name, "timeout", message="Didn't answer in time"))
        elif isinstance(result, Exception):
            log.exception("music.provider_crashed", exc_info=result, extra={"provider": key})
            out.statuses.append(ProviderStatus(key, provider.name, "error", message="Unexpected error"))
        else:
            out.statuses.append(ProviderStatus(key, provider.name, "ok", count=len(result)))
            out.tracks.extend(result)
    return out


def _inactive_statuses(capability: Capability, active: list[str]) -> list[ProviderStatus]:
    settings = get_settings()
    out = []
    for p in known_providers():
        if p.key in active or capability not in p.capabilities or Capability.playback not in p.capabilities:
            continue
        if p.key not in settings.music_providers:
            out.append(ProviderStatus(p.key, p.name, "disabled", message="Disabled in MUSIC_PROVIDERS"))
        elif not p.is_configured():
            out.append(ProviderStatus(p.key, p.name, "not_configured", message="Needs credentials (see docs)"))
    return out


def _interleave(songs_by_provider: dict[str, list[Song]]) -> list[Song]:
    """Round-robin across providers so one large source doesn't bury the others; playable first."""
    out, queues = [], [list(v) for v in songs_by_provider.values()]
    while any(queues):
        for q in queues:
            if q:
                out.append(q.pop(0))
    return sorted(out, key=lambda s: not s.playable)  # stable: keeps the interleaved order


# --- search ------------------------------------------------------------------------------------

@dataclass
class GlobalSearch:
    songs: list[Song]
    statuses: list[ProviderStatus]
    metadata_only: list[MetadataRecording]


def _norm(text: str) -> str:
    return re.sub(r"\W+", "", unicodedata.normalize("NFKC", text).casefold())


def global_search(db: Session, q: str, *, language: str | None, limit: int = 20) -> GlobalSearch:
    settings = get_settings()
    providers = [p for p in enabled_providers(Capability.search) if Capability.playback in p.capabilities]
    calls: dict[str, Callable] = {p.key: (lambda p=p: p.search(q, language=language, limit=limit)) for p in providers}
    mb = next((p for p in enabled_providers(Capability.metadata) if isinstance(p, MusicBrainzProvider)), None)
    if mb and not language:
        calls[mb.key] = lambda: mb.search_recordings(q, limit=10)
    fan = _fan_out(calls, settings.music_search_budget_seconds)

    recordings = [t for t in fan.tracks if isinstance(t, MetadataRecording)]
    provider_tracks = [t for t in fan.tracks if not isinstance(t, MetadataRecording)]
    result = ingest(db, provider_tracks)
    by_provider: dict[str, list[Song]] = {}
    for song in result.songs:
        if language and song.language != language:
            continue  # the provider filtered loosely; only keep what we can label confidently
        by_provider.setdefault(song.source, []).append(song)
    songs = _interleave(by_provider)[: limit * 3]

    have = {(_norm(s.title), _norm(s.artist.name)) for s in songs if s.playable}
    metadata_only = [r for r in recordings if (_norm(r.title), _norm(r.artist_name)) not in have]
    for st in fan.statuses:  # report what was kept (after ingest and language filtering), not raw hits
        if st.status == "ok":
            st.count = len(metadata_only) if mb and st.key == mb.key else len(by_provider.get(st.key, []))
    statuses = fan.statuses + _inactive_statuses(Capability.search, [s.key for s in fan.statuses])
    return GlobalSearch(songs=songs, statuses=statuses, metadata_only=metadata_only)


# --- language fetch / background sync -----------------------------------------------------------

@dataclass
class FetchResult:
    imported: int
    updated: int
    statuses: list[ProviderStatus]


def _sync_state(db: Session, provider: str, language: str) -> CatalogSyncState:
    db.execute(insert(CatalogSyncState).values(provider=provider, language=language).on_conflict_do_nothing())
    return db.get(CatalogSyncState, (provider, language))


def fetch_language(db: Session, language: str, *, providers: list[str] | None = None, page_size: int = 20,
                   budget: float | None = None) -> FetchResult:
    """Pull the next page of popular tracks in `language` from every language-capable provider."""
    if language not in langs.BY_CODE:
        raise NotFound("Unknown language")
    candidates = [p for p in enabled_providers(Capability.language)
                  if Capability.playback in p.capabilities and (providers is None or p.key in providers)]
    states = {p.key: _sync_state(db, p.key, language) for p in candidates}
    stale_exhausted = utcnow() - timedelta(days=7)
    for state in states.values():  # providers keep adding music: start over a week after running dry
        if state.exhausted and (state.last_synced_at is None or state.last_synced_at < stale_exhausted):
            state.exhausted, state.next_offset = False, 0
    db.commit()
    active = [p for p in candidates if not states[p.key].exhausted]
    calls = {p.key: (lambda p=p, o=states[p.key].next_offset: p.browse(language=language, limit=page_size, offset=o))
             for p in active}
    fan = _fan_out(calls, budget or get_settings().music_search_budget_seconds)
    result = ingest(db, fan.tracks)

    now = utcnow()
    for st in fan.statuses:
        state = db.get(CatalogSyncState, (st.key, language))
        state.last_synced_at = now
        if st.status == "ok":
            state.next_offset += page_size
            state.exhausted = st.count == 0
            state.imported += st.count
            state.last_error = None
        else:
            state.last_error = (st.message or st.status)[:500]
    db.commit()
    statuses = fan.statuses + [ProviderStatus(p.key, p.name, "ok", 0, "Everything available has been fetched")
                               for p in candidates if states[p.key].exhausted and p.key not in calls]
    return FetchResult(result.created, result.updated, statuses + _inactive_statuses(Capability.language, list(states)))


def sync_tick() -> None:
    """Worker job: fetch one page for the configured language that was synced longest ago."""
    settings = get_settings()
    languages = [code for code in settings.catalog_sync_languages if code in langs.BY_CODE]
    if not languages:
        return
    with SessionLocal() as db:
        last = dict(db.execute(select(CatalogSyncState.language, func.max(CatalogSyncState.last_synced_at))
                               .where(CatalogSyncState.language.in_(languages))
                               .group_by(CatalogSyncState.language)).all())
        language = min(languages, key=lambda code: (last.get(code) is not None, last.get(code) or utcnow()))
        result = fetch_language(db, language, budget=30)
        log.info("music.sync", extra={"language": language, "imported": result.imported,
                                      "statuses": {s.key: s.status for s in result.statuses}})


def check_conflict(db: Session, song: Song) -> bool:
    """For open-upload sources: block the track if MusicBrainz shows it is someone else's released recording.

    Returns True if the track was blocked. The block is persistent (a rights block), so provider re-syncs
    don't bring it back; an editor can lift it."""
    mb = get_provider("musicbrainz")
    provider = get_provider(song.source)
    if not (mb and is_enabled(mb) and provider and provider.open_uploads) or song.takedown_at is not None:
        return False
    conflict = mb.find_conflict(song.title, song.artist.name, song.duration_ms)
    if conflict is None:
        return False
    reason = f"Matches a released recording by {conflict.artist_name}; this upload isn't from the rights holder"
    block_track(db, song.source, song.provider_track_id, reason, f"auto:musicbrainz:{conflict.id}")
    db.refresh(song)
    return True


def enrich_tick(batch: int = 5) -> int:
    """Worker job: fill language / ISRC / release country from MusicBrainz for recently imported tracks,
    and check open-upload tracks against released recordings."""
    mb = get_provider("musicbrainz")
    if not (mb and is_enabled(mb) and get_settings().musicbrainz_enrichment_enabled):
        return 0
    done = 0
    with SessionLocal() as db:
        songs = db.scalars(select(Song).where(Song.source != "local", Song.enriched_at.is_(None))
                           .order_by(Song.created_at).limit(batch)).unique().all()
        for song in songs:
            try:
                if check_conflict(db, song):
                    song.enriched_at = utcnow()
                    db.commit()
                    done += 1
                    continue
                found = mb.enrich(song.title, song.artist.name, song.duration_ms)
            except ProviderError as exc:
                if exc.kind in ("rate_limited", "quota_exceeded", "unavailable"):
                    break  # try again on a later tick
                found = None
            song.enriched_at = utcnow()
            if found:
                song.musicbrainz_recording_id = found.recording_id
                song.isrc = song.isrc or found.isrc
                song.country = song.country or found.country
                current = _LANGUAGE_STRENGTH.get(song.language_source or "", -1) if song.language else -1
                if found.language and _LANGUAGE_STRENGTH["musicbrainz"] >= current:
                    song.language, song.language_source = found.language, "musicbrainz"
                artist = db.get(Artist, song.artist_id)
                if artist and artist.musicbrainz_id is None and found.artist_id:
                    artist.musicbrainz_id = found.artist_id
            db.commit()
            done += 1
    return done


# --- rights verification at playback time --------------------------------------------------------

def verify(db: Session, song: Song) -> Song:
    """Re-check one track with its provider now. A track the provider no longer has becomes unavailable."""
    provider = get_provider(song.source)
    if provider is None:
        raise NotFound("Unknown source")
    current = provider.fetch_track(song.provider_track_id)
    if current is None:
        if apply_rights(song, Rights(Availability.unavailable, False, False, f"No longer available from {provider.name}")):
            hub.publish("catalog", {"type": "track.unavailable", "song_id": str(song.id)})
        db.commit()
        return song
    ingest(db, [current])
    db.refresh(song)
    return song


def playback_url(db: Session, song: Song) -> str:
    """The authorized URL for a provider track, after (re)verifying its rights if the last check is stale."""
    provider = get_provider(song.source)
    if provider is None or not is_enabled(provider):
        raise PlaybackRestricted("This source is currently disabled on this server", code="source_disabled")
    max_age = timedelta(hours=get_settings().rights_revalidate_hours)
    if song.takedown_at is None and (song.rights_checked_at is None or song.rights_checked_at < utcnow() - max_age):
        try:
            verify(db, song)
        except ProviderError as exc:  # provider unreachable: keep the last verified decision
            log.warning("music.verify_failed", extra={"song_id": str(song.id), "error": exc.message})
    if song.playable and provider.open_uploads and song.enriched_at is None:
        try:  # before an open upload's first play, make sure it isn't someone else's released recording
            check_conflict(db, song)
        except ProviderError as exc:  # MusicBrainz busy: screening already passed; the worker re-checks
            log.info("music.conflict_check_deferred", extra={"song_id": str(song.id), "error": exc.message})
    if not song.playable:
        if song.availability == Availability.unavailable:
            raise NotFound(song.restriction_reason or "No authorized audio for this track", code="audio_missing")
        raise PlaybackRestricted(song.restriction_reason or "This track can't be played here")
    return provider.playback_url(song.provider_track_id, song.remote_stream_url)

