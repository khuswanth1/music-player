import json
import time
import uuid

from sqlalchemy import select

from app.billing import webhooks
from app.billing.signature import sign_payload
from app.models import Payment, Subscription, WebhookEvent, WebhookStatus

SECRET = "whsec_test_secret"


def _event(event_type: str, obj: dict, event_id: str | None = None) -> bytes:
    return json.dumps({"id": event_id or f"evt_{uuid.uuid4().hex}", "type": event_type, "created": int(time.time()),
                       "data": {"object": obj}}).encode()


def _post(client, payload: bytes, secret: str = SECRET, timestamp: int | None = None):
    return client.post("/api/v1/webhooks/stripe", content=payload,
                       headers={"Stripe-Signature": sign_payload(payload, secret, timestamp),
                                "Content-Type": "application/json"})


def _subscription_obj(user_id, sub_id="sub_123", status="active", **extra):
    now = int(time.time())
    return {"id": sub_id, "customer": "cus_abc", "status": status, "metadata": {"user_id": str(user_id),
            "plan": "premium_monthly"}, "cancel_at_period_end": False, "current_period_start": now,
            "current_period_end": now + 30 * 86400, "items": {"data": [{"price": {"id": "price_x"}}]}, **extra}


def test_dev_checkout_grants_premium(client, factory, db):
    user = factory.user()
    h = factory.headers(user)
    plans = client.get("/api/v1/billing/plans").json()
    assert {p["id"] for p in plans} == {"premium_monthly", "premium_yearly"}
    assert client.get("/api/v1/billing/subscription", headers=h).json()["is_premium"] is False

    url = client.post("/api/v1/billing/checkout", json={"plan": "premium_yearly"}, headers=h).json()["url"]
    assert "/checkout/dev?session=" in url
    session = url.split("session=")[1]
    other = factory.user()
    assert client.post("/api/v1/billing/dev/complete", json={"session": session},
                       headers=factory.headers(other)).status_code == 404  # bound to the buyer

    status = client.post("/api/v1/billing/dev/complete", json={"session": session}, headers=h).json()
    assert status["is_premium"] and status["subscription"]["plan"] == "premium_yearly"
    assert client.get("/api/v1/me", headers=h).json()["is_premium"] is True
    payments = client.get("/api/v1/billing/payments", headers=h).json()
    assert payments[0]["amount_cents"] == 9999 and payments[0]["status"] == "succeeded"
    # All three events went through signature verification and were stored.
    assert {e.event_type for e in db.scalars(select(WebhookEvent))} == {
        "checkout.session.completed", "customer.subscription.created", "invoice.paid"}
    assert client.post("/api/v1/billing/checkout", json={"plan": "premium_monthly"}, headers=h).status_code == 409


def test_cancel_and_resume(client, factory):
    user = factory.user()
    h = factory.headers(user)
    session = client.post("/api/v1/billing/checkout", json={"plan": "premium_monthly"}, headers=h).json()["url"].split("=")[1]
    client.post("/api/v1/billing/dev/complete", json={"session": session}, headers=h)
    cancelled = client.post("/api/v1/billing/cancel", headers=h).json()
    assert cancelled["is_premium"] and cancelled["subscription"]["cancel_at_period_end"] is True
    resumed = client.post("/api/v1/billing/resume", headers=h).json()
    assert resumed["subscription"]["cancel_at_period_end"] is False


def test_webhook_rejects_bad_signatures(client, factory, db):
    user = factory.user()
    payload = _event("customer.subscription.created", _subscription_obj(user.id))
    assert _post(client, payload, secret="whsec_wrong").status_code == 400
    assert _post(client, payload, timestamp=int(time.time()) - 3600).status_code == 400
    missing = client.post("/api/v1/webhooks/stripe", content=payload)
    assert missing.status_code == 400 and missing.json()["error"]["code"] == "invalid_signature"
    assert db.scalars(select(WebhookEvent)).all() == []  # nothing stored before verification


