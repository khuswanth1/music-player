"""Turn provider tracks into catalog rows (artists, albums, songs) with their rights evaluated.

Upserts are keyed by (source, provider id), so repeated searches and syncs refresh rows instead of
duplicating them, and two requests importing the same track at once are safe (savepoint + retry).
"""

import hashlib
import logging
import re
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass, field

from sqlalchemy import select, tuple_
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import utcnow
from app.models import Album, AlbumType, Artist, Availability, Genre, RightsBlock, Song
from app.music import languages as langs
from app.music.genres import canonical_genre, color_for
from app.music.licensing import License, Rights, attribution_line, evaluate
from app.music.providers import get_provider
from app.music.providers.base import ProviderTrack
from app.music.screening import screen
from app.realtime.hub import hub
from app.services.catalog import slugify

log = logging.getLogger(__name__)

# Language provenance, strongest first. A weaker source never overwrites a stronger one.
_LANGUAGE_STRENGTH = {"manual": 4, "musicbrainz": 3, "provider": 2, "tag": 1, "script": 0}


@dataclass
class IngestResult:
    songs: list[Song] = field(default_factory=list)
    created: int = 0
    updated: int = 0
    skipped: int = 0


def _short_hash(*parts: str, n: int = 10) -> str:
    return hashlib.sha1("\x1f".join(parts).encode()).hexdigest()[:n]


def import_slug(name: str, *key: str) -> str:
    """Readable and unique without a lookup loop: ascii (or native-script) words plus a stable hash."""
    base = slugify(name)
    if base == "item":  # no ASCII equivalent (e.g. Telugu or Hangul): keep the native letters
        base = re.sub(r"[^\w]+", "-", unicodedata.normalize("NFKC", name).casefold()).strip("-_") or "artist"
    return f"{base[:110]}-{_short_hash(*key)}"


def _name_key(name: str) -> str:
    return "name:" + _short_hash(unicodedata.normalize("NFKC", name).casefold().strip(), n=24)


def _upsert_artist(db: Session, t: ProviderTrack, cache: dict) -> Artist:
    pid = (t.provider_artist_id or _name_key(t.artist_name))[:128]
    key = (t.provider, pid)
    if key in cache:
        return cache[key]
    artist = db.scalar(select(Artist).where(Artist.source == t.provider, Artist.provider_artist_id == pid))
    if artist is None:
        try:
            with db.begin_nested():
                artist = Artist(name=t.artist_name[:120], slug=import_slug(t.artist_name, t.provider, pid),
                                source=t.provider, provider_artist_id=pid, source_url=t.artist_url, bio="")
                db.add(artist)
        except IntegrityError:  # imported concurrently by another request
            artist = db.scalar(select(Artist).where(Artist.source == t.provider, Artist.provider_artist_id == pid))
    elif t.artist_url and artist.source_url != t.artist_url:
        artist.source_url = t.artist_url
    cache[key] = artist
    return artist


def _upsert_album(db: Session, t: ProviderTrack, artist: Artist, cache: dict) -> Album | None:
    if not t.album_title:
        return None
    pid = (t.provider_album_id or _name_key(f"{artist.id}:{t.album_title}"))[:128]
    key = (t.provider, pid)
    if key in cache:
        return cache[key]
    album = db.scalar(select(Album).where(Album.source == t.provider, Album.provider_album_id == pid))
    if album is None:
        try:
            with db.begin_nested():
                album = Album(title=t.album_title[:200], artist_id=artist.id, album_type=AlbumType.album,
                              release_date=t.release_date, cover_url=t.artwork_url, source=t.provider,
                              provider_album_id=pid, source_url=t.album_url)
                db.add(album)
        except IntegrityError:
            album = db.scalar(select(Album).where(Album.source == t.provider, Album.provider_album_id == pid))
    else:
        album.cover_url = album.cover_url or t.artwork_url
        album.release_date = album.release_date or t.release_date
    cache[key] = album
    return album


def _genre(db: Session, tags: list[str], cache: dict) -> Genre | None:
    name = canonical_genre(tags)
    if name is None:
        return None
    if name not in cache:
        db.execute(insert(Genre).values(name=name, slug=slugify(name), color=color_for(name)).on_conflict_do_nothing())
        cache[name] = db.scalar(select(Genre).where(Genre.name == name))
    return cache[name]


