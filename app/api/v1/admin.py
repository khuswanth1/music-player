import uuid
from datetime import date, datetime, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import Date, cast, func, or_, select
from sqlalchemy.orm import Session

from app.api.deps import DB, PageParams, require_permission
from app.billing import webhooks
from app.core.errors import AppError, Forbidden, NotFound
from app.core.permissions import ROLE_IDS, Perm, RoleName
from app.core.security import utcnow
from app.models import (
    ENTITLED_STATUSES,
    Album,
    Artist,
    ListeningHistory,
    Payment,
    PaymentStatus,
    Plan,
    Playlist,
    Song,
    Subscription,
    SubscriptionStatus,
    User,
    WebhookEvent,
    WebhookStatus,
)
from app.repositories import users as users_repo
from app.repositories.catalog import paginate
from app.schemas.common import Message, Page
from app.schemas.playlist import PlaylistSummary
from app.services.playlists import summarize_many

router = APIRouter(prefix="/admin", tags=["admin"])

Analyst = Annotated[User, Depends(require_permission(Perm.analytics_view))]
UserAdmin = Annotated[User, Depends(require_permission(Perm.users_manage))]
BillingAdmin = Annotated[User, Depends(require_permission(Perm.billing_manage))]
Moderator = Annotated[User, Depends(require_permission(Perm.playlists_moderate))]
WebhookAdmin = Annotated[User, Depends(require_permission(Perm.webhooks_manage))]


def _premium_ids(db: Session, user_ids: list[uuid.UUID]) -> set[uuid.UUID]:
    if not user_ids:
        return set()
    cutoff = utcnow() - timedelta(days=1)
    return set(db.scalars(select(Subscription.user_id).where(
        Subscription.user_id.in_(user_ids), Subscription.status.in_(ENTITLED_STATUSES),
        or_(Subscription.current_period_end.is_(None), Subscription.current_period_end > cutoff))))


# --- dashboard -----------------------------------------------------------------------------

class Stats(BaseModel):
    users: int
    active_users_30d: int
    premium_users: int
    artists: int
    albums: int
    songs: int
    playlists: int
    plays_total: int
    plays_24h: int
    revenue_30d_cents: int
    failed_webhooks: int


@router.get("/stats", response_model=Stats)
def stats(_: Analyst, db: DB):
    now = utcnow()
    count = lambda stmt: db.scalar(stmt) or 0  # noqa: E731
    return Stats(
        users=count(select(func.count()).select_from(User)),
        active_users_30d=count(select(func.count(func.distinct(ListeningHistory.user_id)))
                               .where(ListeningHistory.played_at >= now - timedelta(days=30))),
        premium_users=count(select(func.count(func.distinct(Subscription.user_id))).where(
            Subscription.status.in_(ENTITLED_STATUSES),
            or_(Subscription.current_period_end.is_(None), Subscription.current_period_end > now - timedelta(days=1)))),
        artists=count(select(func.count()).select_from(Artist)),
        albums=count(select(func.count()).select_from(Album)),
        songs=count(select(func.count()).select_from(Song)),
        playlists=count(select(func.count()).select_from(Playlist)),
        plays_total=count(select(func.count()).select_from(ListeningHistory)),
        plays_24h=count(select(func.count()).where(ListeningHistory.played_at >= now - timedelta(days=1))),
        revenue_30d_cents=count(select(func.coalesce(func.sum(Payment.amount_cents), 0)).where(
            Payment.status == PaymentStatus.succeeded, Payment.created_at >= now - timedelta(days=30))),
        failed_webhooks=count(select(func.count()).where(WebhookEvent.status == WebhookStatus.failed)),
    )


class SeriesPoint(BaseModel):
    date: date
    value: int


class RankedItem(BaseModel):
    id: str
    name: str
    subtitle: str | None = None
    value: int


class Analytics(BaseModel):
    days: int
    plays: list[SeriesPoint]
    signups: list[SeriesPoint]
    revenue_cents: list[SeriesPoint]
    top_songs: list[RankedItem]
    top_artists: list[RankedItem]
    plan_breakdown: dict[str, int]


def _daily(db: Session, column, days: int, *, where=(), value=None) -> list[SeriesPoint]:
    start = (utcnow() - timedelta(days=days - 1)).date()
    day = cast(column, Date)
    rows = dict(db.execute(select(day, value if value is not None else func.count())
                           .where(column >= start, *where).group_by(day)).all())
    return [SeriesPoint(date=start + timedelta(days=i), value=int(rows.get(start + timedelta(days=i), 0)))
            for i in range(days)]


