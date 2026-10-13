"""Payment providers. Secrets stay server-side; the browser only ever receives redirect URLs."""

import json
import time
import uuid
from abc import ABC, abstractmethod
from datetime import timedelta
from functools import lru_cache

import httpx
from sqlalchemy.orm import Session

from app.billing.plans import PLANS
from app.billing.signature import sign_payload
from app.core.config import get_settings
from app.core.errors import AppError, NotFound
from app.core.security import decode_token, encode_token, utcnow
from app.models import Plan, Subscription, User


class BillingProvider(ABC):
    name: str

    @abstractmethod
    def create_checkout(self, db: Session, user: User, plan: Plan) -> str: ...

    @abstractmethod
    def set_cancel_at_period_end(self, db: Session, subscription: Subscription, cancel: bool) -> None: ...

    def create_portal(self, db: Session, user: User) -> str:
        raise AppError("The billing portal isn't available with this payment provider", code="portal_unavailable")

    def fetch_subscription(self, subscription_id: str) -> dict | None:
        """Latest state from the provider, so out-of-order webhooks can't regress state."""
        return None


class StripeProvider(BillingProvider):
    name = "stripe"

    def __init__(self) -> None:
        import stripe

        settings = get_settings()
        if not settings.stripe_secret_key:
            raise RuntimeError("STRIPE_SECRET_KEY is required when BILLING_PROVIDER=stripe")
        self.client = stripe.StripeClient(settings.stripe_secret_key)

    def _customer(self, db: Session, user: User) -> str:
        if not user.billing_customer_id:
            customer = self.client.v1.customers.create(params={"email": user.email, "name": user.display_name,
                                                               "metadata": {"user_id": str(user.id)}})
            user.billing_customer_id = customer.id
            db.commit()
        return user.billing_customer_id

    def create_checkout(self, db: Session, user: User, plan: Plan) -> str:
        price = PLANS[plan].stripe_price_id
        if not price:
            raise AppError("This plan isn't configured", code="plan_unavailable")
        frontend = get_settings().frontend_url
        metadata = {"user_id": str(user.id), "plan": plan.value}
        session = self.client.v1.checkout.sessions.create(params={
            "mode": "subscription", "customer": self._customer(db, user),
            "line_items": [{"price": price, "quantity": 1}], "client_reference_id": str(user.id),
            "metadata": metadata, "subscription_data": {"metadata": metadata},
            "success_url": f"{frontend}/premium?checkout=success",
            "cancel_url": f"{frontend}/premium?checkout=cancelled",
        })
        return session.url

    def create_portal(self, db: Session, user: User) -> str:
        portal = self.client.v1.billing_portal.sessions.create(params={
            "customer": self._customer(db, user), "return_url": f"{get_settings().frontend_url}/account"})
        return portal.url

    def set_cancel_at_period_end(self, db: Session, subscription: Subscription, cancel: bool) -> None:
        # The resulting customer.subscription.updated webhook updates our database.
        self.client.v1.subscriptions.update(subscription.provider_subscription_id,
                                            params={"cancel_at_period_end": cancel})

    def fetch_subscription(self, subscription_id: str) -> dict | None:
        return self.client.v1.subscriptions.retrieve(subscription_id).to_dict()


