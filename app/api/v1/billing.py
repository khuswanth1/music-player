import uuid
from datetime import datetime, timedelta

import httpx
from fastapi import APIRouter, BackgroundTasks, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from starlette.concurrency import run_in_threadpool

from app.api.deps import DB, CurrentUser
from app.billing import webhooks
from app.billing.plans import PLANS
from app.billing.providers import DevProvider, get_provider
from app.core.config import get_settings
from app.core.errors import AppError, Conflict, NotFound
from app.core.security import utcnow
from app.db.session import SessionLocal
from app.models import Payment, PaymentStatus, Plan, Subscription, SubscriptionStatus
from app.realtime.hub import hub
from app.services.entitlements import active_subscription

router = APIRouter(tags=["billing"])


class PlanOut(BaseModel):
    id: Plan
    name: str
    amount_cents: int
    currency: str
    interval: str
    features: list[str]


class SubscriptionOut(BaseModel):
    id: str
    plan: Plan
    status: SubscriptionStatus
    provider: str
    current_period_end: datetime | None
    cancel_at_period_end: bool


class BillingStatus(BaseModel):
    is_premium: bool
    provider: str
    subscription: SubscriptionOut | None


class CheckoutRequest(BaseModel):
    plan: Plan


class RedirectOut(BaseModel):
    url: str


class DevCompleteRequest(BaseModel):
    session: str


class PaymentOut(BaseModel):
    id: str
    amount_cents: int
    currency: str
    status: PaymentStatus
    description: str
    created_at: datetime


def _status(db, user) -> BillingStatus:
    sub = active_subscription(db, user.id)
    return BillingStatus(
        is_premium=sub is not None, provider=get_provider().name,
        subscription=SubscriptionOut(id=str(sub.id), plan=sub.plan, status=sub.status, provider=sub.provider,
                                     current_period_end=sub.current_period_end,
                                     cancel_at_period_end=sub.cancel_at_period_end) if sub else None,
    )


@router.get("/billing/plans", response_model=list[PlanOut])
def plans():
    return [PlanOut(id=p.id, name=p.name, amount_cents=p.amount_cents, currency=p.currency,
                    interval=p.interval, features=list(p.features)) for p in PLANS.values()]


@router.get("/billing/subscription", response_model=BillingStatus)
def subscription(user: CurrentUser, db: DB):
    return _status(db, user)


@router.post("/billing/checkout", response_model=RedirectOut)
def checkout(data: CheckoutRequest, user: CurrentUser, db: DB):
    if active_subscription(db, user.id):
        raise Conflict("You already have Premium", code="already_premium")
    return RedirectOut(url=get_provider().create_checkout(db, user, data.plan))


@router.post("/billing/portal", response_model=RedirectOut)
def portal(user: CurrentUser, db: DB):
    return RedirectOut(url=get_provider().create_portal(db, user))


def _change_cancellation(db, user, cancel: bool) -> BillingStatus:
    sub = active_subscription(db, user.id)
    if sub is None or sub.provider == "manual":
        raise NotFound("No active subscription to change")
    if sub.cancel_at_period_end == cancel:
        return _status(db, user)
    get_provider().set_cancel_at_period_end(db, sub, cancel)
    db.expire_all()
    return _status(db, user)


@router.post("/billing/cancel", response_model=BillingStatus, summary="Cancel at the end of the current period")
def cancel(user: CurrentUser, db: DB):
    return _change_cancellation(db, user, True)


@router.post("/billing/resume", response_model=BillingStatus, summary="Undo a pending cancellation")
def resume(user: CurrentUser, db: DB):
    return _change_cancellation(db, user, False)


@router.get("/billing/payments", response_model=list[PaymentOut])
def payments(user: CurrentUser, db: DB):
    rows = db.scalars(select(Payment).where(Payment.user_id == user.id).order_by(Payment.created_at.desc())).all()
    return [PaymentOut(id=str(p.id), amount_cents=p.amount_cents, currency=p.currency, status=p.status,
                       description=p.description, created_at=p.created_at) for p in rows]