def _language(t: ProviderTrack) -> tuple[str | None, str | None]:
    code = langs.normalize(t.language)
    if code:
        return code, t.language_source
    detected = langs.detect_from_script(t.title, t.album_title, t.artist_name)
    return (detected, "script") if detected else (None, None)


def rights_for(t: ProviderTrack) -> Rights:
    settings = get_settings()
    provider = get_provider(t.provider)
    restrictions = list(t.restrictions)
    if (doubt := screen(t, open_uploads=provider.open_uploads)) is not None:  # the stated license isn't credible
        restrictions.append(doubt)
    return evaluate(lic=t.license, policy=provider.policy, has_stream=bool(t.stream_url),
                    has_download=bool(t.download_url), provider_download_allowed=t.provider_download_allowed,
                    restrictions=restrictions, commercial_deployment=settings.commercial_deployment,
                    downloads_enabled=settings.music_downloads_enabled)


def apply_rights(song: Song, rights: Rights) -> bool:
    """Set rights columns; returns True if the song stopped being playable. Takedowns always win."""
    was_playable = song.playable
    if song.takedown_at is not None:
        rights = Rights(Availability.restricted, False, False, song.restriction_reason or "Removed following a rights notice")
    song.availability = rights.availability
    song.stream_allowed = rights.stream_allowed
    song.download_allowed = rights.download_allowed
    song.restriction_reason = rights.reason
    song.rights_checked_at = utcnow()
    return was_playable and not song.playable


def _apply(song: Song, t: ProviderTrack, artist: Artist, album: Album | None, genre: Genre | None) -> bool:
    provider = get_provider(t.provider)
    song.title = t.title[:200]
    song.artist_id, song.album_id = artist.id, album.id if album else None
    song.duration_ms = t.duration_ms
    song.explicit = t.explicit
    song.is_premium = False  # open-catalog tracks are never put behind a paywall (many are NonCommercial)
    song.source_url, song.artwork_url = t.source_url, t.artwork_url
    song.remote_stream_url, song.remote_download_url = t.stream_url, t.download_url
    song.license_code, song.license_name, song.license_url = t.license.code, t.license.name, t.license.url
    song.attribution = t.attribution or attribution_line(t.title, t.artist_name, t.license, provider.name)
    song.provider_popularity = t.popularity if t.popularity is not None else song.provider_popularity
    song.isrc = song.isrc or (t.isrc[:12] if t.isrc else None)
    if genre is not None and song.genre_id is None:
        song.genre_id = genre.id
    code, source = _language(t)
    current = _LANGUAGE_STRENGTH.get(song.language_source or "", -1) if song.language else -1
    if code and _LANGUAGE_STRENGTH.get(source or "", -1) >= current:
        song.language, song.language_source = code, source
    return apply_rights(song, rights_for(t))


def block_track(db: Session, source: str, provider_track_id: str, reason: str, requested_by: str) -> Song | None:
    """Record a rights block (kept even for tracks not imported yet) and make any stored copy unplayable."""
    values = {"reason": reason[:255], "requested_by": requested_by[:120]}
    db.execute(insert(RightsBlock).values(source=source, provider_track_id=provider_track_id, **values)
               .on_conflict_do_update(index_elements=[RightsBlock.source, RightsBlock.provider_track_id], set_=values))
    song = db.scalar(select(Song).where(Song.source == source, Song.provider_track_id == provider_track_id))
    if song is not None:
        song.takedown_at = song.takedown_at or utcnow()
        song.restriction_reason = reason[:255]
        apply_rights(song, Rights(Availability.restricted, False, False, reason[:255]))
    db.commit()
    if song is not None:
        hub.publish("catalog", {"type": "track.unavailable", "song_id": str(song.id)})
    log.info("music.blocked", extra={"source": source, "provider_track_id": provider_track_id, "by": requested_by})
    return song