@router.get("/analytics", response_model=Analytics)
def analytics(_: Analyst, db: DB, days: int = Query(30, ge=7, le=365)):
    since = utcnow() - timedelta(days=days)
    plays = func.count(ListeningHistory.id).label("plays")
    top_songs = db.execute(select(Song.id, Song.title, Artist.name, plays)
                           .join(ListeningHistory, ListeningHistory.song_id == Song.id)
                           .join(Artist, Artist.id == Song.artist_id)
                           .where(ListeningHistory.played_at >= since)
                           .group_by(Song.id, Song.title, Artist.name).order_by(plays.desc()).limit(10)).all()
    top_artists = db.execute(select(Artist.id, Artist.name, plays)
                             .join(Song, Song.artist_id == Artist.id)
                             .join(ListeningHistory, ListeningHistory.song_id == Song.id)
                             .where(ListeningHistory.played_at >= since)
                             .group_by(Artist.id, Artist.name).order_by(plays.desc()).limit(10)).all()
    breakdown = dict(db.execute(select(Subscription.plan, func.count()).where(Subscription.status.in_(ENTITLED_STATUSES))
                                .group_by(Subscription.plan)).all())
    return Analytics(
        days=days,
        plays=_daily(db, ListeningHistory.played_at, days),
        signups=_daily(db, User.created_at, days),
        revenue_cents=_daily(db, Payment.created_at, days, where=(Payment.status == PaymentStatus.succeeded,),
                             value=func.sum(Payment.amount_cents)),
        top_songs=[RankedItem(id=str(i), name=t, subtitle=a, value=n) for i, t, a, n in top_songs],
        top_artists=[RankedItem(id=str(i), name=a, value=n) for i, a, n in top_artists],
        plan_breakdown={plan.value: int(breakdown.get(plan, 0)) for plan in Plan},
    )


# --- users ---------------------------------------------------------------------------------

class AdminUserOut(BaseModel):
    id: uuid.UUID
    email: str
    display_name: str
    role: str
    is_active: bool
    is_premium: bool
    created_at: datetime
    last_login_at: datetime | None


class AdminUserUpdate(BaseModel):
    role: RoleName | None = None
    is_active: bool | None = None


def _admin_user(user: User, premium: set[uuid.UUID]) -> AdminUserOut:
    return AdminUserOut(id=user.id, email=user.email, display_name=user.display_name, role=user.role_name,
                        is_active=user.is_active, is_premium=user.id in premium, created_at=user.created_at,
                        last_login_at=user.last_login_at)


@router.get("/users", response_model=Page[AdminUserOut])
def list_users(_: UserAdmin, db: DB, page: PageParams, q: str | None = None, role: RoleName | None = None):
    users, total = users_repo.search(db, q, ROLE_IDS[role] if role else None, page.offset, page.page_size)
    premium = _premium_ids(db, [u.id for u in users])
    return Page.build([_admin_user(u, premium) for u in users], total, page.page, page.page_size)


@router.patch("/users/{user_id}", response_model=AdminUserOut)
def update_user(user_id: uuid.UUID, data: AdminUserUpdate, admin: UserAdmin, db: DB):
    user = db.get(User, user_id)
    if user is None:
        raise NotFound("User not found")
    if user.id == admin.id and (data.is_active is False or (data.role and data.role != RoleName.admin)):
        raise Forbidden("You can't demote or disable your own account")
    if data.role is not None:
        user.role_id = ROLE_IDS[data.role]
    if data.is_active is not None:
        user.is_active = data.is_active
        if not data.is_active:
            users_repo.revoke_all_for_user(db, user.id, utcnow())
    db.commit()
    db.refresh(user, ["role"])
    return _admin_user(user, _premium_ids(db, [user.id]))


@router.delete("/users/{user_id}", response_model=Message)
def delete_user(user_id: uuid.UUID, admin: UserAdmin, db: DB):
    if user_id == admin.id:
        raise Forbidden("You can't delete your own account here")
    user = db.get(User, user_id)
    if user is None:
        raise NotFound("User not found")
    db.delete(user)
    db.commit()
    return Message(message="User deleted")


# --- playlists (moderation) ----------------------------------------------------------------

@router.get("/playlists", response_model=Page[PlaylistSummary])
def list_playlists(_: Moderator, db: DB, page: PageParams, q: str | None = None):
    stmt = select(Playlist).order_by(Playlist.updated_at.desc())
    if q:
        stmt = stmt.where(Playlist.name.ilike(f"%{q}%"))
    items, total = paginate(db, stmt, page.offset, page.page_size)
    return Page.build(summarize_many(db, items), total, page.page, page.page_size)


# --- subscriptions & payments --------------------------------------------------------------

