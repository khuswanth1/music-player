import uuid

from fastapi import APIRouter, File, UploadFile

from app.api.deps import DB, CurrentUser, OptionalUser
from app.schemas.common import Message
from app.schemas.playlist import (
    AddTracksRequest,
    JoinPlaylistRequest,
    PlaylistCreate,
    PlaylistDetail,
    PlaylistSummary,
    PlaylistUpdate,
    ReorderRequest,
)
from app.services import playlists as svc

router = APIRouter(tags=["playlists"])


@router.get("/me/playlists", response_model=list[PlaylistSummary], summary="Playlists I own or collaborate on")
def my_playlists(user: CurrentUser, db: DB):
    return svc.list_for_user(db, user)


@router.post("/playlists", response_model=PlaylistDetail, status_code=201)
def create_playlist(data: PlaylistCreate, user: CurrentUser, db: DB):
    return svc.detail(db, svc.create(db, user, data), user)


@router.get("/playlists/{playlist_id}", response_model=PlaylistDetail)
def get_playlist(playlist_id: uuid.UUID, db: DB, user: OptionalUser):
    return svc.detail(db, svc.get_viewable(db, playlist_id, user), user)


@router.patch("/playlists/{playlist_id}", response_model=PlaylistDetail)
def update_playlist(playlist_id: uuid.UUID, data: PlaylistUpdate, user: CurrentUser, db: DB):
    return svc.detail(db, svc.update_playlist(db, playlist_id, user, data), user)


@router.post("/playlists/{playlist_id}/cover", response_model=PlaylistDetail)
def upload_cover(playlist_id: uuid.UUID, user: CurrentUser, db: DB, file: UploadFile = File(...)):
    return svc.detail(db, svc.set_cover(db, playlist_id, user, file), user)


@router.delete("/playlists/{playlist_id}", response_model=Message)
def delete_playlist(playlist_id: uuid.UUID, user: CurrentUser, db: DB):
    svc.delete_playlist(db, playlist_id, user)
    return Message(message="Playlist deleted")


@router.post("/playlists/{playlist_id}/tracks", response_model=PlaylistDetail)
def add_tracks(playlist_id: uuid.UUID, data: AddTracksRequest, user: CurrentUser, db: DB):
    return svc.detail(db, svc.add_tracks(db, playlist_id, user, data.song_ids, data.position), user)


@router.delete("/playlists/{playlist_id}/tracks/{item_id}", response_model=PlaylistDetail)
def remove_track(playlist_id: uuid.UUID, item_id: int, user: CurrentUser, db: DB):
    return svc.detail(db, svc.remove_track(db, playlist_id, user, item_id), user)


@router.patch("/playlists/{playlist_id}/tracks/reorder", response_model=PlaylistDetail)
def reorder_tracks(playlist_id: uuid.UUID, data: ReorderRequest, user: CurrentUser, db: DB):
    return svc.detail(db, svc.reorder(db, playlist_id, user, data.from_index, data.to_index), user)


@router.post("/playlists/{playlist_id}/invite", response_model=PlaylistDetail,
             summary="Regenerate the collaboration invite code (owner only)")
def regenerate_invite(playlist_id: uuid.UUID, user: CurrentUser, db: DB):
    return svc.detail(db, svc.regenerate_invite(db, playlist_id, user), user)


@router.post("/playlists/{playlist_id}/join", response_model=PlaylistDetail)
def join_playlist(playlist_id: uuid.UUID, data: JoinPlaylistRequest, user: CurrentUser, db: DB):
    return svc.detail(db, svc.join(db, playlist_id, user, data.code), user)


@router.delete("/playlists/{playlist_id}/collaborators/{user_id}", response_model=Message)
def remove_collaborator(playlist_id: uuid.UUID, user_id: uuid.UUID, user: CurrentUser, db: DB):
    svc.remove_collaborator(db, playlist_id, user, user_id)
    return Message(message="Collaborator removed")
