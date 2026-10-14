"""Artist / album discovery and the "latest" / "old" track lists, built on the catalog that provider searches fill."""

import logging
from collections import defaultdict

from sqlalchemy import Integer, Select, cast, func, or_, select
from sqlalchemy.orm import Session

from app.models import Album, AlbumType, Artist, FollowedArtist, Genre, Song, User
from app.music import federation
from app.music.http import ProviderError
from app.music.providers import get_provider, is_enabled
from app.repositories.catalog import playable_condition, song_country
from app.schemas.catalog import AlbumOut
from app.schemas.worldmusic import AlbumCard, ArtistCard, ArtistProfile, ReleaseYear
from app.services.discovery import _match

log = logging.getLogger(__name__)

# --- tracks by release date ---------------------------------------------------------------------


def dated_songs(
    *,
    language: str | None,
    country: str | None,
    genre: str | None,
    year_from: int | None,
    year_to: int | None,
    source: str | None,
    full_only: bool,
    playable_only: bool = True,
) -> Select:
    stmt = select(Song).join(Album, Album.id == Song.album_id).where(Song.is_published.is_(True), Album.release_date.is_not(None))
    if playable_only:
        stmt = stmt.where(playable_condition())
    if full_only:
        stmt = stmt.where(or_(Song.license_code.is_(None), Song.license_code != "preview"))
    if language:
        stmt = stmt.where(Song.language == language)
    if country:
        stmt = stmt.where(song_country() == country.upper())
    if source:
        stmt = stmt.where(Song.source == source)
    if genre:
        stmt = stmt.join(Genre, Genre.id == Song.genre_id).where(Genre.slug == genre)
    if year_from:
        stmt = stmt.where(func.extract("year", Album.release_date) >= year_from)
    if year_to:
        stmt = stmt.where(func.extract("year", Album.release_date) <= year_to)
    return stmt


# --- artists ------------------------------------------------------------------------------------


def ingest_for_query(db: Session, q: str) -> list:
    """Run the live provider search so matching artists/albums exist in the catalog. Never raises."""
    try:
        return federation.global_search(db, q, language=None, limit=20).statuses
    except Exception:
        log.exception("worldmusic.ingest_failed")
        return []


def _artist_stats(db: Session, artist_ids: list) -> dict:
    if not artist_ids:
        return {}
    songs = {
        a: (n, p)
        for a, n, p in db.execute(
            select(Song.artist_id, func.count(), func.count().filter(playable_condition()))
            .where(Song.artist_id.in_(artist_ids), Song.is_published.is_(True))
            .group_by(Song.artist_id)
        )
    }
    albums = {
        a: n for a, n in db.execute(select(Album.artist_id, func.count()).where(Album.artist_id.in_(artist_ids)).group_by(Album.artist_id))
    }
    langs_by: dict = defaultdict(list)
    for a, lang in db.execute(
        select(Song.artist_id, Song.language)
        .where(Song.artist_id.in_(artist_ids), Song.language.is_not(None))
        .group_by(Song.artist_id, Song.language)
    ):
        langs_by[a].append(lang)
    cover = {}
    for a, url in db.execute(
        select(Album.artist_id, Album.cover_url)
        .where(Album.artist_id.in_(artist_ids), Album.cover_url.is_not(None))
        .order_by(Album.release_date.desc().nulls_last())
    ):
        cover.setdefault(a, url)
    art = {}
    for a, url in db.execute(select(Song.artist_id, Song.artwork_url).where(Song.artist_id.in_(artist_ids), Song.artwork_url.is_not(None))):
        art.setdefault(a, url)
    return {
        a: {
            "song_count": songs.get(a, (0, 0))[0],
            "playable_count": songs.get(a, (0, 0))[1],
            "album_count": albums.get(a, 0),
            "languages": sorted(langs_by.get(a, [])),
            "image_fallback": cover.get(a) or art.get(a),
        }
        for a in artist_ids
    }