class AdminSubscriptionOut(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    user_email: str
    plan: Plan
    status: SubscriptionStatus
    provider: str
    provider_subscription_id: str | None
    current_period_end: datetime | None
    cancel_at_period_end: bool
    created_at: datetime


class GrantPremium(BaseModel):
    days: int = Field(default=30, ge=1, le=3650)


@router.get("/subscriptions", response_model=Page[AdminSubscriptionOut])
def list_subscriptions(_: BillingAdmin, db: DB, page: PageParams, status: SubscriptionStatus | None = None):
    stmt = select(Subscription, User.email).join(User, User.id == Subscription.user_id)
    if status:
        stmt = stmt.where(Subscription.status == status)
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.execute(stmt.order_by(Subscription.created_at.desc()).offset(page.offset).limit(page.page_size)).all()
    items = [AdminSubscriptionOut(id=s.id, user_id=s.user_id, user_email=email, plan=s.plan, status=s.status,
                                  provider=s.provider, provider_subscription_id=s.provider_subscription_id,
                                  current_period_end=s.current_period_end, cancel_at_period_end=s.cancel_at_period_end,
                                  created_at=s.created_at) for s, email in rows]
    return Page.build(items, total, page.page, page.page_size)


@router.post("/users/{user_id}/grant-premium", response_model=Message,
             summary="Grant complimentary Premium (manual subscription, no payment)")
def grant_premium(user_id: uuid.UUID, data: GrantPremium, _: BillingAdmin, db: DB):
    if db.get(User, user_id) is None:
        raise NotFound("User not found")
    now = utcnow()
    db.add(Subscription(user_id=user_id, plan=Plan.premium_monthly, status=SubscriptionStatus.active,
                        provider="manual", current_period_start=now, current_period_end=now + timedelta(days=data.days)))
    db.commit()
    return Message(message=f"Premium granted for {data.days} days")


@router.post("/subscriptions/{subscription_id}/revoke", response_model=Message)
def revoke_subscription(subscription_id: uuid.UUID, _: BillingAdmin, db: DB):
    sub = db.get(Subscription, subscription_id)
    if sub is None:
        raise NotFound("Subscription not found")
    if sub.provider != "manual":
        raise AppError("Cancel paid subscriptions in the payment provider's dashboard; "
                       "the webhook will update this record", code="provider_managed")
    sub.status, sub.canceled_at = SubscriptionStatus.canceled, utcnow()
    db.commit()
    return Message(message="Subscription revoked")


class AdminPaymentOut(BaseModel):
    id: uuid.UUID
    user_email: str | None
    provider: str
    provider_payment_id: str
    amount_cents: int
    currency: str
    status: PaymentStatus
    description: str
    created_at: datetime


@router.get("/payments", response_model=Page[AdminPaymentOut])
def list_payments(_: BillingAdmin, db: DB, page: PageParams):
    stmt = select(Payment, User.email).outerjoin(User, User.id == Payment.user_id)
    total = db.scalar(select(func.count()).select_from(Payment)) or 0
    rows = db.execute(stmt.order_by(Payment.created_at.desc()).offset(page.offset).limit(page.page_size)).all()
    items = [AdminPaymentOut(id=p.id, user_email=email, provider=p.provider, provider_payment_id=p.provider_payment_id,
                             amount_cents=p.amount_cents, currency=p.currency, status=p.status,
                             description=p.description, created_at=p.created_at) for p, email in rows]
    return Page.build(items, total, page.page, page.page_size)


# --- webhooks ------------------------------------------------------------------------------

class WebhookEventOut(BaseModel):
    id: uuid.UUID
    provider: str
    event_id: str
    event_type: str
    status: WebhookStatus
    attempts: int
    last_error: str | None
    next_retry_at: datetime | None
    received_at: datetime
    processed_at: datetime | None


class WebhookEventDetail(WebhookEventOut):
    payload: dict[str, Any]


@router.get("/webhooks", response_model=Page[WebhookEventOut])
def list_webhooks(_: WebhookAdmin, db: DB, page: PageParams, status: WebhookStatus | None = None):
    stmt = select(WebhookEvent).order_by(WebhookEvent.received_at.desc())
    if status:
        stmt = stmt.where(WebhookEvent.status == status)
    items, total = paginate(db, stmt, page.offset, page.page_size)
    return Page.build([WebhookEventOut.model_validate(e, from_attributes=True) for e in items],
                      total, page.page, page.page_size)


@router.get("/webhooks/{event_pk}", response_model=WebhookEventDetail)
def get_webhook(event_pk: uuid.UUID, _: WebhookAdmin, db: DB):
    event = db.get(WebhookEvent, event_pk)
    if event is None:
        raise NotFound("Event not found")
    return WebhookEventDetail.model_validate(event, from_attributes=True)


@router.post("/webhooks/{event_pk}/retry", response_model=WebhookEventOut, summary="Re-run processing for an event")
def retry_webhook(event_pk: uuid.UUID, _: WebhookAdmin, db: DB):
    if db.get(WebhookEvent, event_pk) is None:
        raise NotFound("Event not found")
    webhooks.process_event(event_pk, force=True)
    db.expire_all()
    return WebhookEventOut.model_validate(db.get(WebhookEvent, event_pk), from_attributes=True)
