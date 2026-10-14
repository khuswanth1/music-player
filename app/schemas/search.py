from datetime import datetime

from pydantic import BaseModel, Field

from app.schemas.catalog import GenreOut, SongOut
from app.schemas.music import MetadataRecordingOut, ProviderStatusOut
from app.schemas.playlist import PlaylistSummary
from app.schemas.podcast import EpisodeOut, PodcastOut
from app.schemas.private_album import PrivateAlbumSummary
from app.schemas.worldmusic import AlbumCard, ArtistCard, SoundtrackOut


class LanguageHit(BaseModel):
    code: str
    name: str
    native_name: str
    playable_count: int


class CountryHit(BaseModel):
    code: str
    name: str


class UnifiedSearchOut(BaseModel):
    query: str
    language: str | None = None
    interpreted: dict = Field(default={}, description="Filters recognized in the query text (language, country, years, era)")
    page: int = 1
    has_more: bool = False
    songs: list[SongOut] = Field(default=[], description="Each carries `access`: full | preview | metadata")
    metadata_only: list[MetadataRecordingOut] = []
    artists: list[ArtistCard] = []
    albums: list[AlbumCard] = []
    soundtracks: list[SoundtrackOut] = []
    podcasts: list[PodcastOut] = []
    episodes: list[EpisodeOut] = []
    playlists: list[PlaylistSummary] = []
    private_albums: list[PrivateAlbumSummary] = []
    languages: list[LanguageHit] = []
    countries: list[CountryHit] = []
    genres: list[GenreOut] = []
    years: list[int] = []
    providers: list[ProviderStatusOut] = []


class Suggestion(BaseModel):
    text: str
    type: str = Field(description="song | artist | album | language | genre | country | recent")
    subtitle: str | None = None
    image_url: str | None = None
    # How the client should open it: a search query, or a route.
    query: str | None = None
    href: str | None = None


class SuggestionsOut(BaseModel):
    query: str
    items: list[Suggestion]


class SearchHistoryIn(BaseModel):
    query: str = Field(min_length=1, max_length=100)


class SearchHistoryItem(BaseModel):
    query: str
    last_searched_at: datetime
