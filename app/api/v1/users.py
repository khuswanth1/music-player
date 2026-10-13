import uuid

from fastapi import APIRouter, File, Request, Response, UploadFile
from sqlalchemy import select

from app.api.deps import DB, CurrentUser
from app.api.v1.auth import clear_refresh_cookie, token_response
from app.core.errors import NotFound
from app.core.rate_limit import client_ip
from app.models import Playlist, User
from app.schemas.common import Message
from app.schemas.playlist import PlaylistSummary
from app.schemas.user import ChangePasswordRequest, TokenResponse, UpdateProfileRequest, UserMe, UserPublic
from app.services import auth as auth_service
from app.services import users as user_service
from app.services.playlists import summarize_many

router = APIRouter(tags=["users"])


@router.get("/me", response_model=UserMe)
def me(user: CurrentUser, db: DB):
    return user_service.to_me(db, user)


@router.patch("/me", response_model=UserMe)
def update_me(data: UpdateProfileRequest, user: CurrentUser, db: DB):
    return user_service.to_me(db, user_service.update_profile(db, user, data))


@router.post("/me/password", response_model=TokenResponse,
             summary="Change password; signs out other sessions and returns a fresh one")
def change_password(data: ChangePasswordRequest, user: CurrentUser, request: Request, response: Response, db: DB):
    user_service.change_password(db, user, data)
    session = auth_service.issue_session(db, user, ip=client_ip(request), user_agent=request.headers.get("user-agent"))
    db.commit()
    return token_response(db, response, session)


@router.post("/me/avatar", response_model=UserMe)
def upload_avatar(user: CurrentUser, db: DB, file: UploadFile = File(...)):
    return user_service.to_me(db, user_service.set_avatar(db, user, file))


@router.delete("/me", response_model=Message)
def delete_me(user: CurrentUser, response: Response, db: DB):
    db.delete(user)
    db.commit()
    clear_refresh_cookie(response)
    return Message(message="Account deleted")


@router.get("/users/{user_id}", response_model=UserPublic)
def get_user(user_id: uuid.UUID, db: DB):
    user = db.get(User, user_id)
    if user is None or not user.is_active:
        raise NotFound("User not found")
    return user


@router.get("/users/{user_id}/playlists", response_model=list[PlaylistSummary])
def user_public_playlists(user_id: uuid.UUID, db: DB):
    playlists = db.scalars(select(Playlist).where(Playlist.owner_id == user_id, Playlist.is_public.is_(True))
                           .order_by(Playlist.updated_at.desc())).all()
    return summarize_many(db, list(playlists))
