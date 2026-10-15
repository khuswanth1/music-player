from fastapi import UploadFile
from sqlalchemy.orm import Session

from app.core.errors import Conflict, Unauthorized
from app.core.permissions import permissions_for
from app.core.security import hash_password, utcnow, verify_password
from app.models import User
from app.repositories import users as users_repo
from app.schemas.user import ChangePasswordRequest, UiPrefs, UpdateProfileRequest, UserMe
from app.services.entitlements import is_premium
from app.storage.backends import get_storage, media_url
from app.storage.validation import validate_image


def to_me(db: Session, user: User) -> UserMe:
    return UserMe(
        id=user.id, email=user.email, display_name=user.display_name, avatar_url=user.avatar_url,
        role=user.role_name, permissions=permissions_for(user.role_name), is_premium=is_premium(db, user),
        has_password=user.password_hash is not None, google_linked=user.google_sub is not None,
        created_at=user.created_at, preferred_languages=list(user.preferred_languages or []),
        preferred_genres=list(user.preferred_genres or []), onboarded=user.onboarded_at is not None,
        ui_prefs=UiPrefs.model_validate(user.ui_prefs or {}),
        date_of_birth=user.date_of_birth, gender=user.gender, marketing_emails=user.marketing_emails,
    )


def update_profile(db: Session, user: User, data: UpdateProfileRequest) -> User:
    if data.display_name is not None:
        user.display_name = data.display_name.strip()
    if data.email is not None and data.email.lower() != user.email:
        if users_repo.get_by_email(db, data.email):
            raise Conflict("That email is already in use", code="email_taken")
        user.email = data.email.lower()
    db.commit()
    return user


def change_password(db: Session, user: User, data: ChangePasswordRequest) -> None:
    if user.password_hash is not None and not verify_password(data.current_password or "", user.password_hash):
        raise Unauthorized("Current password is incorrect", code="invalid_credentials")
    user.password_hash = hash_password(data.new_password)
    # Other sessions are signed out; the caller re-issues a session for this device.
    users_repo.revoke_all_for_user(db, user.id, utcnow())
    db.commit()


def set_avatar(db: Session, user: User, upload: UploadFile) -> User:
    image = validate_image(upload)
    key = image.key("images/avatars")
    storage = get_storage()
    with image.fileobj:
        storage.save(key, image.fileobj, image.content_type)
    old = user.avatar_url
    user.avatar_url = media_url(key)
    db.commit()
    if old and old.startswith("/api/v1/media/images/avatars/"):
        storage.delete(old.removeprefix("/api/v1/media/"))
    return user
