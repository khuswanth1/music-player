"""Reference data and bookkeeping for the open-catalog providers."""

from datetime import date, datetime

from sqlalchemy import Boolean, CheckConstraint, Date, DateTime, ForeignKey, Index, Integer, SmallInteger, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Language(Base):
    """ISO 639 languages (seeded by migration from app/music/languages.py)."""

    __tablename__ = "languages"

    code: Mapped[str] = mapped_column(String(12), primary_key=True)
    iso639_3: Mapped[str] = mapped_column(String(3))
    name: Mapped[str] = mapped_column(String(80))
    native_name: Mapped[str] = mapped_column(String(120))
    region: Mapped[str] = mapped_column(String(32), index=True)
    rtl: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    featured_rank: Mapped[int | None] = mapped_column(SmallInteger)  # lower = shown earlier


class ProviderCache(Base):
    """Cached provider API responses, shared by every API replica. Expired rows are purged by the worker."""

    __tablename__ = "provider_cache"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)  # sha256 of provider + URL + params
    provider: Mapped[str] = mapped_column(String(32))
    url: Mapped[str] = mapped_column(Text)
    body: Mapped[dict | list] = mapped_column(JSONB)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class ProviderUsage(Base):
    """Outbound requests per provider per UTC day, to stay inside each provider's quota."""

    __tablename__ = "provider_usage"

    provider: Mapped[str] = mapped_column(String(32), primary_key=True)
    day: Mapped[date] = mapped_column(Date, primary_key=True)
    requests: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    errors: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    last_error: Mapped[str | None] = mapped_column(String(500))
    last_error_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (CheckConstraint("requests >= 0 AND errors >= 0", name="non_negative"),)


class RightsBlock(Base):
    """Tracks that must never be playable here (takedowns), including ones not imported yet."""

    __tablename__ = "rights_blocks"

    source: Mapped[str] = mapped_column(String(32), primary_key=True)
    provider_track_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    reason: Mapped[str] = mapped_column(String(255))
    requested_by: Mapped[str] = mapped_column(String(120))  # "webhook:<event id>" or "admin:<user id>"
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class CatalogSyncState(Base):
    """How far each provider has been paged for each language, so syncs keep reaching new tracks."""

    __tablename__ = "catalog_sync_state"

    provider: Mapped[str] = mapped_column(String(32), primary_key=True)
    language: Mapped[str] = mapped_column(ForeignKey("languages.code", ondelete="CASCADE"), primary_key=True)
    next_offset: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    exhausted: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    imported: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(String(500))

    __table_args__ = (Index("ix_catalog_sync_state_last_synced_at", "last_synced_at"),)
