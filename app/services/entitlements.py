"""Server-side entitlement checks. The frontend only mirrors these; it never decides access."""

import uuid
from datetime import timedelta

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import PaymentRequired
from app.core.security import utcnow
from app.models import ENTITLED_STATUSES, Subscription, User

# Covers webhook delivery delays around renewal time.
RENEWAL_GRACE = timedelta(days=1)


def active_subscription(db: Session, user_id: uuid.UUID) -> Subscription | None:
    cutoff = utcnow() - RENEWAL_GRACE
    return db.scalar(
        select(Subscription)
        .where(Subscription.user_id == user_id,
               Subscription.status.in_(ENTITLED_STATUSES),
               or_(Subscription.current_period_end.is_(None), Subscription.current_period_end > cutoff))
        .order_by(Subscription.current_period_end.desc().nulls_first())
        .limit(1)
    )


def is_premium(db: Session, user: User) -> bool:
    return active_subscription(db, user.id) is not None


def require_premium(db: Session, user: User, feature: str) -> None:
    if not is_premium(db, user):
        raise PaymentRequired(f"{feature} requires Premium", details={"feature": feature})


def playlist_limit(db: Session, user: User) -> int | None:
    return None if is_premium(db, user) else get_settings().free_playlist_limit
