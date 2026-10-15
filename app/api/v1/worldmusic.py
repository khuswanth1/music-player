"""Worldwide discovery: latest / old tracks, countries, genres, movie soundtracks, artist and album search."""

import uuid
from typing import Annotated, Literal

from concurrent.futures import ThreadPoolExecutor

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from app.api.deps import DB, CurrentUser, OptionalUser, PageParams
from app.api.v1 import streaming
from app.api.v1.music import _provider_fanout_limit, _warm_language
from app.core.errors import NotFound
from app.models import Album, Artist, Genre, Song
from app.music import artist_photos, federation, queryparse, soundtracks
from app.music import languages as langs
from app.music.countries import country_name
from app.music.genres import CANONICAL
from app.music.http import ProviderError
from app.music.ingest import ingest
from app.repositories.catalog import paginate, playable_condition, song_country
from app.schemas.catalog import SongOut, StreamUrl
from app.schemas.music import ProviderStatusOut
from app.schemas.worldmusic import (
    AlbumCard,
    AlbumSearchOut,
    ArtistCard,
    ArtistProfile,
    ArtistSearchOut,
    CountryOut,
    GenreFetchIn,
    GenreFetchOut,
    GenreStat,
    MovieOut,
    MovieSearchOut,
    SoundtrackDetail,
    SoundtrackOut,
    SoundtrackSearchOut,
    SoundtrackTrack,
    TrackListOut,
)
from app.services import catalog as catalog_svc
from app.services import worldmusic as svc
from app.services.catalog import slugify

router = APIRouter(tags=["worldwide"])

Language = Annotated[str | None, Query(max_length=12, description="Catalog language code, e.g. te, hi, ko")]
Country = Annotated[str | None, Query(min_length=2, max_length=2, description="ISO 3166-1 alpha-2 release country")]


def _lang_code(value: str | None) -> str | None:
    if not value:
        return None
    code = value if value in langs.BY_CODE else langs.normalize(value)
    if code is None:
        raise NotFound("Unknown language")
    return code


def _interpreted(h: queryparse.Hints) -> dict:
    return {
        k: v
        for k, v in {
            "language": h.language,
            "country": h.country,
            "year_from": h.year_from,
            "year_to": h.year_to,
            "era": h.era,
            "text": h.rest or None,
        }.items()
        if v
    }


def _track_list(db, user, page, stmt, basis, interpreted=None) -> TrackListOut:
    items, total = paginate(db, stmt, page.offset, page.page_size)
    return TrackListOut(
        basis=basis,
        interpreted=interpreted or {},
        total=total,
        page=page.page,
        page_size=page.page_size,
        items=catalog_svc.song_outs(db, user, items),
    )


# --- tracks by date ---------------------------------------------------------------------------


@router.get("/music/latest", response_model=TrackListOut, summary="Most recently released tracks in the catalog")
def latest(
    db: DB,
    user: OptionalUser,
    page: PageParams,
    language: Language = None,
    country: Country = None,
    genre: str | None = None,
    year: int | None = Query(None, ge=1900, le=2100),
    source: str | None = None,
    full_only: bool = False,
    q: Annotated[str | None, Query(max_length=100, description="e.g. 'telugu latest songs'")] = None,
):
    h = queryparse.parse(q) if q else queryparse.Hints()
    language = _lang_code(language) or h.language
    country = country or h.country
    if language and page.page == 1:
        _warm_language(db, language)
    stmt = svc.dated_songs(
        language=language,
        country=country,
        genre=genre,
        year_from=year or h.year_from,
        year_to=year or h.year_to,
        source=source,
        full_only=full_only,
    )
    stmt = stmt.order_by(Album.release_date.desc(), Song.id)
    return _track_list(
        db, user, page, stmt, "Newest first by the album's release date; only tracks with a known release date are listed", _interpreted(h)
    )