def artist_cards(db: Session, user: User | None, artists: list[Artist]) -> list[ArtistCard]:
    stats = _artist_stats(db, [a.id for a in artists])
    followed = (
        set(
            db.scalars(
                select(FollowedArtist.artist_id).where(
                    FollowedArtist.user_id == user.id, FollowedArtist.artist_id.in_([a.id for a in artists])
                )
            )
        )
        if user
        else set()
    )
    return [
        ArtistCard.model_validate(
            {
                **{f: getattr(a, f) for f in ("id", "name", "slug", "bio", "image_url", "verified", "source", "source_url", "country")},
                **stats[a.id],
                "is_followed": (a.id in followed) if user else None,
            }
        )
        for a in artists
    ]


def search_artists(
    db: Session, user: User | None, q: str, *, language: str | None, country: str | None, source: str | None, limit: int, offset: int = 0
) -> list[ArtistCard]:
    stmt = select(Artist).where(or_(_match(Artist.name, q), func.similarity(Artist.name, q) > 0.35))
    if country:
        stmt = stmt.where(Artist.country == country.upper())
    if source:
        stmt = stmt.where(Artist.source == source)
    if language:
        stmt = stmt.where(Artist.id.in_(select(Song.artist_id).where(Song.language == language)))
    # Artists with playable music first, then closest name.
    playable = select(Song.artist_id, func.count().label("n")).where(playable_condition()).group_by(Song.artist_id).subquery()
    stmt = (
        stmt.outerjoin(playable, playable.c.artist_id == Artist.id)
        .order_by(
            (func.lower(Artist.name) == q.lower()).desc(),
            func.coalesce(playable.c.n, 0).desc(),
            func.similarity(Artist.name, q).desc(),
            Artist.id,
        )
        .offset(offset)
        .limit(limit)
    )
    return artist_cards(db, user, list(db.scalars(stmt).unique()))


def top_up_artist(db: Session, artist: Artist) -> list:
    """Pull more of this artist's catalog from their provider (iTunes lookup), when the provider supports it."""
    statuses = []
    if artist.source == "itunes" and artist.provider_artist_id and artist.provider_artist_id.isdigit():
        from app.music.ingest import ingest
        from app.schemas.music import ProviderStatusOut

        itunes = get_provider("itunes")
        if itunes and is_enabled(itunes):
            try:
                rows = itunes.lookup_artist(artist.provider_artist_id, entity="song", limit=50)
                tracks = [t for r in rows if r.get("wrapperType") == "track" and (t := itunes._to_track(r))]
                ingest(db, tracks)
                statuses.append(ProviderStatusOut(key="itunes", name=itunes.name, status="ok", count=len(tracks), message=None))
            except ProviderError as exc:
                statuses.append(ProviderStatusOut(key="itunes", name=itunes.name, status="error", count=0, message=exc.message))
    return statuses


def artist_profile(db: Session, user: User | None, artist: Artist, *, refresh: bool = True) -> ArtistProfile:
    statuses = top_up_artist(db, artist) if refresh else []
    card = artist_cards(db, user, [artist])[0]
    albums = list(
        db.scalars(select(Album).where(Album.artist_id == artist.id).order_by(Album.release_date.desc().nulls_last(), Album.title)).unique()
    )
    # A provider track with no album reference is treated as a standalone single on the release history only.
    singles = [
        a
        for a in albums
        if a.album_type == AlbumType.single
        or (a.album_type == AlbumType.album and (db.scalar(select(func.count()).select_from(Song).where(Song.album_id == a.id)) or 0) == 1)
    ]
    single_ids = {a.id for a in singles}
    full_albums = [a for a in albums if a.id not in single_ids]
    top = list(
        db.scalars(
            select(Song)
            .where(Song.artist_id == artist.id, Song.is_published.is_(True))
            .order_by(playable_condition().desc(), Song.play_count.desc(), Song.provider_popularity.desc().nulls_last(), Song.id)
            .limit(10)
        ).unique()
    )
    from app.services import catalog as catalog_svc

    years: dict[int, list[int]] = defaultdict(lambda: [0, 0])
    for a in albums:
        if a.release_date:
            years[a.release_date.year][0] += 1
    release_year = cast(func.extract("year", Album.release_date), Integer)
    for year, n in db.execute(
        select(release_year, func.count(Song.id))
        .join(Song, Song.album_id == Album.id)
        .where(Album.artist_id == artist.id, Album.release_date.is_not(None))
        .group_by(release_year)
    ):
        years[int(year)][1] = n
    related, basis = related_artists(db, user, artist)
    return ArtistProfile.model_validate(
        {
            **card.model_dump(),
            "albums": [AlbumOut.model_validate(a) for a in full_albums],
            "singles": [AlbumOut.model_validate(a) for a in singles],
            "top_songs": catalog_svc.song_outs(db, user, top),
            "follower_count": db.scalar(select(func.count()).select_from(FollowedArtist).where(FollowedArtist.artist_id == artist.id)) or 0,
            "release_history": [ReleaseYear(year=y, albums=v[0], songs=v[1]) for y, v in sorted(years.items(), reverse=True)],
            "related": related,
            "related_basis": basis,
            "providers": statuses,
        }
    )