def track_from_song(song: Song) -> ProviderTrack:
    """Rebuild what we know of a provider track from its stored row (for re-checking rights offline)."""
    return ProviderTrack(
        provider=song.source, provider_track_id=song.provider_track_id, title=song.title, artist_name=song.artist.name,
        album_title=song.album.title if song.album else None, release_date=song.album.release_date if song.album else None,
        duration_ms=song.duration_ms, stream_url=song.remote_stream_url, download_url=song.remote_download_url,
        provider_download_allowed=song.remote_download_url is not None, source_url=song.source_url,
        license=License(song.license_code or "unknown", song.license_name or "", song.license_url),
        tags=[song.genre.name] if song.genre else [])


def recheck_rights(db: Session, batch: int = 500) -> tuple[int, int]:
    """Re-run rights evaluation and screening on stored provider tracks after rules or settings change.

    Never contacts providers and never re-enables a track the provider itself restricted (that needs a
    re-verification). Returns (checked, newly unplayable)."""
    checked = lost = 0
    last_id = None
    while True:
        stmt = select(Song).where(Song.source != "local").order_by(Song.id).limit(batch)
        if last_id is not None:
            stmt = stmt.where(Song.id > last_id)
        songs = db.scalars(stmt).unique().all()
        if not songs:
            break
        for song in songs:
            checked += 1
            if song.provider_track_id is None or get_provider(song.source) is None:
                continue
            rights = rights_for(track_from_song(song))
            if song.availability != Availability.playable and rights.availability == Availability.playable:
                continue  # only a fresh check with the provider may lift a restriction it reported
            if apply_rights(song, rights):
                lost += 1
                hub.publish("catalog", {"type": "track.unavailable", "song_id": str(song.id)})
        db.commit()
        last_id = songs[-1].id
    return checked, lost


def ingest(db: Session, tracks: Iterable[ProviderTrack]) -> IngestResult:
    """Upsert provider tracks and commit. Tracks without a known duration are skipped (never invented)."""
    result = IngestResult()
    tracks = list(tracks)
    artists: dict = {}
    albums: dict = {}
    genres: dict = {}
    seen: set[tuple[str, str]] = set()
    lost_playback: list[str] = []
    keys = {(t.provider, t.provider_track_id) for t in tracks}
    blocks = {(b.source, b.provider_track_id): b for b in db.scalars(
        select(RightsBlock).where(tuple_(RightsBlock.source, RightsBlock.provider_track_id).in_(keys)))} if keys else {}
    for t in tracks:
        key = (t.provider, t.provider_track_id)
        if key in seen or get_provider(t.provider) is None:
            continue
        seen.add(key)
        if not t.duration_ms or t.duration_ms <= 0 or not t.title.strip():
            result.skipped += 1
            continue
        artist = _upsert_artist(db, t, artists)
        album = _upsert_album(db, t, artist, albums)
        genre = _genre(db, t.tags, genres)
        block = blocks.get(key)
        song = db.scalar(select(Song).where(Song.source == t.provider, Song.provider_track_id == t.provider_track_id))
        if song is not None and block is not None and song.takedown_at is None:
            song.takedown_at, song.restriction_reason = block.created_at, block.reason
        if song is None:
            try:
                with db.begin_nested():
                    song = Song(source=t.provider, provider_track_id=t.provider_track_id, play_count=0, is_published=True)
                    if block is not None:
                        song.takedown_at, song.restriction_reason = block.created_at, block.reason
                    _apply(song, t, artist, album, genre)
                    db.add(song)
                result.created += 1
            except IntegrityError:
                song = db.scalar(select(Song).where(Song.source == t.provider, Song.provider_track_id == t.provider_track_id))
                if song is None:
                    result.skipped += 1
                    continue
                if _apply(song, t, artist, album, genre):
                    lost_playback.append(str(song.id))
                result.updated += 1
        else:
            if _apply(song, t, artist, album, genre):
                lost_playback.append(str(song.id))
            result.updated += 1
        result.songs.append(song)
    db.commit()
    for song_id in lost_playback:
        hub.publish("catalog", {"type": "track.unavailable", "song_id": song_id})
    if result.created:
        log.info("music.ingested", extra={"tracks_created": result.created, "tracks_updated": result.updated,
                                          "tracks_skipped": result.skipped})
    return result