@router.get("/music/old", response_model=TrackListOut, summary="Older and classic recordings")
def old(
    db: DB,
    user: OptionalUser,
    page: PageParams,
    language: Language = None,
    country: Country = None,
    genre: str | None = None,
    before: int = Query(2005, ge=1900, le=2100, description="Released in or before this year"),
    decade: Annotated[int | None, Query(ge=1900, le=2090, description="e.g. 1990 for the 1990s")] = None,
    source: str | None = None,
    full_only: bool = False,
    q: Annotated[str | None, Query(max_length=100)] = None,
):
    h = queryparse.parse(q) if q else queryparse.Hints()
    language = _lang_code(language) or h.language
    year_from, year_to = (decade, decade + 9) if decade else (h.year_from, h.year_to or before)
    if language and page.page == 1:
        _warm_language(db, language)
    stmt = svc.dated_songs(
        language=language,
        country=country or h.country,
        genre=genre,
        year_from=year_from,
        year_to=year_to,
        source=source,
        full_only=full_only,
    )
    stmt = stmt.order_by(Song.play_count.desc(), Song.provider_popularity.desc().nulls_last(), Album.release_date, Song.id)
    return _track_list(
        db,
        user,
        page,
        stmt,
        f"Released {year_from or 'any year'}-{year_to}; ordered by listens here, then the provider's "
        "own popularity signal where it gives one",
        _interpreted(h),
    )


# --- facets -----------------------------------------------------------------------------------


@router.get(
    "/music/countries",
    response_model=list[CountryOut],
    summary="Countries present in the catalog (built from provider metadata; missing values are 'Unknown')",
)
def countries(db: DB):
    where = song_country()
    rows = db.execute(
        select(where, func.count(), func.count().filter(playable_condition())).where(Song.is_published.is_(True)).group_by(where)
    ).all()
    known = sorted(((c, n, p) for c, n, p in rows if c), key=lambda r: -r[2])
    out = [CountryOut(code=c, name=country_name(c) or c, track_count=n, playable_count=p) for c, n, p in known]
    unknown = next(((n, p) for c, n, p in rows if not c), (0, 0))
    out.append(CountryOut(code=None, name="Unknown", track_count=unknown[0], playable_count=unknown[1]))
    return out


@router.get(
    "/music/tracks",
    response_model=TrackListOut,
    summary="Browse every track in the catalog by language, country, genre, year or source (no search text needed)",
)
def browse_tracks(
    db: DB,
    user: OptionalUser,
    page: PageParams,
    language: Language = None,
    country: Country = None,
    genre: str | None = None,
    year_from: int | None = Query(None, ge=1900, le=2100),
    year_to: int | None = Query(None, ge=1900, le=2100),
    source: str | None = None,
    full_only: bool = False,
    playable_only: Annotated[bool, Query(description="false also lists tracks that can't be played here (greyed out)")] = True,
    sort: Annotated[Literal["popular", "latest"], Query(description="`latest` needs a known release date")] = "popular",
):
    from app.services.unified_search import song_query

    stmt = song_query(
        "",
        language=_lang_code(language),
        country=country,
        genre=genre,
        year_from=year_from,
        year_to=year_to,
        source=source,
        full_only=full_only or playable_only,
        era="latest" if sort == "latest" else None,
    )
    basis = "Newest first by release date" if sort == "latest" else "Most listened here first, then the source's own popularity signal"
    return _track_list(db, user, page, stmt, basis)


@router.get(
    "/music/albums",
    response_model=list[AlbumCard],
    summary="Browse albums in the catalog (newest first), optionally by language, source or years",
)
def browse_albums(
    db: DB,
    language: Language = None,
    source: str | None = None,
    year_from: int | None = Query(None, ge=1900, le=2100),
    year_to: int | None = Query(None, ge=1900, le=2100),
    page: int = Query(1, ge=1, le=500),
    limit: int = Query(24, ge=1, le=60),
):
    return svc.search_albums(
        db,
        None,
        language=_lang_code(language),
        source=source,
        year_from=year_from,
        year_to=year_to,
        limit=limit,
        offset=(page - 1) * limit,
        playable_only=True,
    )


