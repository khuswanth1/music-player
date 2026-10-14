"""User-managed collections of provider tracks. Only references are stored, never audio."""

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, Boolean, CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, Timestamps, UUIDPk
from app.models.catalog import Song
from app.models.user import User


class PrivateAlbum(UUIDPk, Timestamps, Base):
    __tablename__ = "private_albums"

    owner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str] = mapped_column(Text, default="", server_default="")
    cover_url: Mapped[str | None] = mapped_column(String(1000))
    is_public: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    is_favorite: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    # Unguessable token for sharing a public album; rotated on demand.
    share_code: Mapped[str | None] = mapped_column(String(32), unique=True)

    owner: Mapped[User] = relationship(lazy="joined")
    tracks: Mapped[list[PrivateAlbumTrack]] = relationship(
        back_populates="album", order_by="PrivateAlbumTrack.position", cascade="all, delete-orphan"
    )

    __table_args__ = (Index("ix_private_albums_owner_name", "owner_id", "name"),)


class PrivateAlbumTrack(Base):
    __tablename__ = "private_album_tracks"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    album_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("private_albums.id", ondelete="CASCADE"))
    song_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("songs.id", ondelete="CASCADE"), index=True)
    position: Mapped[int] = mapped_column(Integer)
    added_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    album: Mapped[PrivateAlbum] = relationship(back_populates="tracks")
    song: Mapped[Song] = relationship(lazy="joined")

    __table_args__ = (
        UniqueConstraint("album_id", "song_id", name="uq_private_album_tracks_song"),
        UniqueConstraint("album_id", "position", name="uq_private_album_tracks_position", deferrable=True, initially="DEFERRED"),
        CheckConstraint("position >= 0", name="position_non_negative"),
    )