def test_webhook_processing_and_duplicates(client, factory, db):
    user = factory.user()
    payload = _event("customer.subscription.created", _subscription_obj(user.id), event_id="evt_dup")
    first = _post(client, payload)
    assert first.status_code == 200 and first.json()["duplicate"] is False
    second = _post(client, payload)  # provider retry of the same event
    assert second.status_code == 200 and second.json()["duplicate"] is True
    assert len(db.scalars(select(WebhookEvent)).all()) == 1
    event = db.scalar(select(WebhookEvent))
    assert event.status == WebhookStatus.processed and event.attempts == 1
    sub = db.scalar(select(Subscription))
    assert sub.user_id == user.id and sub.status.value == "active"
    assert client.get("/api/v1/me", headers=factory.headers(user)).json()["is_premium"] is True

    # Later status changes update the same row; deletion ends the entitlement.
    _post(client, _event("customer.subscription.updated", _subscription_obj(user.id, status="past_due")))
    db.expire_all()
    assert db.scalar(select(Subscription)).status.value == "past_due"
    assert client.get("/api/v1/me", headers=factory.headers(user)).json()["is_premium"] is True  # grace while retrying
    _post(client, _event("customer.subscription.deleted", _subscription_obj(user.id, status="canceled")))
    assert client.get("/api/v1/me", headers=factory.headers(user)).json()["is_premium"] is False
    assert len(db.scalars(select(Subscription)).all()) == 1


def test_invoice_events_record_payments(client, factory, db):
    user = factory.user()
    _post(client, _event("customer.subscription.created", _subscription_obj(user.id)))
    invoice = {"id": "in_1", "customer": "cus_abc", "subscription": "sub_123", "amount_paid": 999,
               "amount_due": 999, "currency": "usd", "metadata": {"user_id": str(user.id)}}
    _post(client, _event("invoice.payment_failed", invoice))
    db.expire_all()
    assert db.scalar(select(Payment)).status.value == "failed"
    _post(client, _event("invoice.paid", invoice))
    db.expire_all()
    payment = db.scalar(select(Payment))
    assert payment.status.value == "succeeded" and payment.subscription_id is not None
    # Customer id is linked to the user, so later events without metadata still resolve.
    _post(client, _event("invoice.paid", {"id": "in_2", "customer": "cus_abc", "amount_paid": 999, "currency": "usd"}))
    assert len(db.scalars(select(Payment)).all()) == 2


def test_unknown_events_are_ignored(client, db):
    res = _post(client, _event("charge.refund.updated", {"id": "x"}))
    assert res.status_code == 200
    db.expire_all()
    assert db.scalar(select(WebhookEvent)).status == WebhookStatus.ignored


def test_failed_events_are_retried(client, factory, db, monkeypatch):
    # An event for a customer we don't know yet fails, is scheduled for retry, and succeeds once resolvable.
    payload = _event("invoice.paid", {"id": "in_9", "customer": "cus_later", "amount_paid": 500, "currency": "usd"})
    _post(client, payload)
    db.expire_all()
    event = db.scalar(select(WebhookEvent))
    assert event.status == WebhookStatus.failed and event.attempts == 1
    assert event.next_retry_at is not None and "cus_later" in event.last_error

    user = factory.user()
    from app.models import User

    db.get(User, user.id).billing_customer_id = "cus_later"
    event.next_retry_at = event.received_at  # make it due now
    db.commit()
    assert webhooks.retry_due_events() == 1
    db.expire_all()
    event = db.scalar(select(WebhookEvent))
    assert event.status == WebhookStatus.processed and event.attempts == 2
    # Processed events are not re-run by a duplicate delivery.
    assert _post(client, payload).json() == {"received": True, "duplicate": True, "status": "processed"}


def test_retries_stop_after_max_attempts(client, db, settings, monkeypatch):
    monkeypatch.setattr(settings, "webhook_max_attempts", 2)
    _post(client, _event("invoice.paid", {"id": "in_x", "customer": "cus_nobody", "amount_paid": 1, "currency": "usd"}))
    db.expire_all()
    event = db.scalar(select(WebhookEvent))
    webhooks.process_event(event.id)
    db.expire_all()
    event = db.scalar(select(WebhookEvent))
    assert event.attempts == 2 and event.status == WebhookStatus.failed and event.next_retry_at is None
