import uuid
from typing import Annotated

from fastapi import Depends, Query
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from app.core.errors import Forbidden, Unauthorized
from app.core.permissions import Perm, has_permission
from app.core.security import decode_token
from app.db.session import get_db
from app.models import User

# tokenUrl powers the "Authorize" button in Swagger UI.
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/token", auto_error=False)

DB = Annotated[Session, Depends(get_db)]


def _load_user(db: Session, token: str) -> User:
    payload = decode_token(token, "access")
    try:
        user_id = uuid.UUID(payload["sub"])
    except ValueError as exc:
        raise Unauthorized("Invalid token", code="invalid_token") from exc
    user = db.get(User, user_id)
    if user is None or not user.is_active:
        raise Unauthorized("Account is unavailable", code="account_unavailable")
    return user


def get_current_user(db: DB, token: Annotated[str | None, Depends(oauth2_scheme)]) -> User:
    if not token:
        raise Unauthorized("Authentication required")
    return _load_user(db, token)


def get_optional_user(db: DB, token: Annotated[str | None, Depends(oauth2_scheme)]) -> User | None:
    if not token:
        return None
    return _load_user(db, token)


CurrentUser = Annotated[User, Depends(get_current_user)]
OptionalUser = Annotated[User | None, Depends(get_optional_user)]


def require_permission(perm: Perm):
    def dependency(user: CurrentUser) -> User:
        if not has_permission(user.role_name, perm):
            raise Forbidden("You don't have permission to perform this action")
        return user

    return dependency


class Pagination:
    def __init__(self, page: int = Query(1, ge=1, le=10_000),
                 page_size: int = Query(20, ge=1, le=100)) -> None:
        self.page = page
        self.page_size = page_size

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.page_size


PageParams = Annotated[Pagination, Depends()]
