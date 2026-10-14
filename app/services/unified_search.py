"""One search across songs, artists, albums, soundtracks, podcasts, episodes, playlists, private albums and facets.

Live providers are queried first (in parallel, inside a time budget); their results join the catalog, which is
then searched with the filters applied in SQL so pagination, deduplication and ordering are consistent.
"""

import re
import threading
import time
import unicodedata
from collections.abc import Callable

from sqlalchemy import Select, delete, func, or_, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.session import SessionLocal
from app.models import Album, Artist, Genre, Language, SearchHistory, Song, User
from app.music import federation, queryparse, soundtracks
from app.music.countries import COUNTRIES
from app.music.federation import run_parallel
from app.repositories.catalog import complete_recordings, playable_condition, song_country
from app.schemas.catalog import GenreOut
from app.schemas.music import MetadataRecordingOut, ProviderStatusOut
from app.schemas.search import CountryHit, LanguageHit, Suggestion, SuggestionsOut, UnifiedSearchOut
from app.schemas.worldmusic import SoundtrackOut
from app.services import catalog as catalog_svc

_SEARCH_CACHE: dict[str, tuple[UnifiedSearchOut, float]] = {}
_SEARCH_CACHE_LOCK = threading.Lock()
_SEARCH_CACHE_TTL = 180.0  # 3 minutes
_SEARCH_CACHE_MAX = 500

from app.services import discovery as disc
from app.services import podcasts as podcast_svc
from app.services import private_albums as private_svc
from app.services import worldmusic as world
from app.services.discovery import _match
from app.services.playlists import summarize_many

ALL = ("songs", "artists", "albums", "soundtracks", "podcasts", "episodes", "playlists", "private_albums", "facets")


def _norm(text: str) -> str:
    return re.sub(r"\W+", "", unicodedata.normalize("NFKC", text).casefold())


def _status(key, name, status, count=0, message=None) -> ProviderStatusOut:
    return ProviderStatusOut(key=key, name=name, status=status, count=count, message=message)


def song_query(rest: str, *, language, country, genre, year_from, year_to, source, full_only, era) -> Select:
    stmt = (
        select(Song)
        .join(Artist, Artist.id == Song.artist_id)
        .outerjoin(Album, Album.id == Song.album_id)
        .where(Song.is_published.is_(True))
    )
    if rest:
        stmt = stmt.where(or_(_match(Song.title, rest), _match(Artist.name, rest), _match(Album.title, rest)))
    if language:
        stmt = stmt.where(Song.language == language)
    if country:
        stmt = stmt.where(song_country() == country.upper())
    if source:
        stmt = stmt.where(Song.source == source)
    if genre:
        stmt = stmt.join(Genre, Genre.id == Song.genre_id).where(Genre.slug == genre)
    stmt = stmt.where(complete_recordings())  # previews never appear unless MUSIC_PREVIEWS_VISIBLE is on
    if full_only:
        stmt = stmt.where(playable_condition(), or_(Song.license_code.is_(None), Song.license_code != "preview"))
    if year_from:
        stmt = stmt.where(func.extract("year", Album.release_date) >= year_from)
    if year_to:
        stmt = stmt.where(func.extract("year", Album.release_date) <= year_to)
    playable_first = playable_condition().desc()
    if era == "latest":
        return stmt.order_by(playable_first, Album.release_date.desc().nulls_last(), Song.id)
    if rest:
        rank = func.greatest(func.similarity(Song.title, rest), func.similarity(Artist.name, rest) * 0.8)
        return stmt.order_by(playable_first, rank.desc(), Song.play_count.desc(), Song.id)
    return stmt.order_by(playable_first, Song.play_count.desc(), Song.provider_popularity.desc().nulls_last(), Song.id)


def _dedupe_songs(songs: list[Song]) -> list[Song]:
    """Same recording from several providers (same ISRC / MusicBrainz id / title+artist): keep the best audio, not all."""
    best: dict = {}
    order: list = []
    rank = {"full": 0, "preview": 1, "metadata": 2}

    def access(s: Song) -> str:
        return "metadata" if not s.playable else ("preview" if s.license_code == "preview" else "full")

    for s in songs:
        keys = [("isrc", s.isrc)] if s.isrc else []
        keys.append(("mb", s.musicbrainz_recording_id)) if s.musicbrainz_recording_id else None
        keys.append(("ta", _norm(s.title), _norm(s.artist.name)))
        hit = next((best[k] for k in keys if k in best), None)
        if hit is None:
            for k in keys:
                best[k] = s
            order.append(s)
        elif rank[access(s)] < rank[access(hit)]:
            order[order.index(hit)] = s
            for k in keys:
                best[k] = s
    return order