@router.post("/billing/dev/complete", response_model=BillingStatus,
             summary="Development provider only: complete a test checkout (no real payment)")
def dev_complete(data: DevCompleteRequest, user: CurrentUser, db: DB):
    provider = get_provider()
    if not isinstance(provider, DevProvider):
        raise NotFound("Not available")
    if active_subscription(db, user.id):
        raise Conflict("You already have Premium", code="already_premium")
    for payload, signature in provider.complete_checkout(db, user, data.session):
        webhooks.ingest_and_process(db, payload, signature)
    db.expire_all()
    return _status(db, user)


class RazorpayVerifyRequest(BaseModel):
    payment_id: str
    payment_link_id: str | None = None


@router.post("/billing/razorpay/verify", response_model=BillingStatus, summary="Verify and activate Razorpay payment")
def razorpay_verify(data: RazorpayVerifyRequest, user: CurrentUser, db: DB):
    settings = get_settings()
    if not settings.razorpay_key_id or not settings.razorpay_key_secret:
        raise NotFound("Razorpay is not configured")

    with httpx.Client(timeout=10) as client:
        res = client.get(
            f"https://api.razorpay.com/v1/payments/{data.payment_id}",
            auth=(settings.razorpay_key_id, settings.razorpay_key_secret),
        )
        if res.status_code != 200:
            raise AppError("Payment verification failed", code="payment_verification_failed")
        pdata = res.json()

    if pdata.get("status") not in ("captured", "authorized"):
        raise AppError("Payment is not completed", code="payment_not_completed")

    notes = pdata.get("notes") or {}
    plan_name = notes.get("plan", Plan.premium_monthly.value)
    plan = Plan(plan_name) if plan_name in Plan.__members__ else Plan.premium_monthly

    amount = pdata.get("amount", 19900)
    currency = (pdata.get("currency") or "INR").lower()
    now = utcnow()
    period = timedelta(days=365 if plan == Plan.premium_yearly else 30)

    sub_id = data.payment_link_id or f"sub_rzp_{data.payment_id}"
    values = {
        "user_id": user.id,
        "plan": plan,
        "status": SubscriptionStatus.active,
        "provider": "razorpay",
        "current_period_start": now,
        "current_period_end": now + period,
        "cancel_at_period_end": False,
        "canceled_at": None,
        "updated_at": now,
    }
    stmt = insert(Subscription).values(id=uuid.uuid4(), provider_subscription_id=sub_id, **values)
    db.execute(stmt.on_conflict_do_update(index_elements=[Subscription.provider_subscription_id], set_=values))
    db.flush()

    sub = db.scalar(select(Subscription).where(Subscription.provider_subscription_id == sub_id))

    payment_values = {
        "user_id": user.id,
        "subscription_id": sub.id if sub else None,
        "provider": "razorpay",
        "provider_payment_id": data.payment_id,
        "amount_cents": amount,
        "currency": currency,
        "status": PaymentStatus.succeeded,
        "description": f"Wavely {plan.value} (Razorpay UPI)",
    }
    pstmt = insert(Payment).values(id=uuid.uuid4(), **payment_values)
    db.execute(pstmt.on_conflict_do_update(index_elements=[Payment.provider_payment_id], set_={"status": PaymentStatus.succeeded}))
    db.commit()

    hub.publish(f"user:{user.id}", {"type": "subscription.updated", "status": SubscriptionStatus.active.value})
    db.expire_all()
    return _status(db, user)


@router.post("/webhooks/stripe", tags=["webhooks"], summary="Stripe webhook endpoint (signature verified)")
async def stripe_webhook(request: Request, background: BackgroundTasks):
    payload = await request.body()  # raw bytes: the signature covers the exact body
    signature = request.headers.get("stripe-signature")

    def _ingest():
        with SessionLocal() as db:
            event, created = webhooks.ingest(db, payload, signature)
            return event.id, created, event.status

    event_pk, created, status = await run_in_threadpool(_ingest)
    if created:
        background.add_task(webhooks.process_event, event_pk)
    return {"received": True, "duplicate": not created, "status": status.value}
