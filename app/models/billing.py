import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, CreatedAt, Timestamps, UUIDPk


class Plan(enum.StrEnum):
    premium_monthly = "premium_monthly"
    premium_yearly = "premium_yearly"


class SubscriptionStatus(enum.StrEnum):
    incomplete = "incomplete"
    trialing = "trialing"
    active = "active"
    past_due = "past_due"
    canceled = "canceled"
    unpaid = "unpaid"
    incomplete_expired = "incomplete_expired"


# Statuses that grant premium. past_due keeps access while the provider retries the card.
ENTITLED_STATUSES = (SubscriptionStatus.trialing, SubscriptionStatus.active, SubscriptionStatus.past_due)


class PaymentStatus(enum.StrEnum):
    pending = "pending"
    succeeded = "succeeded"
    failed = "failed"
    refunded = "refunded"


class WebhookStatus(enum.StrEnum):
    received = "received"
    processing = "processing"
    processed = "processed"
    failed = "failed"
    ignored = "ignored"


class Subscription(UUIDPk, Timestamps, Base):
    __tablename__ = "subscriptions"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    plan: Mapped[Plan] = mapped_column(Enum(Plan, name="subscription_plan"))
    status: Mapped[SubscriptionStatus] = mapped_column(Enum(SubscriptionStatus, name="subscription_status"))
    provider: Mapped[str] = mapped_column(String(20))  # stripe | dev | manual
    provider_subscription_id: Mapped[str | None] = mapped_column(String(255), unique=True)
    current_period_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    current_period_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancel_at_period_end: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    canceled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (Index("ix_subscriptions_user_status", "user_id", "status"),)


class Payment(UUIDPk, CreatedAt, Base):
    __tablename__ = "payments"

    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    subscription_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("subscriptions.id", ondelete="SET NULL"), index=True
    )
    provider: Mapped[str] = mapped_column(String(20))
    provider_payment_id: Mapped[str] = mapped_column(String(255), unique=True)
    amount_cents: Mapped[int] = mapped_column(Integer)
    currency: Mapped[str] = mapped_column(String(3))
    status: Mapped[PaymentStatus] = mapped_column(Enum(PaymentStatus, name="payment_status"))
    description: Mapped[str] = mapped_column(String(255), default="")

    __table_args__ = (
        CheckConstraint("amount_cents >= 0", name="amount_non_negative"),
        Index("ix_payments_created_at", "created_at"),
    )


class WebhookEvent(UUIDPk, Base):
    __tablename__ = "webhook_events"

    provider: Mapped[str] = mapped_column(String(20))
    event_id: Mapped[str] = mapped_column(String(255))
    event_type: Mapped[str] = mapped_column(String(100))
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB)
    status: Mapped[WebhookStatus] = mapped_column(
        Enum(WebhookStatus, name="webhook_status"), default=WebhookStatus.received
    )
    attempts: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    last_error: Mapped[str | None] = mapped_column(Text)
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        UniqueConstraint("provider", "event_id", name="uq_webhook_events_provider_event"),
        Index("ix_webhook_events_status_retry", "status", "next_retry_at"),
        Index("ix_webhook_events_received_at", "received_at"),
    )
