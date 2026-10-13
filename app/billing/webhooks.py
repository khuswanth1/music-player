"""Webhook ingestion and processing (Stripe billing events and signed catalog rights notifications).

1. Verify the signature over the raw body.
2. Insert the event keyed by (provider, event_id); a duplicate delivery is acknowledged and skipped.
3. Acknowledge quickly; process in a background task with its own DB session.
4. Failures are recorded with exponential backoff and retried by the worker, up to a limit.
   Admins can replay any event from the dashboard.
"""

import json
import logging
import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.billing.plans import plan_for_price
from app.billing.signature import InvalidSignature, verify_signature
from app.core.config import get_settings
from app.core.security import utcnow
from app.db.session import SessionLocal
from app.models import (
    Payment,
    PaymentStatus,
    Plan,
    Subscription,
    SubscriptionStatus,
    User,
    WebhookEvent,
    WebhookStatus,
)
from app.realtime.hub import hub

log = logging.getLogger(__name__)
PROVIDER = "stripe"


class UnresolvableEvent(Exception):
    """The event can't be applied (yet), e.g. it references a user we can't identify."""


Handler = Callable[[Session, str, dict], bool]
_HANDLERS: dict[str, Handler] = {}


def register_handler(provider: str, handler: Handler) -> None:
    """Route stored events of `provider` to `handler(db, event_type, payload) -> handled`."""
    _HANDLERS[provider] = handler


def ingest(db: Session, payload: bytes, signature: str | None, *, provider: str = PROVIDER,
           secret: str | None = None) -> tuple[WebhookEvent, bool]:
    settings = get_settings()
    try:
        verify_signature(payload, signature, secret or settings.stripe_webhook_secret, settings.webhook_tolerance_seconds)
    except InvalidSignature as exc:
        log.warning("webhook.signature_invalid", extra={"reason": exc.message})
        raise
    try:
        event = json.loads(payload)
        event_id, event_type = str(event["id"]), str(event["type"])
    except (ValueError, KeyError, TypeError) as exc:
        raise InvalidSignature("Malformed event payload") from exc

    inserted = db.scalar(
        insert(WebhookEvent)
        .values(id=uuid.uuid4(), provider=provider, event_id=event_id, event_type=event_type, payload=event,
                status=WebhookStatus.received, attempts=0)
        .on_conflict_do_nothing(constraint="uq_webhook_events_provider_event")
        .returning(WebhookEvent.id)
    )
    db.commit()
    if inserted is None:
        log.info("webhook.duplicate", extra={"event_id": event_id, "event_type": event_type})
        existing = db.scalar(select(WebhookEvent).where(WebhookEvent.provider == provider,
                                                        WebhookEvent.event_id == event_id))
        return existing, False
    log.info("webhook.received", extra={"event_id": event_id, "event_type": event_type})
    return db.get(WebhookEvent, inserted), True


def ingest_and_process(db: Session, payload: bytes, signature: str) -> WebhookEvent:
    event, _ = ingest(db, payload, signature)
    process_event(event.id)
    db.expire_all()
    return event


def _backoff(attempts: int) -> timedelta:
    return timedelta(seconds=min(30 * 2 ** (attempts - 1), 6 * 3600))


def process_event(event_pk: uuid.UUID, *, force: bool = False) -> WebhookStatus | None:
    """Process one stored event in its own session. Safe to call concurrently: the row is locked
    with SKIP LOCKED, so two workers never handle the same event at once."""
    settings = get_settings()
    with SessionLocal() as db:
        event = db.scalar(select(WebhookEvent).where(WebhookEvent.id == event_pk).with_for_update(skip_locked=True))
        if event is None:
            return None
        if event.status in (WebhookStatus.processed, WebhookStatus.ignored) and not force:
            return event.status
        event.status = WebhookStatus.processing
        event.attempts += 1
        attempt = event.attempts  # re-applied below if the handler fails and we roll back
        db.flush()
        try:
            handler = _HANDLERS.get(event.provider, _dispatch)
            handled = handler(db, event.event_type, event.payload)
            event.status = WebhookStatus.processed if handled else WebhookStatus.ignored
            event.processed_at = utcnow()
            event.last_error = None
            event.next_retry_at = None
            db.commit()
            log.info("webhook.processed", extra={"event_id": event.event_id, "status": event.status.value})
        except Exception as exc:
            db.rollback()
            event = db.get(WebhookEvent, event_pk)
            event.attempts = attempt
            event.status = WebhookStatus.failed
            event.last_error = f"{type(exc).__name__}: {exc}"[:2000]
            event.next_retry_at = utcnow() + _backoff(event.attempts) if event.attempts < settings.webhook_max_attempts else None
            db.commit()
            log.error("webhook.failed", extra={"event_id": event.event_id, "attempts": event.attempts,
                                               "error": event.last_error})
        return event.status


