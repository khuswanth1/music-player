import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile
from sqlalchemy import select

from app.api.deps import DB, OptionalUser, PageParams, require_permission
from app.core.permissions import Perm
from app.models import AlbumType, Genre, User
from app.repositories import catalog as repo
from app.schemas.catalog import (
    AlbumCreate,
    AlbumDetail,
    AlbumOut,
    AlbumUpdate,
    ArtistCreate,
    ArtistDetail,
    ArtistOut,
    ArtistUpdate,
    GenreCreate,
    GenreOut,
    GenreUpdate,
    SongOut,
    SongUpdate,
)
from app.schemas.common import Message, Page
from app.services import catalog as svc

router = APIRouter()
CatalogEditor = Annotated[User, Depends(require_permission(Perm.catalog_write))]


# --- genres --------------------------------------------------------------------------------

@router.get("/genres", response_model=list[GenreOut], tags=["genres"])
def list_genres(db: DB):
    return db.scalars(select(Genre).order_by(Genre.name)).all()


@router.get("/genres/{slug}", response_model=GenreOut, tags=["genres"])
def get_genre(slug: str, db: DB):
    return svc.get_genre_by_slug(db, slug)


@router.post("/genres", response_model=GenreOut, status_code=201, tags=["genres"])
def create_genre(data: GenreCreate, _: CatalogEditor, db: DB):
    return svc.create_genre(db, data)


@router.patch("/genres/{genre_id}", response_model=GenreOut, tags=["genres"])
def update_genre(genre_id: int, data: GenreUpdate, _: CatalogEditor, db: DB):
    return svc.update_genre(db, genre_id, data)


@router.delete("/genres/{genre_id}", response_model=Message, tags=["genres"])
def delete_genre(genre_id: int, _: CatalogEditor, db: DB):
    svc.delete_genre(db, genre_id)
    return Message(message="Genre deleted")


# --- artists -------------------------------------------------------------------------------

@router.get("/artists", response_model=Page[ArtistOut], tags=["artists"])
def list_artists(db: DB, page: PageParams, genre: str | None = None,
                 sort: Literal["name", "popular"] = "name"):
    items, total = repo.paginate(db, repo.artists_query(genre_slug=genre, sort=sort), page.offset, page.page_size)
    return Page.build(items, total, page.page, page.page_size)


@router.get("/artists/{artist_id}", response_model=ArtistDetail, tags=["artists"])
def get_artist(artist_id: uuid.UUID, db: DB, user: OptionalUser):
    return svc.artist_detail(db, svc.get_artist(db, artist_id), user)


@router.get("/artists/{artist_id}/top-songs", response_model=list[SongOut], tags=["artists"])
def artist_top_songs(artist_id: uuid.UUID, db: DB, user: OptionalUser, limit: int = Query(10, ge=1, le=50)):
    svc.get_artist(db, artist_id)
    songs = db.scalars(repo.songs_query(artist_id=artist_id, sort="popular").limit(limit)).unique().all()
    return svc.song_outs(db, user, songs)


@router.get("/artists/{artist_id}/albums", response_model=list[AlbumOut], tags=["artists"])
def artist_albums(artist_id: uuid.UUID, db: DB):
    svc.get_artist(db, artist_id)
    return db.scalars(repo.albums_query(artist_id=artist_id)).unique().all()


@router.post("/artists", response_model=ArtistOut, status_code=201, tags=["artists"])
def create_artist(data: ArtistCreate, _: CatalogEditor, db: DB):
    return svc.create_artist(db, data)


@router.patch("/artists/{artist_id}", response_model=ArtistOut, tags=["artists"])
def update_artist(artist_id: uuid.UUID, data: ArtistUpdate, _: CatalogEditor, db: DB):
    return svc.update_artist(db, artist_id, data)


@router.post("/artists/{artist_id}/image", response_model=ArtistOut, tags=["artists"])
def upload_artist_image(artist_id: uuid.UUID, _: CatalogEditor, db: DB, file: UploadFile = File(...)):
    return svc.set_artist_image(db, artist_id, file)


@router.delete("/artists/{artist_id}", response_model=Message, tags=["artists"])
def delete_artist(artist_id: uuid.UUID, _: CatalogEditor, db: DB):
    svc.delete_artist(db, artist_id)
    return Message(message="Artist deleted")


# --- albums --------------------------------------------------------------------------------

