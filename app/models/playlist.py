import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, CreatedAt, Timestamps, UUIDPk
from app.models.catalog import Song
from app.models.user import User


class Playlist(UUIDPk, Timestamps, Base):
    __tablename__ = "playlists"

    owner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str] = mapped_column(Text, default="")
    cover_url: Mapped[str | None] = mapped_column(String(500))
    is_public: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    is_collaborative: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    collab_invite_code: Mapped[str | None] = mapped_column(String(32), unique=True)

    owner: Mapped[User] = relationship(lazy="joined")
    tracks: Mapped[list[PlaylistTrack]] = relationship(
        back_populates="playlist", order_by="PlaylistTrack.position", cascade="all, delete-orphan"
    )

    __table_args__ = (
        CheckConstraint("NOT (is_public AND is_collaborative)", name="collab_not_public"),
        Index("ix_playlists_name_trgm", "name", postgresql_using="gin", postgresql_ops={"name": "gin_trgm_ops"}),
    )


class PlaylistTrack(Base):
    __tablename__ = "playlist_tracks"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    playlist_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("playlists.id", ondelete="CASCADE"))
    song_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("songs.id", ondelete="CASCADE"), index=True)
    position: Mapped[int] = mapped_column(Integer)
    added_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    added_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    playlist: Mapped[Playlist] = relationship(back_populates="tracks")
    song: Mapped[Song] = relationship(lazy="joined")
    added_by: Mapped[User | None] = relationship(lazy="joined")

    __table_args__ = (
        # Deferred so a reorder can shift many positions inside one transaction.
        UniqueConstraint("playlist_id", "position", name="uq_playlist_tracks_position",
                         deferrable=True, initially="DEFERRED"),
        CheckConstraint("position >= 0", name="position_non_negative"),
    )


class PlaylistCollaborator(CreatedAt, Base):
    __tablename__ = "playlist_collaborators"

    playlist_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("playlists.id", ondelete="CASCADE"), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True, index=True)

    user: Mapped[User] = relationship(lazy="joined")
