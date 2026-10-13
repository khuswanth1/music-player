import uuid
from datetime import datetime

from sqlalchemy import func, or_, select, update
from sqlalchemy.orm import Session

from app.models import PasswordResetToken, RefreshToken, User


def get_by_email(db: Session, email: str) -> User | None:
    return db.scalar(select(User).where(User.email == email.lower()))


def get_by_google_sub(db: Session, sub: str) -> User | None:
    return db.scalar(select(User).where(User.google_sub == sub))


def get_refresh_token(db: Session, token_hash: str, *, for_update: bool = False) -> RefreshToken | None:
    stmt = select(RefreshToken).where(RefreshToken.token_hash == token_hash)
    if for_update:
        stmt = stmt.with_for_update()
    return db.scalar(stmt)


def revoke_family(db: Session, family_id: uuid.UUID, now: datetime) -> None:
    db.execute(update(RefreshToken)
               .where(RefreshToken.family_id == family_id, RefreshToken.revoked_at.is_(None))
               .values(revoked_at=now))


def revoke_all_for_user(db: Session, user_id: uuid.UUID, now: datetime) -> None:
    db.execute(update(RefreshToken)
               .where(RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None))
               .values(revoked_at=now))


def invalidate_reset_tokens(db: Session, user_id: uuid.UUID, now: datetime) -> None:
    db.execute(update(PasswordResetToken)
               .where(PasswordResetToken.user_id == user_id, PasswordResetToken.used_at.is_(None))
               .values(used_at=now))


def get_reset_token(db: Session, token_hash: str) -> PasswordResetToken | None:
    return db.scalar(select(PasswordResetToken).where(PasswordResetToken.token_hash == token_hash).with_for_update())


def search(db: Session, q: str | None, role_id: int | None, offset: int, limit: int) -> tuple[list[User], int]:
    stmt = select(User)
    if q:
        like = f"%{q.lower()}%"
        stmt = stmt.where(or_(func.lower(User.email).like(like), func.lower(User.display_name).like(like)))
    if role_id:
        stmt = stmt.where(User.role_id == role_id)
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    items = db.scalars(stmt.order_by(User.created_at.desc()).offset(offset).limit(limit)).all()
    return list(items), total