class DevProvider(BillingProvider):
    """Local stand-in for Stripe. No money moves. It produces Stripe-format events, signs them with
    STRIPE_WEBHOOK_SECRET, and feeds them through the real webhook ingestion path."""

    name = "dev"

    def create_checkout(self, db: Session, user: User, plan: Plan) -> str:
        token = encode_token({"sub": str(user.id), "plan": plan.value, "typ": "dev_checkout"}, timedelta(minutes=30))
        return f"{get_settings().frontend_url}/checkout/dev?session={token}"

    def complete_checkout(self, db: Session, user: User, session_token: str) -> list[tuple[bytes, str]]:
        claims = decode_token(session_token, "dev_checkout")
        if claims["sub"] != str(user.id):
            raise NotFound("Checkout session not found")
        plan = PLANS[Plan(claims["plan"])]
        now = int(time.time())
        period = 365 * 86400 if plan.interval == "year" else 30 * 86400
        customer = user.billing_customer_id or f"cus_dev_{uuid.uuid4().hex[:14]}"
        sub_id = f"sub_dev_{uuid.uuid4().hex[:14]}"
        metadata = {"user_id": str(user.id), "plan": plan.id.value}
        subscription = {
            "id": sub_id, "object": "subscription", "customer": customer, "status": "active",
            "metadata": metadata, "cancel_at_period_end": False, "canceled_at": None,
            "current_period_start": now, "current_period_end": now + period,
            "items": {"data": [{"price": {"id": f"price_dev_{plan.id.value}"}}]},
        }
        invoice = {"id": f"in_dev_{uuid.uuid4().hex[:14]}", "object": "invoice", "customer": customer,
                   "subscription": sub_id, "amount_paid": plan.amount_cents, "currency": plan.currency,
                   "status": "paid", "description": f"{plan.name} (development checkout)"}
        checkout = {"id": f"cs_dev_{uuid.uuid4().hex[:14]}", "object": "checkout.session", "mode": "subscription",
                    "customer": customer, "subscription": sub_id, "client_reference_id": str(user.id),
                    "metadata": metadata}
        return [self._event("checkout.session.completed", checkout),
                self._event("customer.subscription.created", subscription),
                self._event("invoice.paid", invoice)]

    def set_cancel_at_period_end(self, db: Session, subscription: Subscription, cancel: bool) -> None:
        from app.billing.webhooks import ingest_and_process

        obj = {
            "id": subscription.provider_subscription_id, "object": "subscription",
            "customer": db.get(User, subscription.user_id).billing_customer_id,
            "status": subscription.status.value, "metadata": {"user_id": str(subscription.user_id),
                                                             "plan": subscription.plan.value},
            "cancel_at_period_end": cancel, "canceled_at": int(time.time()) if cancel else None,
            "current_period_start": int(subscription.current_period_start.timestamp()) if subscription.current_period_start else None,
            "current_period_end": int(subscription.current_period_end.timestamp()) if subscription.current_period_end else None,
            "items": {"data": [{"price": {"id": f"price_dev_{subscription.plan.value}"}}]},
        }
        payload, signature = self._event("customer.subscription.updated", obj)
        ingest_and_process(db, payload, signature)

    @staticmethod
    def _event(event_type: str, obj: dict) -> tuple[bytes, str]:
        event = {"id": f"evt_dev_{uuid.uuid4().hex}", "object": "event", "type": event_type,
                 "created": int(time.time()), "livemode": False, "data": {"object": obj}}
        payload = json.dumps(event).encode()
        return payload, sign_payload(payload, get_settings().stripe_webhook_secret)


class RazorpayProvider(BillingProvider):
    name = "razorpay"

    def __init__(self) -> None:
        settings = get_settings()
        if not settings.razorpay_key_id or not settings.razorpay_key_secret:
            raise RuntimeError("RAZORPAY_KEY_ID and RAZORPAY_KEY_SECRET are required when BILLING_PROVIDER=razorpay")
        self.key_id = settings.razorpay_key_id
        self.key_secret = settings.razorpay_key_secret

    def create_checkout(self, db: Session, user: User, plan: Plan) -> str:
        settings = get_settings()
        plan_info = PLANS[plan]
        frontend = settings.frontend_url

        payload = {
            "amount": plan_info.amount_cents,
            "currency": plan_info.currency.upper(),
            "accept_partial": False,
            "description": f"Wavely {plan_info.name}",
            "customer": {
                "name": user.display_name or "Wavely User",
                "email": user.email,
            },
            "notify": {"sms": False, "email": True},
            "reminder_enable": False,
            "notes": {
                "user_id": str(user.id),
                "plan": plan.value,
            },
            "callback_url": f"{frontend}/premium?checkout=success",
            "callback_method": "get",
        }
        with httpx.Client(timeout=15) as client:
            res = client.post(
                "https://api.razorpay.com/v1/payment_links",
                json=payload,
                auth=(self.key_id, self.key_secret),
            )
            if res.status_code not in (200, 201):
                err = res.json().get("error", {}).get("description", "Failed to create Razorpay payment link")
                raise AppError(err, code="payment_init_failed")
            return res.json()["short_url"]

    def set_cancel_at_period_end(self, db: Session, subscription: Subscription, cancel: bool) -> None:
        subscription.cancel_at_period_end = cancel
        if cancel:
            subscription.canceled_at = utcnow()
        db.commit()

    def fetch_subscription(self, subscription_id: str) -> dict | None:
        return None


@lru_cache
def get_provider() -> BillingProvider:
    provider = get_settings().billing_provider
    if provider == "stripe":
        return StripeProvider()
    elif provider == "razorpay":
        return RazorpayProvider()
    return DevProvider()
