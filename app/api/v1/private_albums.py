import uuid

from fastapi import APIRouter, File, Query, UploadFile

from app.api.deps import DB, CurrentUser, OptionalUser
from app.schemas.common import Message
from app.schemas.private_album import (
    AddAlbumTracks,
    AlbumSort,
    PrivateAlbumCreate,
    PrivateAlbumDetail,
    PrivateAlbumSummary,
    PrivateAlbumUpdate,
)
from app.services import private_albums as svc

router = APIRouter(tags=["private-albums"])


@router.get("/private-albums", response_model=list[PrivateAlbumSummary], summary="My private albums (favorites first)")
def list_albums(
    user: CurrentUser, db: DB, sort: AlbumSort = "updated", favorites: bool = False, q: str | None = Query(None, max_length=100)
):
    return svc.list_mine(db, user, sort=sort, favorites_only=favorites, q=q)


@router.post("/private-albums", response_model=PrivateAlbumDetail, status_code=201)
def create_album(data: PrivateAlbumCreate, user: CurrentUser, db: DB):
    return svc.detail(db, svc.create(db, user, data), user)


@router.get(
    "/private-albums/shared/{code}", response_model=PrivateAlbumDetail, summary="A public album, by its share code (no sign-in needed)"
)
def shared_album(code: str, db: DB, user: OptionalUser):
    return svc.detail(db, svc.get_shared(db, code), user)


@router.get("/private-albums/{album_id}", response_model=PrivateAlbumDetail, summary="Owner only")
def get_album(album_id: uuid.UUID, user: CurrentUser, db: DB):
    return svc.detail(db, svc.get_viewable(db, album_id, user), user)


@router.patch("/private-albums/{album_id}", response_model=PrivateAlbumDetail, summary="Rename, change visibility, favorite, pick cover")
def update_album(album_id: uuid.UUID, data: PrivateAlbumUpdate, user: CurrentUser, db: DB):
    return svc.detail(db, svc.update(db, album_id, user, data), user)


@router.post("/private-albums/{album_id}/cover", response_model=PrivateAlbumDetail)
def upload_cover(album_id: uuid.UUID, user: CurrentUser, db: DB, file: UploadFile = File(...)):
    return svc.detail(db, svc.set_cover(db, album_id, user, file), user)


@router.post(
    "/private-albums/{album_id}/share", response_model=PrivateAlbumDetail, summary="Issue a new share link (the old one stops working)"
)
def new_share_link(album_id: uuid.UUID, user: CurrentUser, db: DB):
    return svc.detail(db, svc.rotate_share_code(db, album_id, user), user)


@router.delete("/private-albums/{album_id}", response_model=Message)
def delete_album(album_id: uuid.UUID, user: CurrentUser, db: DB):
    svc.delete(db, album_id, user)
    return Message(message="Album deleted")


@router.post("/private-albums/{album_id}/tracks", response_model=PrivateAlbumDetail)
def add_tracks(album_id: uuid.UUID, data: AddAlbumTracks, user: CurrentUser, db: DB):
    return svc.detail(db, svc.add_tracks(db, album_id, user, data.song_ids), user)


@router.delete("/private-albums/{album_id}/tracks/{item_id}", response_model=PrivateAlbumDetail)
def remove_track(album_id: uuid.UUID, item_id: int, user: CurrentUser, db: DB):
    return svc.detail(db, svc.remove_track(db, album_id, user, item_id), user)