def related_artists(db: Session, user: User | None, artist: Artist, limit: int = 8) -> tuple[list[ArtistCard], str]:
    """Artists whose catalog overlaps this one's in genre and language - computed from our data, not a provider's graph."""
    genre_ids = list(db.scalars(select(Song.genre_id).where(Song.artist_id == artist.id, Song.genre_id.is_not(None)).distinct()))
    languages = list(db.scalars(select(Song.language).where(Song.artist_id == artist.id, Song.language.is_not(None)).distinct()))
    basis = "Artists in this catalog sharing this artist's genres and languages (not a provider's recommendation graph)"
    if not genre_ids:
        return [], basis
    cond = [Song.artist_id != artist.id, playable_condition(), Song.genre_id.in_(genre_ids)]
    if languages:
        cond.append(Song.language.in_(languages))
    overlap = (
        select(Song.artist_id, func.count().label("n"))
        .where(*cond)
        .group_by(Song.artist_id)
        .order_by(func.count().desc())
        .limit(limit)
        .subquery()
    )
    found = list(db.scalars(select(Artist).join(overlap, overlap.c.artist_id == Artist.id).order_by(overlap.c.n.desc())).unique())
    return artist_cards(db, user, found), basis


def search_albums(
    db: Session,
    q: str | None,
    *,
    language: str | None,
    source: str | None,
    year_from: int | None,
    year_to: int | None,
    limit: int,
    offset: int = 0,
    playable_only: bool = False,
) -> list[AlbumCard]:
    stmt = select(Album).join(Artist, Artist.id == Album.artist_id)
    if q:
        stmt = stmt.where(or_(_match(Album.title, q), func.similarity(Album.title, q) > 0.35, _match(Artist.name, q)))
    if source:
        stmt = stmt.where(Album.source == source)
    if playable_only:  # an album none of whose tracks can be played here isn't worth listing
        stmt = stmt.where(Album.id.in_(select(Song.album_id).where(playable_condition())))
    if language:
        stmt = stmt.where(Album.id.in_(select(Song.album_id).where(Song.language == language)))
    if year_from:
        stmt = stmt.where(func.extract("year", Album.release_date) >= year_from)
    if year_to:
        stmt = stmt.where(func.extract("year", Album.release_date) <= year_to)
    order = ((func.lower(Album.title) == q.lower()).desc(), func.similarity(Album.title, q).desc()) if q else ()
    albums = list(db.scalars(stmt.order_by(*order, Album.release_date.desc().nulls_last(), Album.id).offset(offset).limit(limit)).unique())
    ids = [a.id for a in albums]
    counts = (
        {
            a: (n, p)
            for a, n, p in db.execute(
                select(Song.album_id, func.count(), func.count().filter(playable_condition()))
                .where(Song.album_id.in_(ids))
                .group_by(Song.album_id)
            )
        }
        if ids
        else {}
    )
    langs_by = {}
    for a, lang in (
        db.execute(
            select(Song.album_id, Song.language)
            .where(Song.album_id.in_(ids), Song.language.is_not(None))
            .group_by(Song.album_id, Song.language)
        )
        if ids
        else []
    ):
        langs_by.setdefault(a, lang)
    return [
        AlbumCard.model_validate(
            {
                **AlbumOut.model_validate(a).model_dump(),
                "track_count": counts.get(a.id, (0, 0))[0],
                "playable_count": counts.get(a.id, (0, 0))[1],
                "language": langs_by.get(a.id),
            }
        )
        for a in albums
    ]