def retry_due_events(limit: int = 50) -> int:
    with SessionLocal() as db:
        ids = db.scalars(select(WebhookEvent.id).where(WebhookEvent.status == WebhookStatus.failed,
                                                       WebhookEvent.next_retry_at.is_not(None),
                                                       WebhookEvent.next_retry_at <= utcnow())
                         .order_by(WebhookEvent.next_retry_at).limit(limit)).all()
    for event_id in ids:
        process_event(event_id)
    return len(ids)


# --- handlers ------------------------------------------------------------------------------

def _ts(value) -> datetime | None:
    return datetime.fromtimestamp(int(value), UTC) if value else None


def _resolve_user(db: Session, obj: dict) -> User:
    user_id = (obj.get("metadata") or {}).get("user_id") or obj.get("client_reference_id")
    if user_id:
        try:
            user = db.get(User, uuid.UUID(user_id))
        except ValueError:
            user = None
        if user:
            return user
    customer = obj.get("customer")
    if customer:
        user = db.scalar(select(User).where(User.billing_customer_id == customer))
        if user:
            return user
    raise UnresolvableEvent(f"No user for customer {customer!r}")


def _link_customer(db: Session, user: User, customer: str | None) -> None:
    if customer and user.billing_customer_id != customer:
        user.billing_customer_id = customer


def _on_checkout_completed(db: Session, obj: dict) -> bool:
    if obj.get("mode") != "subscription":
        return False
    user = _resolve_user(db, obj)
    _link_customer(db, user, obj.get("customer"))
    return True


def _on_subscription(db: Session, obj: dict, *, deleted: bool = False) -> bool:
    from app.billing.providers import get_provider

    provider = get_provider()
    # Prefer the provider's current view of the subscription over the (possibly stale) event payload.
    obj = provider.fetch_subscription(obj["id"]) or obj
    user = _resolve_user(db, obj)
    _link_customer(db, user, obj.get("customer"))

    item = ((obj.get("items") or {}).get("data") or [{}])[0]
    metadata_plan = (obj.get("metadata") or {}).get("plan")
    plan = Plan(metadata_plan) if metadata_plan in Plan.__members__ else plan_for_price((item.get("price") or {}).get("id"))
    status = SubscriptionStatus.canceled if deleted else SubscriptionStatus(obj.get("status", "incomplete"))
    # Newer Stripe API versions report billing periods on the subscription item.
    period_start = obj.get("current_period_start") or item.get("current_period_start")
    period_end = obj.get("current_period_end") or item.get("current_period_end")

    values = {
        "user_id": user.id, "plan": plan or Plan.premium_monthly, "status": status, "provider": provider.name,
        "current_period_start": _ts(period_start), "current_period_end": _ts(period_end),
        "cancel_at_period_end": bool(obj.get("cancel_at_period_end")),
        "canceled_at": _ts(obj.get("canceled_at")) or (utcnow() if deleted else None),
        "updated_at": utcnow(),
    }
    stmt = insert(Subscription).values(id=uuid.uuid4(), provider_subscription_id=obj["id"], **values)
    db.execute(stmt.on_conflict_do_update(index_elements=[Subscription.provider_subscription_id], set_=values))
    db.flush()
    hub.publish(f"user:{user.id}", {"type": "subscription.updated", "status": status.value})
    return True


def _on_invoice(db: Session, obj: dict, status: PaymentStatus) -> bool:
    user = _resolve_user(db, obj)
    sub_ref = obj.get("subscription") or ((obj.get("parent") or {}).get("subscription_details") or {}).get("subscription")
    subscription_id = db.scalar(select(Subscription.id).where(Subscription.provider_subscription_id == sub_ref)) if sub_ref else None
    amount = obj.get("amount_paid") if status == PaymentStatus.succeeded else obj.get("amount_due", 0)
    values = {"user_id": user.id, "subscription_id": subscription_id, "status": status,
              "amount_cents": int(amount or 0), "currency": (obj.get("currency") or "usd")[:3],
              "description": (obj.get("description") or "Wavely Premium")[:255]}
    from app.billing.providers import get_provider

    stmt = insert(Payment).values(id=uuid.uuid4(), provider=get_provider().name, provider_payment_id=obj["id"], **values)
    db.execute(stmt.on_conflict_do_update(index_elements=[Payment.provider_payment_id],
                                          set_={"status": status, "subscription_id": subscription_id}))
    return True


def _dispatch(db: Session, event_type: str, event: dict) -> bool:
    obj = (event.get("data") or {}).get("object") or {}
    match event_type:
        case "checkout.session.completed":
            return _on_checkout_completed(db, obj)
        case "customer.subscription.created" | "customer.subscription.updated":
            return _on_subscription(db, obj)
        case "customer.subscription.deleted":
            return _on_subscription(db, obj, deleted=True)
        case "invoice.paid" | "invoice.payment_succeeded":
            return _on_invoice(db, obj, PaymentStatus.succeeded)
        case "invoice.payment_failed":
            return _on_invoice(db, obj, PaymentStatus.failed)
        case _:
            return False  # not an event we act on; stored as "ignored"


register_handler(PROVIDER, _dispatch)
