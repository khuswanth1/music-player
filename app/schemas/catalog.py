import uuid
from datetime import date, datetime

from pydantic import BaseModel, Field, computed_field, field_validator

from app.models.catalog import AlbumType, Availability
from app.schemas.common import ORMModel


def source_name(key: str) -> str:
    """Display name for a catalog source ("local" = hosted by this service)."""
    from app.core.config import get_settings
    from app.music.providers import get_provider  # deferred: providers import models and settings

    if key == "local":
        return get_settings().app_name
    provider = get_provider(key)
    return provider.name if provider else key

_HEX = r"^#[0-9a-fA-F]{6}$"


class GenreOut(ORMModel):
    id: int
    name: str
    slug: str
    color: str


class GenreCreate(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    color: str = Field(default="#1db954", pattern=_HEX)


class GenreUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=60)
    color: str | None = Field(default=None, pattern=_HEX)


class ArtistRef(ORMModel):
    id: uuid.UUID
    name: str
    slug: str


class ArtistOut(ORMModel):
    id: uuid.UUID
    name: str
    slug: str
    bio: str
    image_url: str | None
    verified: bool
    source: str = "local"
    source_url: str | None = None
    country: str | None = None


class ArtistDetail(ArtistOut):
    follower_count: int
    monthly_plays: int
    is_followed: bool | None = None


class ArtistCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    bio: str = Field(default="", max_length=5000)
    verified: bool = False


class ArtistUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    bio: str | None = Field(default=None, max_length=5000)
    verified: bool | None = None


class AlbumRef(ORMModel):
    id: uuid.UUID
    title: str
    cover_url: str | None


class AlbumOut(ORMModel):
    id: uuid.UUID
    title: str
    album_type: AlbumType
    release_date: date | None
    cover_url: str | None
    is_featured: bool
    artist: ArtistRef
    source: str = "local"
    source_url: str | None = None


class AlbumCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    artist_id: uuid.UUID
    album_type: AlbumType = AlbumType.album
    release_date: date
    is_featured: bool = False


class AlbumUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    artist_id: uuid.UUID | None = None
    album_type: AlbumType | None = None
    release_date: date | None = None
    is_featured: bool | None = None


class SongOut(ORMModel):
    id: uuid.UUID
    title: str
    duration_ms: int
    track_number: int | None
    explicit: bool
    is_premium: bool
    is_published: bool
    play_count: int
    has_audio: bool
    artist: ArtistRef
    album: AlbumRef | None
    genre: GenreOut | None
    created_at: datetime
    liked: bool | None = None
    # Where the track comes from and what we may do with it.
    source: str = Field("local", description="`local` (hosted here) or a provider key, e.g. `jamendo`")
    source_url: str | None = Field(None, description="The track's page at its provider")
    artwork_url: str | None = None
    language: str | None = Field(None, description="Catalog language code (ISO 639-1, else 639-3; `zxx` = instrumental)")
    language_source: str | None = Field(None, description="provider | musicbrainz | script | tag | manual")
    availability: Availability = Availability.playable
    playable: bool = True
    restriction_reason: str | None = None
    download_allowed: bool = False
    license_code: str | None = None
    license_name: str | None = None
    license_url: str | None = None
    attribution: str | None = None
    upgrading: bool = Field(False, description="True when this is a short preview and the full stream is still being resolved")
    country: str | None = Field(None, description="Release country (ISO 3166-1) when a provider states it; null = Unknown")
    release_date: date | None = Field(None, description="Release date of the track's album, when known")

    @computed_field
    @property
    def source_name(self) -> str:
        return source_name(self.source)

    @computed_field(description="`full` (complete recording), `preview` (provider's short clip) or `metadata` (cannot be played here)")
    @property
    def access(self) -> str:
        if not (self.playable and self.has_audio):
            return "metadata"
        if self.source == "itunes" or self.license_code in ("full", None):
            return "full"
        return "preview" if self.license_code == "preview" else "full"




class AlbumDetail(AlbumOut):
    songs: list[SongOut]
    total_duration_ms: int
    is_saved: bool | None = None


class SongUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    artist_id: uuid.UUID | None = None
    album_id: uuid.UUID | None = None
    genre_id: int | None = None
    track_number: int | None = Field(default=None, ge=1, le=999)
    explicit: bool | None = None
    is_premium: bool | None = None
    is_published: bool | None = None
    language: str | None = Field(default=None, max_length=12, description="Corrects the language; recorded as manual")

    @field_validator("title")
    @classmethod
    def _strip(cls, v):
        return v.strip() if v else v


class StreamUrl(BaseModel):
    url: str
    expires_in: int
    mime_type: str | None
    external: bool = Field(False, description="True when the URL is the provider's own authorized stream")
    attribution: str | None = None
    upgrading: bool = Field(False, description="True when this is a short preview and the full stream is still being resolved")
