from typing import Annotated

from fastapi import APIRouter, Query
from pydantic import BaseModel
from sqlalchemy import func, select

from app.api.deps import DB, CurrentUser, OptionalUser, PageParams
from app.models import Album, Genre, Language, Playlist, Song
from app.repositories.catalog import paginate, playable_condition
from app.schemas.catalog import AlbumOut, ArtistOut, GenreOut, SongOut
from app.schemas.common import Page
from app.schemas.playlist import PlaylistSummary
from app.services import catalog as catalog_svc
from app.services import discovery as svc
from app.services.library import recently_played_songs
from app.services.playlists import summarize_many

router = APIRouter(tags=["discovery"])


class SearchResults(BaseModel):
    query: str
    songs: Page[SongOut] | None = None
    artists: Page[ArtistOut] | None = None
    albums: Page[AlbumOut] | None = None
    playlists: Page[PlaylistSummary] | None = None


@router.get("/search", response_model=SearchResults)
def search(
    db: DB,
    user: OptionalUser,
    page: PageParams,
    q: Annotated[str, Query(min_length=1, max_length=100)],
    type: Annotated[str, Query(description="Comma-separated: song,artist,album,playlist")] = "song,artist,album,playlist",
    genre: str | None = None,
    sort: svc.SearchSort = "relevance",
):
    q = q.strip()
    types = {t.strip() for t in type.split(",")}
    result = SearchResults(query=q)
    if not q:
        return result
    if "song" in types:
        items, total = paginate(db, svc.search_songs(q, genre=genre, sort=sort), page.offset, page.page_size)
        result.songs = Page.build(catalog_svc.song_outs(db, user, items), total, page.page, page.page_size)
    if "artist" in types:
        items, total = paginate(db, svc.search_artists(q, genre=genre, sort=sort), page.offset, page.page_size)
        result.artists = Page.build(items, total, page.page, page.page_size)
    if "album" in types:
        items, total = paginate(db, svc.search_albums(q, genre=genre, sort=sort), page.offset, page.page_size)
        result.albums = Page.build(items, total, page.page, page.page_size)
    if "playlist" in types:
        items, total = paginate(db, svc.search_playlists(q, sort=sort), page.offset, page.page_size)
        result.playlists = Page.build(summarize_many(db, items), total, page.page, page.page_size)
    return result


class HomeLanguage(BaseModel):
    code: str
    name: str
    native_name: str
    playable_count: int


class HomeFeed(BaseModel):
    featured: list[AlbumOut]
    new_releases: list[AlbumOut]
    trending: list[SongOut]
    recommended: list[SongOut]
    recently_played: list[SongOut]
    genres: list[GenreOut]
    public_playlists: list[PlaylistSummary]
    languages: list[HomeLanguage] = []
    in_your_languages: list[SongOut] = []


@router.get("/browse/home", response_model=HomeFeed, summary="Everything the home screen needs in one call")
def home(db: DB, user: OptionalUser):
    has_audio = Album.id.in_(select(Song.album_id).where(playable_condition()))  # albums nobody can play aren't shelved
    featured = (
        db.scalars(select(Album).where(Album.is_featured.is_(True), has_audio).order_by(Album.release_date.desc().nulls_last()).limit(8))
        .unique()
        .all()
    )
    new_releases = (
        db.scalars(select(Album).where(has_audio).order_by(Album.release_date.desc().nulls_last(), Album.id).limit(10)).unique().all()
    )
    trending = svc.trending_songs(db, 10)
    recommended = svc.recommendations(db, user, 12) if user else []
    recent = recently_played_songs(db, user, 8) if user else []
    playlists = (
        db.scalars(select(Playlist).where(Playlist.is_public.is_(True)).order_by(Playlist.updated_at.desc()).limit(8)).unique().all()
    )
    counts = (
        select(Song.language, func.count().label("n"))
        .where(playable_condition(), Song.language.is_not(None))
        .group_by(Song.language)
        .subquery()
    )
    languages = [
        HomeLanguage(code=lang.code, name=lang.name, native_name=lang.native_name, playable_count=n)
        for lang, n in db.execute(
            select(Language, counts.c.n)
            .join(counts, counts.c.language == Language.code)
            .order_by(Language.featured_rank.nulls_last(), counts.c.n.desc())
            .limit(16)
        )
    ]
    preferred = list(user.preferred_languages or []) if user else []
    in_your_languages = db.scalars(svc.popular_songs(12).where(Song.language.in_(preferred))).unique().all() if preferred else []
    return HomeFeed(
        languages=languages,
        in_your_languages=catalog_svc.song_outs(db, user, in_your_languages),
        featured=featured,
        new_releases=new_releases,
        trending=catalog_svc.song_outs(db, user, trending),
        recommended=catalog_svc.song_outs(db, user, recommended),
        recently_played=catalog_svc.song_outs(db, user, recent),
        genres=db.scalars(select(Genre).order_by(Genre.name)).all(),
        public_playlists=summarize_many(db, list(playlists)),
    )


@router.get("/browse/new-releases", response_model=Page[AlbumOut])
def new_releases(db: DB, page: PageParams):
    playable = Album.id.in_(select(Song.album_id).where(playable_condition()))
    items, total = paginate(
        db, select(Album).where(playable).order_by(Album.release_date.desc().nulls_last(), Album.id), page.offset, page.page_size
    )
    return Page.build(items, total, page.page, page.page_size)


@router.get("/browse/trending", response_model=list[SongOut])
def trending(db: DB, user: OptionalUser, limit: int = Query(20, ge=1, le=50)):
    return catalog_svc.song_outs(db, user, svc.trending_songs(db, limit))


@router.get("/me/recommendations", response_model=list[SongOut])
def recommendations(db: DB, user: CurrentUser, limit: int = Query(20, ge=1, le=50)):
    return catalog_svc.song_outs(db, user, svc.recommendations(db, user, limit))