@router.get("/music/genres", response_model=list[GenreStat], summary="Genres with track counts, optionally within a language/country")
def genres(
    db: DB,
    language: Language = None,
    country: Country = None,
    include_empty: Annotated[bool, Query(description="Also list every canonical genre that has no tracks yet")] = False,
):
    cond = [Song.is_published.is_(True)]
    if language:
        cond.append(Song.language == _lang_code(language))
    if country:
        cond.append(song_country() == country.upper())
    rows = db.execute(
        select(Genre, func.count(Song.id), func.count(Song.id).filter(playable_condition()))
        .join(Song, Song.genre_id == Genre.id)
        .where(*cond)
        .group_by(Genre.id)
        .order_by(func.count(Song.id).filter(playable_condition()).desc(), Genre.name)
    ).all()
    out = [GenreStat(id=g.id, name=g.name, slug=g.slug, color=g.color, track_count=n, playable_count=p) for g, n, p in rows]
    if include_empty:
        have = {g.name for g in out}
        out += [
            GenreStat(id=None, name=name, slug=slugify(name), color=color, track_count=0, playable_count=0)
            for name, (color, _) in CANONICAL.items()
            if name not in have
        ]
    return out


@router.post(
    "/music/genres/fetch",
    response_model=GenreFetchOut,
    dependencies=[_provider_fanout_limit],
    summary="Pull one page of a genre (any canonical genre, even one with no tracks yet) from every provider that supports it",
)
def fetch_genre(data: GenreFetchIn, db: DB, _: CurrentUser):
    name = next((n for n in CANONICAL if n == data.genre or slugify(n) == data.genre), None)
    if name is None:
        raise NotFound("Unknown genre")
    result = federation.fetch_genre(db, name, page=data.page)
    statuses = [ProviderStatusOut(key=s.key, name=s.name, status=s.status, count=s.count, message=s.message) for s in result.statuses]
    return GenreFetchOut(
        genre=name, slug=slugify(name), page=data.page, imported=result.imported, updated=result.updated, providers=statuses
    )


# --- one track / its stream -------------------------------------------------------------------


@router.get("/music/tracks/{track_id}", response_model=SongOut, summary="One track by catalog id, or `<provider>:<provider id>`")
def track(track_id: str, db: DB, user: OptionalUser):
    song = _find_song(db, track_id)
    return catalog_svc.song_outs(db, user, [song])[0]


def _find_song(db, track_id: str) -> Song:
    try:
        song = db.get(Song, uuid.UUID(track_id))
    except ValueError:
        provider, _, pid = track_id.partition(":")
        song = db.scalar(select(Song).where(Song.source == provider, Song.provider_track_id == pid)) if pid else None
    if song is None or not song.is_published:
        raise NotFound("Track not found")
    return song


@router.get(
    "/music/stream/{provider}/{provider_track_id}",
    response_model=StreamUrl,
    responses={451: {"description": "Not permitted to play here"}},
    summary="Authorized playback URL for a provider track (rights re-verified when stale)",
)
def stream(provider: str, provider_track_id: str, db: DB, user: CurrentUser):
    song = db.scalar(select(Song).where(Song.source == provider, Song.provider_track_id == provider_track_id))
    if song is None:
        raise NotFound("Track not found")
    return streaming.stream_url(song.id, user, db)


# --- movies & soundtracks ---------------------------------------------------------------------


def _soundtrack_search(q, language, country, year_from, year_to, limit):
    h = queryparse.parse(q) if q else queryparse.Hints()
    language = _lang_code(language) or h.language
    country = (country or h.country or "").upper() or None
    year_from, year_to = year_from or h.year_from, year_to or h.year_to
    rows, statuses = soundtracks.search(
        h.rest if q else "", language=language, country=country, year_from=year_from, year_to=year_to, limit=limit
    )
    interpreted = {
        k: v
        for k, v in {"language": language, "country": country, "year_from": year_from, "year_to": year_to, "text": h.rest or None}.items()
        if v
    }
    return rows, statuses, interpreted


