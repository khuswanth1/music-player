from datetime import date

from pydantic import BaseModel, Field

from app.schemas.catalog import AlbumOut, ArtistOut, SongOut
from app.schemas.music import ProviderStatusOut


class CountryOut(BaseModel):
    code: str | None = Field(description="ISO 3166-1 alpha-2; null = Unknown (metadata missing)")
    name: str
    track_count: int
    playable_count: int


class GenreFetchIn(BaseModel):
    genre: str = Field(max_length=60, description="Canonical genre name or its slug, e.g. `Jazz` or `drum-bass`")
    page: int = Field(default=0, ge=0, le=50, description="Higher pages reach deeper into each provider's catalog")


class GenreFetchOut(BaseModel):
    genre: str
    slug: str
    page: int
    imported: int
    updated: int
    providers: list[ProviderStatusOut]


class GenreStat(BaseModel):
    id: int | None = Field(None, description="null = a canonical genre with no tracks yet")
    name: str
    slug: str
    color: str
    track_count: int
    playable_count: int


class SoundtrackOut(BaseModel):
    id: str = Field(description="`<provider>:<provider id>`")
    provider: str
    movie_title: str
    album_title: str
    credited_artist: str | None = Field(
        None, description="Lead credited artist - for film scores usually the composer; not verified as such"
    )
    release_date: date | None = None
    release_year: int | None = None
    language: str | None = Field(None, description="Catalog language code, from provider metadata. null = Unknown")
    language_source: str | None = None
    country: str | None = Field(None, description="Release country (ISO 3166-1) when the provider states it; null = Unknown")
    genre: str | None = None
    track_count: int | None = None
    artwork_url: str | None = None
    source_url: str | None = None
    access: str = Field(description="`preview` (30s clips), `metadata` (no audio source), or `full`")


class SoundtrackTrack(BaseModel):
    number: int | None = None
    title: str
    singers: str | None = Field(None, description="Artists credited on the track, as the provider lists them")
    duration_ms: int | None = None
    song: SongOut | None = Field(None, description="Playable catalog track, when the provider supplies audio")
    access: str


class SoundtrackDetail(SoundtrackOut):
    tracks: list[SoundtrackTrack]
    providers: list[ProviderStatusOut] = []


class SoundtrackSearchOut(BaseModel):
    query: str
    interpreted: dict = Field(description="Language / country / years recognized in the query")
    items: list[SoundtrackOut]
    providers: list[ProviderStatusOut]


class MovieOut(BaseModel):
    title: str
    release_year: int | None = None
    language: str | None = None
    country: str | None = None
    artwork_url: str | None = None
    soundtracks: list[SoundtrackOut]


class MovieSearchOut(BaseModel):
    query: str
    interpreted: dict
    items: list[MovieOut]
    providers: list[ProviderStatusOut]


class ArtistCard(ArtistOut):
    languages: list[str] = []
    song_count: int = 0
    playable_count: int = 0
    album_count: int = 0
    image_fallback: str | None = None
    is_followed: bool | None = None


class ArtistSearchOut(BaseModel):
    query: str
    items: list[ArtistCard]
    providers: list[ProviderStatusOut]


class ReleaseYear(BaseModel):
    year: int
    albums: int
    songs: int


class ArtistProfile(ArtistCard):
    follower_count: int = 0
    albums: list[AlbumOut] = []
    singles: list[AlbumOut] = []
    top_songs: list[SongOut] = []
    release_history: list[ReleaseYear] = []
    related: list[ArtistCard] = []
    related_basis: str = ""
    providers: list[ProviderStatusOut] = []


class AlbumCard(AlbumOut):
    track_count: int = 0
    playable_count: int = 0
    language: str | None = None


class AlbumSearchOut(BaseModel):
    query: str
    items: list[AlbumCard]
    providers: list[ProviderStatusOut]


class TrackListOut(BaseModel):
    basis: str
    interpreted: dict = {}
    total: int
    page: int
    page_size: int
    items: list[SongOut]