def _live_songs(q: str, language: str | None, limit: int):
    with SessionLocal() as db:
        if q:
            found = federation.global_search(db, q, language=language, limit=limit)
            return found.statuses, found.metadata_only
        if language:
            return federation.fetch_language(db, language).statuses, []
        return [], []


def search(
    db: Session,
    user: User | None,
    q: str,
    *,
    categories: set[str],
    language: str | None,
    country: str | None,
    year: int | None,
    genre: str | None,
    source: str | None,
    full_only: bool,
    page: int,
    limit: int,
    live: bool = True,
) -> UnifiedSearchOut:
    user_id = str(user.id) if user and ("private_albums" in categories or "playlists" in categories) else ""
    cache_key = f"{q.strip().casefold()}::{','.join(sorted(categories))}::{language}::{country}::{year}::{genre}::{source}::{full_only}::{page}::{limit}::{live}::{user_id}"
    now_m = time.monotonic()
    with _SEARCH_CACHE_LOCK:
        if cache_key in _SEARCH_CACHE:
            cached_out, exp = _SEARCH_CACHE[cache_key]
            if exp > now_m:
                return cached_out

    h = queryparse.parse(q)
    language = language or h.language
    country = (country or h.country or "").upper() or None
    year_from, year_to = (year, year) if year else (h.year_from, h.year_to)
    rest = h.rest
    out = UnifiedSearchOut(
        query=q,
        language=language,
        page=page,
        interpreted={
            k: v
            for k, v in {
                "language": language,
                "country": country,
                "year_from": year_from,
                "year_to": year_to,
                "era": h.era,
                "movie": h.movie or None,
                "podcast": h.podcast or None,
                "text": rest or None,
            }.items()
            if v
        },
    )

    # Intent words shift emphasis: "podcasts" without a music hint skips the music providers entirely.
    want = lambda c: c in categories  # noqa: E731
    music_live = live and (want("songs") or want("artists") or want("albums")) and not (h.podcast and not (rest or language))
    calls: dict[str, Callable] = {}
    if music_live and page == 1 and (rest or language):
        calls["songs"] = lambda: _live_songs(rest, language, limit)
    if live and want("soundtracks") and page == 1 and (h.movie or categories == {"soundtracks"} or rest):
        calls["soundtracks"] = lambda: soundtracks.search(
            rest, language=language, country=country, year_from=year_from, year_to=year_to, limit=12
        )
    podcast_term = rest or ("" if language else "podcast")
    # Podcasts only for a podcast intent, a text query, or when that tab is chosen: "telugu old songs" is a music search.
    if live and want("podcasts") and page == 1 and (h.podcast or rest or categories == {"podcasts"}):
        calls["podcasts"] = lambda: podcast_svc.search(
            podcast_term, country=country, language=language, category=None, provider=None, limit=12
        )
    if live and want("episodes") and page == 1 and rest:
        calls["episodes"] = lambda: podcast_svc.search_episodes(rest, country=country, limit=10)
    # Give search calls a fast, bounded budget
    search_budget = min(get_settings().music_search_budget_seconds, 2.5)
    results = run_parallel(calls, search_budget)


    for key, value in results.items():
        if isinstance(value, Exception):
            out.providers.append(
                _status(key, key.title(), "timeout" if isinstance(value, TimeoutError) else "error", message=str(value)[:200])
            )
    if isinstance(results.get("songs"), tuple):
        statuses, recordings = results["songs"]
        out.providers += [ProviderStatusOut(key=s.key, name=s.name, status=s.status, count=s.count, message=s.message) for s in statuses]
        out.metadata_only = [MetadataRecordingOut(**vars(r)) for r in recordings][:10]
    if isinstance(results.get("soundtracks"), tuple):
        rows, statuses = results["soundtracks"]
        out.soundtracks = [SoundtrackOut(**r) for r in rows]
        out.providers += statuses
    if isinstance(results.get("podcasts"), tuple):
        found, statuses = results["podcasts"]
        out.podcasts = podcast_svc.podcast_outs(db, user, found[:12])
        out.providers += statuses
        if h.era == "latest":
            out.podcasts.sort(key=lambda p: p.latest_episode_at.timestamp() if p.latest_episode_at else 0, reverse=True)
    if isinstance(results.get("episodes"), tuple):
        found, statuses = results["episodes"]
        out.episodes = podcast_svc.episode_outs(db, user, found)

    if want("songs"):
        stmt = song_query(
            rest,
            language=language,
            country=country,
            genre=genre,
            year_from=year_from,
            year_to=year_to,
            source=source,
            full_only=full_only,
            era=h.era,
        )
        rows = list(db.scalars(stmt.offset((page - 1) * limit).limit(limit + 1)).unique())
        out.has_more = len(rows) > limit
        out.songs = catalog_svc.song_outs(db, user, _dedupe_songs(rows[:limit]))
    if want("artists") and (rest or language):
        if rest:
            out.artists = world.search_artists(
                db, user, rest, language=language, country=country, source=source, limit=limit, offset=(page - 1) * limit
            )
        else:
            top = (
                select(Song.artist_id, func.count().label("n"))
                .where(Song.language == language, playable_condition())
                .group_by(Song.artist_id)
                .order_by(func.count().desc())
                .limit(limit)
                .offset((page - 1) * limit)
                .subquery()
            )
            artists = list(db.scalars(select(Artist).join(top, top.c.artist_id == Artist.id).order_by(top.c.n.desc())).unique())
            out.artists = world.artist_cards(db, user, artists)
    if want("albums") and (rest or language or year_from):
        out.albums = world.search_albums(
            db,
            rest or None,
            language=language,
            source=source,
            year_from=year_from,
            year_to=year_to,
            limit=min(limit, 20),
            offset=(page - 1) * limit,
            playable_only=True,
        )
    if want("playlists") and rest:
        playlists = db.scalars(disc.search_playlists(rest, sort="relevance").limit(min(limit, 12))).unique().all()
        out.playlists = summarize_many(db, list(playlists))
    if want("private_albums") and user and rest:
        out.private_albums = private_svc.list_mine(db, user, sort="updated", favorites_only=False, q=rest)[:12]
    with _SEARCH_CACHE_LOCK:
        if len(_SEARCH_CACHE) > _SEARCH_CACHE_MAX:
            _SEARCH_CACHE.clear()
        _SEARCH_CACHE[cache_key] = (out, now_m + _SEARCH_CACHE_TTL)
    return out



