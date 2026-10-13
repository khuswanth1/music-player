import enum
import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum, Float, ForeignKey, Integer, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, CreatedAt, Timestamps, UUIDPk
from app.models.catalog import Song
from app.models.user import User


class RepeatMode(enum.StrEnum):
    off = "off"
    all = "all"
    one = "one"


class PlayerState(Base):
    """A user's own player, persisted so playback resumes across devices and reloads."""

    __tablename__ = "player_states"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    current_song_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("songs.id", ondelete="SET NULL"), index=True)
    position_ms: Mapped[int] = mapped_column(Integer, default=0)
    queue: Mapped[list[str]] = mapped_column(JSONB, default=list)
    context: Mapped[dict | None] = mapped_column(JSONB)
    shuffle: Mapped[bool] = mapped_column(Boolean, default=False)
    repeat_mode: Mapped[RepeatMode] = mapped_column(Enum(RepeatMode, name="repeat_mode"), default=RepeatMode.off)
    volume: Mapped[float] = mapped_column(Float, default=0.8)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class PlaybackSession(UUIDPk, Timestamps, Base):
    """A group listening session: the host controls playback, members follow along."""

    __tablename__ = "playback_sessions"

    host_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    invite_code: Mapped[str] = mapped_column(String(32), unique=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    current_song_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("songs.id", ondelete="SET NULL"), index=True)
    position_ms: Mapped[int] = mapped_column(Integer, default=0)
    is_playing: Mapped[bool] = mapped_column(Boolean, default=False)
    queue: Mapped[list[str]] = mapped_column(JSONB, default=list)
    state_updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    host: Mapped[User] = relationship(lazy="joined")
    current_song: Mapped[Song | None] = relationship(lazy="joined")


class PlaybackSessionMember(CreatedAt, Base):
    __tablename__ = "playback_session_members"

    session_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("playback_sessions.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True, index=True)

    user: Mapped[User] = relationship(lazy="joined")
