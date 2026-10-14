from datetime import datetime

from pydantic import BaseModel, Field

from app.schemas.music import ProviderStatusOut


class PodcastOut(BaseModel):
    id: str = Field(description="Composite id `<provider>:<provider id>`")
    provider: str
    provider_id: str
    title: str
    publisher: str | None = None
    description: str | None = None
    image_url: str | None = None
    feed_url: str | None = None
    website: str | None = None
    language: str | None = Field(None, description="Catalog language code; null = Unknown (never guessed)")
    storefront_country: str | None = Field(None, description="Apple Podcasts storefront the result came from, not the show's origin")
    categories: list[str] = []
    episode_count: int | None = None
    latest_episode_at: datetime | None = None
    explicit: bool = False
    source_url: str | None = None
    followed: bool | None = None
    label: str = "Podcast"


class EpisodeOut(BaseModel):
    id: str = Field(description="`<podcast id>#<episode key>`")
    podcast_id: str
    provider: str
    podcast_title: str | None = None
    title: str
    description: str | None = None
    audio_url: str | None = Field(None, description="The publisher's own enclosure URL; null = not playable")
    mime_type: str | None = None
    duration_s: int | None = None
    published_at: datetime | None = None
    image_url: str | None = None
    season: int | None = None
    episode: int | None = None
    explicit: bool = False
    source_url: str | None = None
    playable: bool = False
    saved: bool | None = None
    position_s: int | None = Field(None, description="Where this user left off (if they have started it)")
    completed: bool | None = None
    label: str = "Podcast"


class PodcastSearchOut(BaseModel):
    query: str
    basis: str
    podcasts: list[PodcastOut]
    providers: list[ProviderStatusOut]


class PodcastDetailOut(PodcastOut):
    providers: list[ProviderStatusOut] = []


class EpisodePageOut(BaseModel):
    podcast: PodcastOut
    items: list[EpisodeOut]
    total: int
    page: int
    page_size: int
    pages: int


class EpisodeSnapshot(BaseModel):
    """What the client knows about an episode; stored so saved items and history render without re-fetching."""

    podcast_id: str = Field(max_length=160)
    title: str = Field(max_length=500)
    podcast_title: str | None = Field(None, max_length=300)
    image_url: str | None = Field(None, max_length=1000)
    audio_url: str | None = Field(None, max_length=2000)
    duration_s: int | None = Field(None, ge=0)
    published_at: datetime | None = None
    description: str | None = Field(None, max_length=4000)


class ProgressIn(EpisodeSnapshot):
    episode_id: str = Field(max_length=160)
    position_s: int = Field(ge=0)
    completed: bool = False


class SubscribeIn(BaseModel):
    title: str = Field(max_length=300)
    publisher: str | None = Field(None, max_length=300)
    image_url: str | None = Field(None, max_length=1000)
    language: str | None = Field(None, max_length=12)


class CategoryOut(BaseModel):
    id: str
    name: str


class ProgressOut(BaseModel):
    episode_id: str
    podcast_id: str
    title: str
    podcast_title: str | None
    image_url: str | None
    audio_url: str | None
    position_s: int
    duration_s: int | None
    completed: bool
    updated_at: datetime