def _facets(db: Session, text: str, h: queryparse.Hints):
    needle = unicodedata.normalize("NFKC", text).casefold().strip()
    languages, countries = [], []
    if needle:
        counts = dict(
            db.execute(
                select(Song.language, func.count()).where(playable_condition(), Song.language.is_not(None)).group_by(Song.language)
            ).all()
        )
        for lang in db.scalars(select(Language).order_by(Language.featured_rank.nulls_last(), Language.name)):
            if lang.code == h.language or (
                len(needle) >= 2 and (lang.name.casefold().startswith(needle) or lang.native_name.casefold().startswith(needle))
            ):
                languages.append(
                    LanguageHit(code=lang.code, name=lang.name, native_name=lang.native_name, playable_count=counts.get(lang.code, 0))
                )
        countries = [
            CountryHit(code=c, name=n)
            for c, n in COUNTRIES.items()
            if c not in ("XW", "XE") and (c == h.country or (len(needle) >= 3 and n.casefold().startswith(needle)))
        ]
    genres = db.scalars(select(Genre).where(_match(Genre.name, needle)).order_by(Genre.name).limit(8)).all() if needle else []
    years = []
    if h.year_from:
        years = list(range(h.year_from, (h.year_to or h.year_from) + 1))
    return languages[:6], countries[:6], [GenreOut.model_validate(g) for g in genres], years


# --- suggestions & history ----------------------------------------------------------------------