@router.get("/albums", response_model=Page[AlbumOut], tags=["albums"])
def list_albums(db: DB, page: PageParams, artist_id: uuid.UUID | None = None, genre: str | None = None,
                album_type: AlbumType | None = None, featured: bool | None = None,
                sort: Literal["newest", "oldest", "title"] = "newest"):
    stmt = repo.albums_query(artist_id=artist_id, genre_slug=genre, album_type=album_type,
                             featured=featured, sort=sort)
    items, total = repo.paginate(db, stmt, page.offset, page.page_size)
    return Page.build(items, total, page.page, page.page_size)


@router.get("/albums/{album_id}", response_model=AlbumDetail, tags=["albums"])
def get_album(album_id: uuid.UUID, db: DB, user: OptionalUser):
    return svc.album_detail(db, svc.get_album(db, album_id), user)


@router.post("/albums", response_model=AlbumOut, status_code=201, tags=["albums"])
def create_album(data: AlbumCreate, _: CatalogEditor, db: DB):
    return svc.create_album(db, data)


@router.patch("/albums/{album_id}", response_model=AlbumOut, tags=["albums"])
def update_album(album_id: uuid.UUID, data: AlbumUpdate, _: CatalogEditor, db: DB):
    return svc.update_album(db, album_id, data)


@router.post("/albums/{album_id}/cover", response_model=AlbumOut, tags=["albums"])
def upload_album_cover(album_id: uuid.UUID, _: CatalogEditor, db: DB, file: UploadFile = File(...)):
    return svc.set_album_cover(db, album_id, file)


@router.delete("/albums/{album_id}", response_model=Message, tags=["albums"])
def delete_album(album_id: uuid.UUID, _: CatalogEditor, db: DB):
    svc.delete_album(db, album_id)
    return Message(message="Album deleted")


# --- songs ---------------------------------------------------------------------------------

@router.get("/songs", response_model=Page[SongOut], tags=["songs"])
def list_songs(db: DB, user: OptionalUser, page: PageParams, genre: str | None = None,
               artist_id: uuid.UUID | None = None, album_id: uuid.UUID | None = None,
               sort: Literal["popular", "newest", "title", "duration"] = "popular",
               include_unpublished: bool = False):
    stmt = repo.songs_query(genre_slug=genre, artist_id=artist_id, album_id=album_id, sort=sort,
                            include_unpublished=include_unpublished and svc.is_staff(user))
    items, total = repo.paginate(db, stmt, page.offset, page.page_size)
    return Page.build(svc.song_outs(db, user, items), total, page.page, page.page_size)


@router.get("/songs/{song_id}", response_model=SongOut, tags=["songs"])
def get_song(song_id: uuid.UUID, db: DB, user: OptionalUser):
    return svc.song_outs(db, user, [svc.get_song(db, song_id, user)])[0]


@router.post("/songs", response_model=SongOut, status_code=201, tags=["songs"],
             summary="Upload a song (multipart: metadata fields + audio file)")
def create_song(_: CatalogEditor, db: DB,
                title: str = Form(...), artist_id: uuid.UUID = Form(...),
                album_id: uuid.UUID | None = Form(None), genre_id: int | None = Form(None),
                track_number: int | None = Form(None, ge=1, le=999), explicit: bool = Form(False),
                is_premium: bool = Form(False), is_published: bool = Form(True),
                file: UploadFile = File(..., description="MP3, OGG, FLAC, WAV or M4A")):
    song = svc.create_song(db, title=title, artist_id=artist_id, album_id=album_id, genre_id=genre_id,
                           track_number=track_number, explicit=explicit, is_premium=is_premium,
                           is_published=is_published, audio=file)
    return SongOut.model_validate(song)


@router.patch("/songs/{song_id}", response_model=SongOut, tags=["songs"])
def update_song(song_id: uuid.UUID, data: SongUpdate, _: CatalogEditor, db: DB):
    return SongOut.model_validate(svc.update_song(db, song_id, data))


@router.put("/songs/{song_id}/audio", response_model=SongOut, tags=["songs"])
def replace_audio(song_id: uuid.UUID, _: CatalogEditor, db: DB, file: UploadFile = File(...)):
    return SongOut.model_validate(svc.replace_song_audio(db, song_id, file))


@router.delete("/songs/{song_id}", response_model=Message, tags=["songs"])
def delete_song(song_id: uuid.UUID, _: CatalogEditor, db: DB):
    svc.delete_song(db, song_id)
    return Message(message="Song deleted")
