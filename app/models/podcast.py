"""Podcast subscriptions, saved episodes and listening progress.

Podcasts and episodes live at their providers; we keep only the composite reference (`provider`,
`podcast_id` / `episode_id`) plus a small display snapshot so the library renders without re-querying
providers. No audio is stored; `audio_url` is the publisher's own enclosure URL.
"""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, CreatedAt


class PodcastSubscription(CreatedAt, Base):
    __tablename__ = "podcast_subscriptions"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    podcast_id: Mapped[str] = mapped_column(String(160), primary_key=True)  # "<provider>:<provider id>"
    provider: Mapped[str] = mapped_column(String(32))
    title: Mapped[str] = mapped_column(String(300))
    publisher: Mapped[str | None] = mapped_column(String(300))
    image_url: Mapped[str | None] = mapped_column(String(1000))
    language: Mapped[str | None] = mapped_column(String(12))

    __table_args__ = (Index("ix_podcast_subscriptions_user_created", "user_id", "created_at"),)


class SavedEpisode(CreatedAt, Base):
    __tablename__ = "saved_episodes"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    episode_id: Mapped[str] = mapped_column(String(160), primary_key=True)  # "<podcast id>#<episode key>"
    podcast_id: Mapped[str] = mapped_column(String(160))
    provider: Mapped[str] = mapped_column(String(32))
    title: Mapped[str] = mapped_column(String(500))
    podcast_title: Mapped[str | None] = mapped_column(String(300))
    image_url: Mapped[str | None] = mapped_column(String(1000))
    audio_url: Mapped[str | None] = mapped_column(String(2000))
    duration_s: Mapped[int | None] = mapped_column(Integer)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    description: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (Index("ix_saved_episodes_user_created", "user_id", "created_at"),)


class EpisodeProgress(Base):
    """Resume position and listening history: one row per user per episode, bumped on every report."""

    __tablename__ = "episode_progress"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    episode_id: Mapped[str] = mapped_column(String(160), primary_key=True)
    podcast_id: Mapped[str] = mapped_column(String(160))
    provider: Mapped[str] = mapped_column(String(32))
    title: Mapped[str] = mapped_column(String(500))
    podcast_title: Mapped[str | None] = mapped_column(String(300))
    image_url: Mapped[str | None] = mapped_column(String(1000))
    audio_url: Mapped[str | None] = mapped_column(String(2000))
    position_s: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    duration_s: Mapped[int | None] = mapped_column(Integer)
    completed: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        CheckConstraint("position_s >= 0", name="position_non_negative"),
        Index("ix_episode_progress_user_updated", "user_id", "updated_at"),
    )
