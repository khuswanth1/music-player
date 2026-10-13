import enum
import uuid
from datetime import date, datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, CreatedAt, Timestamps, UUIDPk


class AlbumType(enum.StrEnum):
    album = "album"
    single = "single"
    ep = "ep"
    compilation = "compilation"


LOCAL_SOURCE = "local"  # uploaded to and hosted by this service


class Availability(enum.StrEnum):
    playable = "playable"        # an authorized stream exists and rights checks passed
    restricted = "restricted"    # audio exists but license/provider terms/takedown forbid playback here
    unavailable = "unavailable"  # no authorized audio (metadata only, or removed by the provider)


class ProviderRef:
    """Where a catalog row came from: `local`, or a provider key plus that provider's own ID."""

    source: Mapped[str] = mapped_column(String(32), default=LOCAL_SOURCE, server_default=LOCAL_SOURCE)


class Genre(CreatedAt, Base):
    __tablename__ = "genres"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(60), unique=True)
    slug: Mapped[str] = mapped_column(String(60), unique=True)
    color: Mapped[str] = mapped_column(String(7), default="#1db954")


class Artist(UUIDPk, Timestamps, ProviderRef, Base):
    __tablename__ = "artists"

    name: Mapped[str] = mapped_column(String(120))
    slug: Mapped[str] = mapped_column(String(140), unique=True)
    bio: Mapped[str] = mapped_column(Text, default="")
    image_url: Mapped[str | None] = mapped_column(String(1000))
    verified: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    provider_artist_id: Mapped[str | None] = mapped_column(String(128))
    source_url: Mapped[str | None] = mapped_column(String(1000))
    musicbrainz_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    country: Mapped[str | None] = mapped_column(String(2))  # ISO 3166-1 alpha-2

    albums: Mapped[list[Album]] = relationship(back_populates="artist", order_by="Album.release_date.desc().nulls_last()")

    __table_args__ = (
        UniqueConstraint("source", "provider_artist_id", name="uq_artists_source_provider_id"),
        Index("ix_artists_name_trgm", "name", postgresql_using="gin", postgresql_ops={"name": "gin_trgm_ops"}),
    )


class Album(UUIDPk, Timestamps, ProviderRef, Base):
    __tablename__ = "albums"

    title: Mapped[str] = mapped_column(String(200))
    artist_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("artists.id", ondelete="RESTRICT"), index=True)
    album_type: Mapped[AlbumType] = mapped_column(
        Enum(AlbumType, name="album_type"), default=AlbumType.album
    )
    # Unknown for some provider releases; never invented.
    release_date: Mapped[date | None] = mapped_column(Date, index=True)
    cover_url: Mapped[str | None] = mapped_column(String(1000))
    is_featured: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    provider_album_id: Mapped[str | None] = mapped_column(String(128))
    source_url: Mapped[str | None] = mapped_column(String(1000))

    artist: Mapped[Artist] = relationship(back_populates="albums", lazy="joined")
    songs: Mapped[list[Song]] = relationship(back_populates="album", order_by="Song.track_number")

    __table_args__ = (
        UniqueConstraint("source", "provider_album_id", name="uq_albums_source_provider_id"),
        Index("ix_albums_title_trgm", "title", postgresql_using="gin", postgresql_ops={"title": "gin_trgm_ops"}),
    )


class Song(UUIDPk, Timestamps, ProviderRef, Base):
    __tablename__ = "songs"

    title: Mapped[str] = mapped_column(String(200))
    artist_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("artists.id", ondelete="RESTRICT"), index=True)
    album_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("albums.id", ondelete="SET NULL"), index=True)
    genre_id: Mapped[int | None] = mapped_column(ForeignKey("genres.id", ondelete="SET NULL"), index=True)
    track_number: Mapped[int | None] = mapped_column(Integer)
    duration_ms: Mapped[int] = mapped_column(Integer)
    audio_key: Mapped[str | None] = mapped_column(String(500))
    audio_mime: Mapped[str | None] = mapped_column(String(100))
    audio_size: Mapped[int | None] = mapped_column(BigInteger)
    explicit: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    is_premium: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    is_published: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    play_count: Mapped[int] = mapped_column(BigInteger, default=0, server_default="0")

    # --- provenance (provider tracks; NULL / defaults for local uploads) ------------------------
    provider_track_id: Mapped[str | None] = mapped_column(String(128))
    source_url: Mapped[str | None] = mapped_column(String(1000))  # the track's page at the provider
    artwork_url: Mapped[str | None] = mapped_column(String(1000))
    language: Mapped[str | None] = mapped_column(ForeignKey("languages.code", ondelete="SET NULL"), index=True)
    language_source: Mapped[str | None] = mapped_column(String(16))  # provider | musicbrainz | script | tag | manual
    country: Mapped[str | None] = mapped_column(String(2))  # release country (ISO 3166-1), when known
    isrc: Mapped[str | None] = mapped_column(String(12))
    musicbrainz_recording_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    enriched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    provider_popularity: Mapped[float | None] = mapped_column(Float)  # 0..1, from the provider's own signal

    # --- rights ---------------------------------------------------------------------------------
    remote_stream_url: Mapped[str | None] = mapped_column(String(2000))
    remote_download_url: Mapped[str | None] = mapped_column(String(2000))
    license_code: Mapped[str | None] = mapped_column(String(16))
    license_name: Mapped[str | None] = mapped_column(String(80))
    license_url: Mapped[str | None] = mapped_column(String(500))
    attribution: Mapped[str | None] = mapped_column(Text)
    availability: Mapped[Availability] = mapped_column(
        Enum(Availability, name="availability"), default=Availability.playable, server_default="playable")
    stream_allowed: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    download_allowed: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    restriction_reason: Mapped[str | None] = mapped_column(String(255))
    rights_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Set by a takedown; provider re-syncs never make the track playable again until it is cleared.
    takedown_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    artist: Mapped[Artist] = relationship(lazy="joined")
    album: Mapped[Album | None] = relationship(back_populates="songs", lazy="joined")
    genre: Mapped[Genre | None] = relationship(lazy="joined")

    @property
    def is_local(self) -> bool:
        return self.source == LOCAL_SOURCE

    @property
    def has_audio(self) -> bool:
        return self.audio_key is not None or self.remote_stream_url is not None

    @property
    def playable(self) -> bool:
        return self.availability == Availability.playable and self.stream_allowed and self.has_audio

    __table_args__ = (
        UniqueConstraint("album_id", "track_number", name="uq_songs_album_track"),
        UniqueConstraint("source", "provider_track_id", name="uq_songs_source_provider_id"),
        CheckConstraint("duration_ms > 0", name="duration_positive"),
        CheckConstraint("play_count >= 0", name="play_count_non_negative"),
        CheckConstraint("provider_popularity IS NULL OR provider_popularity BETWEEN 0 AND 1", name="popularity_range"),
        CheckConstraint("(source = 'local') = (provider_track_id IS NULL)", name="provider_id_matches_source"),
        Index("ix_songs_title_trgm", "title", postgresql_using="gin", postgresql_ops={"title": "gin_trgm_ops"}),
        Index("ix_songs_availability_language", "availability", "language"),
        Index("ix_songs_enrichment_pending", "created_at", postgresql_where="source <> 'local' AND enriched_at IS NULL"),
    )


Index("ix_songs_play_count", Song.play_count.desc())
