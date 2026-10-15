from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.catalog import GenreOut, SongOut


class LanguageOut(BaseModel):
    code: str = Field(description="ISO 639-1 where it exists, otherwise ISO 639-3; `zxx` = instrumental")
    name: str
    native_name: str
    region: str
    region_name: str
    rtl: bool
    featured: bool
    track_count: int = Field(description="Tracks in the catalog in this language")
    playable_count: int = Field(description="Of those, tracks we're authorized to play")


class GenreCount(GenreOut):
    track_count: int


class LanguageDetail(LanguageOut):
    top_genres: list[GenreCount]
    sources: dict[str, int] = Field(description="Playable tracks per source")


class ProviderPolicyOut(BaseModel):
    stream: bool
    requires_open_license: bool
    download_links: bool
    notes: str


class ProviderOut(BaseModel):
    key: str
    name: str
    description: str
    homepage: str
    terms_url: str
    attribution_html: str
    capabilities: list[str]
    enabled: bool = Field(description="Listed in MUSIC_PROVIDERS and configured")
    configured: bool
    requires_credentials: bool
    policy: ProviderPolicyOut
    track_count: int = Field(description="Tracks from this source currently in the catalog")
    playable_count: int


class ProviderStatusOut(BaseModel):
    key: str
    name: str
    status: Literal["ok", "disabled", "not_configured", "unsupported", "rate_limited", "quota_exceeded", "timeout",
                    "error"]
    count: int = 0
    message: str | None = None


class MetadataRecordingOut(BaseModel):
    provider: str
    id: str
    title: str
    artist_name: str
    duration_ms: int | None
    release_title: str | None
    release_date: str | None
    url: str
    isrc: str | None = None


class GlobalSearchOut(BaseModel):
    query: str
    language: str | None
    songs: list[SongOut] = Field(description="Tracks from the providers, now in the catalog (playable first)")
    providers: list[ProviderStatusOut]
    metadata_only: list[MetadataRecordingOut] = Field(
        description="Recordings known from metadata sources with no authorized free audio source")


class FetchResultOut(BaseModel):
    language: str
    imported: int
    updated: int
    providers: list[ProviderStatusOut]


class ChartOut(BaseModel):
    id: str = Field(description="`global`, `region:<key>` or `language:<code>`")
    kind: Literal["global", "region", "language"]
    title: str
    subtitle: str
    track_count: int


class ChartEntry(BaseModel):
    rank: int
    listens_7d: int
    song: SongOut


class ChartDetail(BaseModel):
    id: str
    title: str
    basis: str
    generated_at: datetime
    entries: list[ChartEntry]


class DownloadOut(BaseModel):
    url: str = Field(description="The provider's own download URL; files are never re-hosted here")
    license_name: str | None
    license_url: str | None
    attribution: str | None


class PreferredLanguages(BaseModel):
    languages: list[str] = Field(default_factory=list, max_length=20)


class OnboardingIn(BaseModel):
    """Finishing (or skipping) first-run onboarding. Every field is optional; an empty body means "skipped"."""

    genres: list[str] | None = Field(default=None, max_length=20)


class OnboardingOut(BaseModel):
    onboarded: bool = True
    genres: list[str] = Field(default_factory=list)


class TakedownRequest(BaseModel):
    reason: str = Field(default="Removed following a rights notice", min_length=3, max_length=255)


class SyncRequest(BaseModel):
    language: str
    providers: list[str] | None = None
    pages: int = Field(default=1, ge=1, le=5)


class ProviderUsageOut(BaseModel):
    requests_today: int
    daily_quota: int | None
    errors_today: int
    last_error: str | None
    last_error_at: datetime | None


class SyncStateOut(BaseModel):
    language: str
    next_offset: int
    exhausted: bool
    imported: int
    last_synced_at: datetime | None
    last_error: str | None


class AdminProviderOut(ProviderOut):
    usage: ProviderUsageOut
    sync: list[SyncStateOut]


class CatalogWebhookEvent(BaseModel):
    """Signed rights notification (header `X-Wavely-Signature: t=<unix>,v1=<hex hmac-sha256("t.body")>`)."""

    id: str = Field(min_length=1, max_length=255, description="Unique event id; redeliveries are ignored")
    type: Literal["track.takedown", "track.restore", "track.rights_changed"]
    data: dict = Field(description='{"provider": "jamendo", "provider_track_id": "123", "reason": "..."}')