def suggestions(db: Session, user: User | None, q: str, limit: int = 10) -> SuggestionsOut:
    q = q.strip()
    items: list[Suggestion] = []
    if user:
        recent = db.scalars(
            select(SearchHistory.query)
            .where(SearchHistory.user_id == user.id, SearchHistory.query.ilike(f"{q.replace('%', '')}%"))
            .group_by(SearchHistory.query)
            .order_by(func.max(SearchHistory.created_at).desc())
            .limit(3)
        )
        items += [Suggestion(text=r, type="recent", query=r) for r in recent]
    for song in db.scalars(
        select(Song)
        .join(Artist, Artist.id == Song.artist_id)
        .where(Song.is_published.is_(True), complete_recordings(), _match(Song.title, q))
        .order_by(playable_condition().desc(), func.similarity(Song.title, q).desc(), Song.play_count.desc())
        .limit(4)
    ).unique():
        items.append(
            Suggestion(
                text=song.title,
                type="song",
                subtitle=song.artist.name,
                image_url=song.artwork_url,
                query=f"{song.title} {song.artist.name}",
            )
        )
    for artist in db.scalars(
        select(Artist).where(_match(Artist.name, q)).order_by(func.similarity(Artist.name, q).desc()).limit(3)
    ).unique():
        items.append(
            Suggestion(text=artist.name, type="artist", subtitle="Artist", image_url=artist.image_url, href=f"/artist/{artist.id}")
        )
    for album in db.scalars(select(Album).where(_match(Album.title, q)).order_by(func.similarity(Album.title, q).desc()).limit(2)).unique():
        items.append(
            Suggestion(text=album.title, type="album", subtitle=album.artist.name, image_url=album.cover_url, href=f"/album/{album.id}")
        )
    low = q.casefold()
    for lang in db.scalars(select(Language).order_by(Language.featured_rank.nulls_last()).limit(200)):
        if len(low) >= 2 and (lang.name.casefold().startswith(low) or lang.native_name.casefold().startswith(low)):
            items.append(Suggestion(text=f"{lang.name} songs", type="language", subtitle=lang.native_name, href=f"/language/{lang.code}"))
    for genre in db.scalars(select(Genre).where(_match(Genre.name, q)).limit(2)):
        items.append(Suggestion(text=genre.name, type="genre", href=f"/genre/{genre.slug}"))
    for code, name in COUNTRIES.items():
        if len(low) >= 3 and name.casefold().startswith(low) and code not in ("XW", "XE"):
            items.append(Suggestion(text=name, type="country", subtitle="Country", query=name))
    seen, unique = set(), []
    for item in items:
        key = (item.type == "recent" and item.text.casefold()) or (item.type, item.text.casefold())
        if key not in seen:
            seen.add(key)
            unique.append(item)
    return SuggestionsOut(query=q, items=unique[:limit])


def record_search(db: Session, user: User, query: str) -> None:
    query = " ".join(query.split())[:100]
    if not query:
        return
    last = db.scalar(select(SearchHistory).where(SearchHistory.user_id == user.id).order_by(SearchHistory.created_at.desc()).limit(1))
    if last is not None and last.query.casefold() == query.casefold():
        last.created_at = func.now()  # searching the same thing again just bumps it
    else:
        db.add(SearchHistory(user_id=user.id, query=query))
    db.commit()
    # Keep the table bounded: at most 200 entries per user.
    old = select(SearchHistory.id).where(SearchHistory.user_id == user.id).order_by(SearchHistory.created_at.desc()).offset(200)
    db.execute(delete(SearchHistory).where(SearchHistory.id.in_(old)))
    db.commit()


def recent_searches(db: Session, user: User, limit: int = 10) -> list[tuple[str, object]]:
    rows = db.execute(
        select(SearchHistory.query, func.max(SearchHistory.created_at))
        .where(SearchHistory.user_id == user.id)
        .group_by(SearchHistory.query)
        .order_by(func.max(SearchHistory.created_at).desc())
        .limit(limit)
    ).all()
    return [(r[0], r[1]) for r in rows]


def clear_search(db: Session, user: User, query: str | None) -> None:
    stmt = delete(SearchHistory).where(SearchHistory.user_id == user.id)
    if query:
        stmt = stmt.where(func.lower(SearchHistory.query) == query.casefold())
    db.execute(stmt)
    db.commit()