@router.get(
    "/music/soundtracks",
    response_model=SoundtrackSearchOut,
    dependencies=[_provider_fanout_limit],
    summary="Movie soundtrack albums (iTunes + MusicBrainz), e.g. q='telugu movie songs'",
)
def soundtrack_search(
    q: Annotated[str, Query(max_length=100)] = "",
    language: Language = None,
    country: Country = None,
    year_from: int | None = Query(None, ge=1900, le=2100),
    year_to: int | None = Query(None, ge=1900, le=2100),
    limit: int = Query(24, ge=1, le=50),
):
    rows, statuses, interpreted = _soundtrack_search(q, language, country, year_from, year_to, limit)
    return SoundtrackSearchOut(query=q, interpreted=interpreted, items=[SoundtrackOut(**r) for r in rows], providers=statuses)


@router.get(
    "/music/movies",
    response_model=MovieSearchOut,
    dependencies=[_provider_fanout_limit],
    summary="Movies grouped with their soundtrack albums",
)
def movies(
    q: Annotated[str, Query(max_length=100)] = "",
    language: Language = None,
    country: Country = None,
    year_from: int | None = Query(None, ge=1900, le=2100),
    year_to: int | None = Query(None, ge=1900, le=2100),
    limit: int = Query(24, ge=1, le=50),
):
    rows, statuses, interpreted = _soundtrack_search(q, language, country, year_from, year_to, limit)
    items = [MovieOut(**{**g, "soundtracks": [SoundtrackOut(**r) for r in g["soundtracks"]]}) for g in soundtracks.group_by_movie(rows)]
    return MovieSearchOut(query=q, interpreted=interpreted, items=items, providers=statuses)


@router.get(
    "/music/soundtracks/{soundtrack_id}",
    response_model=SoundtrackDetail,
    summary="Soundtrack with its track listing; tracks are playable only where a provider supplies audio",
)
def soundtrack_detail(soundtrack_id: str, db: DB, user: OptionalUser):
    try:
        row, raw = soundtracks.detail(soundtrack_id)
    except ProviderError as exc:
        if exc.kind == "not_found":
            raise NotFound("Soundtrack not found") from exc
        from app.core.errors import AppError

        raise AppError(f"{exc.provider} is unavailable right now: {exc.message}", code="provider_unavailable", status_code=502) from exc
    tracks: list[SoundtrackTrack] = []
    if row["provider"] == "itunes":
        result = ingest(db, raw)
        by_id = {s.provider_track_id: s for s in result.songs}
        outs = {s.id: o for s, o in zip(result.songs, catalog_svc.song_outs(db, user, result.songs), strict=True)}
        for n, t in enumerate(raw, start=1):
            song = by_id.get(t.provider_track_id)
            out = outs.get(song.id) if song else None
            tracks.append(
                SoundtrackTrack(
                    number=n,
                    title=t.title,
                    singers=t.artist_name,
                    duration_ms=t.duration_ms,
                    song=out,
                    access=out.access if out else "full",
                )
            )
        if tracks and any(t.access == "full" for t in tracks):
            row["access"] = "full"

    else:
        tracks = [
            SoundtrackTrack(number=t["number"], title=t["title"], singers=t["artist"], duration_ms=t["duration_ms"], access="metadata")
            for t in raw
        ]
    return SoundtrackDetail(**row, tracks=tracks)


# --- artists & albums -------------------------------------------------------------------------


