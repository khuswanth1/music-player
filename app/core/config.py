from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BACKEND_DIR / ".env", env_file_encoding="utf-8", extra="ignore"
    )

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls,
        init_settings,
        env_settings,
        dotenv_settings,
        file_secret_settings,
    ):
        return (init_settings, dotenv_settings, env_settings, file_secret_settings)

    app_name: str = "Wavely"
    environment: Literal["development", "test", "production"] = "development"
    debug: bool = False
    log_level: str = "INFO"
    log_json: bool = True

    # Public URLs. FRONTEND_URL is used in emails and OAuth/checkout redirects.
    frontend_url: str = "http://localhost:5173"
    backend_public_url: str = "http://localhost:8000"
    cors_origins: Annotated[list[str], NoDecode] = Field(default_factory=lambda: ["http://localhost:5173"])
    trusted_hosts: Annotated[list[str], NoDecode] = Field(default_factory=lambda: ["*"])

    database_url: str = "postgresql+psycopg://spotify:spotify@localhost:5432/spotify"
    db_pool_size: int = 10
    db_max_overflow: int = 10

    # Auth
    jwt_secret: str = "change-me"
    jwt_algorithm: str = "HS256"
    access_token_ttl_minutes: int = 15
    refresh_token_ttl_days: int = 14
    stream_token_ttl_minutes: int = 60
    password_reset_ttl_minutes: int = 30
    login_code_ttl_minutes: int = 10
    login_code_max_attempts: int = 5
    login_code_resend_seconds: int = 30
    refresh_cookie_name: str = "wavely_refresh"
    cookie_secure: bool = False

    # Google OAuth (optional)
    google_client_id: str | None = None
    google_client_secret: str | None = None

    # Rate limiting (requests per window, per client IP and route)
    rate_limit_enabled: bool = True
    auth_rate_limit: int = 10
    auth_rate_window_seconds: int = 60

    # Storage
    storage_backend: Literal["local", "s3"] = "local"
    media_root: Path = BACKEND_DIR / "media"
    s3_bucket: str | None = None
    s3_endpoint_url: str | None = None
    s3_region: str = "us-east-1"
    s3_access_key_id: str | None = None
    s3_secret_access_key: str | None = None
    max_audio_upload_mb: int = 50
    max_image_upload_mb: int = 5

    # Billing
    billing_provider: Literal["stripe", "dev", "razorpay"] = "dev"
    stripe_secret_key: str | None = None
    stripe_webhook_secret: str = "whsec_dev_only_change_me"
    stripe_price_premium_monthly: str | None = None
    stripe_price_premium_yearly: str | None = None
    razorpay_key_id: str | None = None
    razorpay_key_secret: str | None = None
    razorpay_webhook_secret: str | None = None
    razorpay_currency: str = "inr"
    webhook_tolerance_seconds: int = 300
    webhook_max_attempts: int = 6

    # Email
    email_backend: Literal["console", "smtp"] = "console"
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_username: str | None = None
    smtp_password: str | None = None
    smtp_use_tls: bool = True
    email_from: str = "Wavely <no-reply@wavely.local>"

    # Product limits
    free_playlist_limit: int = 15

    # Background worker
    worker_enabled: bool = True
    worker_interval_seconds: int = 30

    # --- Open music catalogs (docs/MUSIC_SOURCES.md) --------------------------------------
    # Comma-separated provider keys to enable. Providers that need credentials stay inactive until configured.
    # `audius` is available but off by default: it is an open-upload platform (see docs/MUSIC_SOURCES.md).
    music_providers: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["jamendo", "internet_archive", "openverse", "ccmixter", "musicbrainz"])
    # Sent to every provider. MusicBrainz requires a meaningful User-Agent with contact details.
    music_user_agent: str = "Wavely/1.0 (+https://github.com/your-org/wavely)"
    music_http_timeout_seconds: float = 8.0
    # Total time budget for one federated search or language fetch across all providers.
    music_search_budget_seconds: float = 10.0
    # How long provider API responses are cached in PostgreSQL.
    music_cache_ttl_minutes: int = 360
    # Re-verify a track's rights with its provider before playback when the last check is older than this.
    rights_revalidate_hours: int = 168
    # Set true if this deployment is commercial (ads, paid tiers that unlock provider tracks, etc.).
    # Tracks under NonCommercial licenses (CC BY-NC*) are then excluded from playback.
    commercial_deployment: bool = False
    # Offer "Download" links for tracks whose license AND provider terms both allow it.
    music_downloads_enabled: bool = True
    # Background sync: languages to keep warm (ISO codes), and how often (worker ticks) to fetch a page.
    catalog_sync_enabled: bool = False
    catalog_sync_languages: Annotated[list[str], NoDecode] = Field(default_factory=lambda: [
        "te", "hi", "ta", "kn", "ml", "bn", "pa", "en", "ko", "ja", "zh", "ar", "es", "fr", "pt", "de"])
    catalog_sync_every_ticks: int = 10
    musicbrainz_enrichment_enabled: bool = True
    # Shared secret for signed rights notifications (takedowns, license changes) to /catalog/webhooks.
    catalog_webhook_secret: str = "whsec_catalog_dev_only_change_me"

    jamendo_client_id: str | None = None  # free key: https://devportal.jamendo.com
    jamendo_daily_quota: int = 1000
    internet_archive_daily_quota: int = 5000
    audius_app_name: str = "Wavely"
    audius_daily_quota: int = 5000
    openverse_daily_quota: int = 200  # anonymous Openverse limit; register an app for more
    openverse_sources: Annotated[list[str], NoDecode] = Field(default_factory=lambda: ["wikimedia_audio"])
    ccmixter_daily_quota: int = 2000
    musicbrainz_daily_quota: int = 20000

    @field_validator("cors_origins", "trusted_hosts", "music_providers", "catalog_sync_languages",
                     "openverse_sources", mode="before")
    @classmethod
    def _split_csv(cls, value):
        if isinstance(value, str) and not value.strip().startswith("["):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    @model_validator(mode="after")
    def _check_production(self):
        if self.environment == "production":
            if self.jwt_secret in ("change-me", "") or len(self.jwt_secret) < 32:
                raise ValueError("JWT_SECRET must be set to a random value of 32+ characters in production")
            if self.billing_provider == "dev":
                raise ValueError("BILLING_PROVIDER=dev is not allowed in production")
            if self.stripe_webhook_secret.startswith("whsec_dev"):
                raise ValueError("STRIPE_WEBHOOK_SECRET must be set in production")
            if not self.cookie_secure:
                raise ValueError("COOKIE_SECURE must be true in production")
            if self.catalog_webhook_secret.startswith(("whsec_catalog_dev", "whsec_catalog_replace")):
                raise ValueError("CATALOG_WEBHOOK_SECRET must be set in production")
        return self

    @property
    def google_enabled(self) -> bool:
        return bool(self.google_client_id and self.google_client_secret)


@lru_cache
def get_settings() -> Settings:
    return Settings()
