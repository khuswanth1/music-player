import uuid
from datetime import date, datetime

from sqlalchemy import Boolean, CheckConstraint, Date, DateTime, ForeignKey, Index, SmallInteger, String, Text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, CreatedAt, Timestamps, UUIDPk


class Role(Base):
    __tablename__ = "roles"

    id: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    name: Mapped[str] = mapped_column(String(32), unique=True)
    description: Mapped[str] = mapped_column(String(255), default="")


class User(UUIDPk, Timestamps, Base):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(320), unique=True)
    display_name: Mapped[str] = mapped_column(String(80))
    password_hash: Mapped[str | None] = mapped_column(String(255))
    avatar_url: Mapped[str | None] = mapped_column(String(500))
    role_id: Mapped[int] = mapped_column(ForeignKey("roles.id", ondelete="RESTRICT"), index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    google_sub: Mapped[str | None] = mapped_column(String(255), unique=True)
    billing_customer_id: Mapped[str | None] = mapped_column(String(255), unique=True)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Language codes (languages.code) the user wants more of; validated on write.
    preferred_languages: Mapped[list[str]] = mapped_column(ARRAY(String(12)), default=list, server_default="{}")
    # Genre slugs picked during onboarding ("music journey"); they seed recommendations until listening history does.
    preferred_genres: Mapped[list[str]] = mapped_column(ARRAY(String(40)), default=list, server_default="{}")
    # Set once the first-run onboarding has been finished or skipped; null means it still has to be offered.
    onboarded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Display choices: which home shelves to show and in what order, density, ... (validated in schemas.user.UiPrefs).
    ui_prefs: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")
    date_of_birth: Mapped[date | None] = mapped_column(Date)
    gender: Mapped[str | None] = mapped_column(String(24))
    marketing_emails: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")

    role: Mapped[Role] = relationship(lazy="joined")

    @property
    def role_name(self) -> str:
        return self.role.name


class RefreshToken(UUIDPk, CreatedAt, Base):
    __tablename__ = "refresh_tokens"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    family_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))  # logout / theft response
    rotated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))  # replaced by a newer token
    user_agent: Mapped[str | None] = mapped_column(String(255))
    ip: Mapped[str | None] = mapped_column(String(64))

    __table_args__ = (Index("ix_refresh_tokens_expires_at", "expires_at"),)


class LoginCode(UUIDPk, CreatedAt, Base):
    """A one-time 6-digit sign-in code sent by email. Only an HMAC of the code is stored."""

    __tablename__ = "login_codes"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    code_hash: Mapped[str] = mapped_column(String(64))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    attempts: Mapped[int] = mapped_column(SmallInteger, default=0, server_default="0")
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    requested_ip: Mapped[str | None] = mapped_column(String(64))

    __table_args__ = (CheckConstraint("attempts >= 0", name="attempts_non_negative"),
                      Index("ix_login_codes_expires_at", "expires_at"))


class PasswordResetToken(UUIDPk, CreatedAt, Base):
    __tablename__ = "password_reset_tokens"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    requested_ip: Mapped[str | None] = mapped_column(Text)