@router.get(
    "/artists/search",
    response_model=ArtistSearchOut,
    dependencies=[_provider_fanout_limit],
    summary="Search singers/artists. Providers are queried live and matches join the catalog.",
)
def artist_search(
    db: DB,
    user: OptionalUser,
    q: Annotated[str, Query(min_length=2, max_length=100)],
    language: Language = None,
    country: Country = None,
    source: str | None = None,
    live: bool = True,
    limit: int = Query(20, ge=1, le=50),
):
    q = q.strip()
    statuses = svc.ingest_for_query(db, q) if live else []
    items = svc.search_artists(db, user, q, language=_lang_code(language), country=country, source=source, limit=limit)
    return ArtistSearchOut(
        query=q,
        items=items,
        providers=[ProviderStatusOut(key=s.key, name=s.name, status=s.status, count=s.count, message=s.message) for s in statuses],
    )


class ArtistPhotosIn(BaseModel):
    ids: list[uuid.UUID] = Field(max_length=40)


@router.post(
    "/music/artists/photos",
    response_model=dict[uuid.UUID, str],
    dependencies=[_provider_fanout_limit],
    summary="Find real portraits for artists that only have album artwork; returns {artist_id: image_url} for those found",
)
def find_artist_photos(data: ArtistPhotosIn, db: DB, _: CurrentUser):
    artists = [a for a in db.scalars(select(Artist).where(Artist.id.in_(data.ids))).unique() if not a.image_url]
    with ThreadPoolExecutor(max_workers=8) as pool:  # lookups are independent network calls
        urls = list(pool.map(lambda a: artist_photos.portrait_url(a.name), artists))
    found: dict[uuid.UUID, str] = {}
    for artist, url in zip(artists, urls, strict=True):
        if url:
            artist.image_url = url
            found[artist.id] = url
    if found:
        db.commit()
    return found


@router.get(
    "/music/artists",
    response_model=list[ArtistCard],
    summary="Artists ranked by playable music in this catalog and listens here - not a provider popularity chart",
)
def catalog_artists(db: DB, user: OptionalUser, language: Language = None, limit: int = Query(18, ge=1, le=50)):
    n = func.count().filter(playable_condition())
    plays = func.coalesce(func.sum(Song.play_count), 0)
    stmt = select(Song.artist_id).where(Song.is_published.is_(True))
    if language:
        stmt = stmt.where(Song.language == _lang_code(language))
    ids = list(db.scalars(stmt.group_by(Song.artist_id).having(n > 0).order_by(plays.desc(), n.desc(), Song.artist_id).limit(limit)))
    artists = {a.id: a for a in db.scalars(select(Artist).where(Artist.id.in_(ids))).unique()}
    return svc.artist_cards(db, user, [artists[i] for i in ids if i in artists])


@router.get(
    "/artists/{artist_id}/profile",
    response_model=ArtistProfile,
    summary="Artist page: albums, singles, top songs, release history and related artists",
)
def artist_profile(artist_id: uuid.UUID, db: DB, user: OptionalUser, refresh: bool = True):
    artist = db.get(Artist, artist_id)
    if artist is None:
        raise NotFound("Artist not found")
    return svc.artist_profile(db, user, artist, refresh=refresh)


@router.get(
    "/albums/search", response_model=AlbumSearchOut, dependencies=[_provider_fanout_limit], summary="Search albums by title or artist"
)
def album_search(
    db: DB,
    q: Annotated[str, Query(min_length=2, max_length=100)],
    language: Language = None,
    source: str | None = None,
    year_from: int | None = Query(None, ge=1900, le=2100),
    year_to: int | None = Query(None, ge=1900, le=2100),
    live: bool = True,
    limit: int = Query(20, ge=1, le=50),
):
    q = q.strip()
    statuses = svc.ingest_for_query(db, q) if live else []
    items = svc.search_albums(db, q, language=_lang_code(language), source=source, year_from=year_from, year_to=year_to, limit=limit)
    return AlbumSearchOut(
        query=q,
        items=items,
        providers=[ProviderStatusOut(key=s.key, name=s.name, status=s.status, count=s.count, message=s.message) for s in statuses],
    )
