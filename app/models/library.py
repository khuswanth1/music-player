import uuid
from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Index, Integer, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, CreatedAt
from app.models.catalog import Album, Artist, Song
from app.models.playlist import Playlist


class LikedSong(CreatedAt, Base):
    __tablename__ = "liked_songs"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    song_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("songs.id", ondelete="CASCADE"), primary_key=True, index=True)

    song: Mapped[Song] = relationship(lazy="joined")

    __table_args__ = (Index("ix_liked_songs_user_created", "user_id", "created_at"),)


class FollowedArtist(CreatedAt, Base):
    __tablename__ = "followed_artists"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    artist_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("artists.id", ondelete="CASCADE"), primary_key=True, index=True)

    artist: Mapped[Artist] = relationship(lazy="joined")


class SavedAlbum(CreatedAt, Base):
    __tablename__ = "saved_albums"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    album_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("albums.id", ondelete="CASCADE"), primary_key=True, index=True)

    album: Mapped[Album] = relationship(lazy="joined")


class SavedPlaylist(CreatedAt, Base):
    __tablename__ = "saved_playlists"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    playlist_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("playlists.id", ondelete="CASCADE"), primary_key=True, index=True)

    playlist: Mapped[Playlist] = relationship(lazy="joined")


class ListeningHistory(Base):
    __tablename__ = "listening_history"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    song_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("songs.id", ondelete="CASCADE"), index=True)
    played_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    ms_played: Mapped[int] = mapped_column(Integer, default=0)
    completed: Mapped[bool] = mapped_column(Boolean, default=False)
    context_type: Mapped[str | None] = mapped_column(String(20))
    context_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))

    song: Mapped[Song] = relationship(lazy="joined")

    __table_args__ = (Index("ix_listening_history_played_at", "played_at"),)


Index("ix_listening_history_user_played", ListeningHistory.user_id, ListeningHistory.played_at.desc())
