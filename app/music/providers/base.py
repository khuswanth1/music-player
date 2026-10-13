"""The provider-adapter contract.

A provider adapter translates one external catalog into `ProviderTrack`s. Everything downstream —
rights evaluation, storage, search, browse, charts, the player and the frontend — only sees that shape,
so adding a source means writing one adapter and registering it (see docs/MUSIC_SOURCES.md).
"""

import enum
from abc import ABC
from dataclasses import dataclass, field
from datetime import date

from app.music.http import ProviderError
from app.music.licensing import UNKNOWN, License, ProviderPolicy


class Capability(enum.StrEnum):
    search = "search"            # free-text search
    language = "language"        # can filter its catalog by language
    genre = "genre"              # can filter by genre/tag
    popular = "popular"          # can list its own popular/trending tracks
    playback = "playback"        # supplies authorized audio streams
    metadata = "metadata"        # metadata only (no audio), e.g. MusicBrainz


@dataclass
class ProviderTrack:
    provider: str
    provider_track_id: str
    title: str
    artist_name: str
    duration_ms: int | None = None
    provider_artist_id: str | None = None
    artist_url: str | None = None
    album_title: str | None = None
    provider_album_id: str | None = None
    album_url: str | None = None
    release_date: date | None = None
    artwork_url: str | None = None
    language: str | None = None          # raw provider value; normalized during ingest
    language_source: str = "provider"    # provider | tag
    tags: list[str] = field(default_factory=list)
    stream_url: str | None = None        # an authorized playback URL, or None (metadata only)
    download_url: str | None = None
    provider_download_allowed: bool = False
    source_url: str | None = None        # the track's public page at the provider
    license: License = UNKNOWN
    attribution: str | None = None       # provider-supplied attribution text, if any
    popularity: float | None = None      # 0..1 within the provider's own signal
    explicit: bool = False
    isrc: str | None = None
    restrictions: list[str] = field(default_factory=list)  # reasons the provider says it can't be played


@dataclass
class MetadataRecording:
    """A recording known from a metadata-only source; shown as 'not available to stream'."""
    provider: str
    id: str
    title: str
    artist_name: str
    duration_ms: int | None
    release_title: str | None
    release_date: str | None
    url: str
    isrc: str | None = None


class MusicProvider(ABC):
    key: str
    name: str
    homepage: str
    terms_url: str
    description: str
    attribution_html: str = ""  # shown on the Sources page as the provider asks
    capabilities: frozenset[Capability] = frozenset()
    policy: ProviderPolicy = ProviderPolicy()
    requires_credentials: bool = False
    # Anyone can upload and pick a license (vs. curated/artist-only platforms): license claims get extra
    # screening for re-uploaded commercial music (app/music/screening.py).
    open_uploads: bool = False

    def is_configured(self) -> bool:
        return True

    def search(self, query: str, *, language: str | None = None, limit: int = 20, offset: int = 0) -> list[ProviderTrack]:
        raise ProviderError(self.key, "bad_response", "Search is not supported")

    def browse(self, *, language: str | None = None, genre: str | None = None, limit: int = 20,
               offset: int = 0) -> list[ProviderTrack]:
        """Popular tracks, optionally in one language (catalog code) or genre (canonical name)."""
        raise ProviderError(self.key, "bad_response", "Browsing is not supported")

    def fetch_track(self, provider_track_id: str) -> ProviderTrack | None:
        """Current state of one track, for rights re-verification. None if the provider no longer has it."""
        return None

    def playback_url(self, provider_track_id: str, stored_url: str) -> str:
        """The URL handed to the player. Override when stored URLs expire (e.g. signed URLs)."""
        return stored_url


def rank_popularity(position: int, depth: int = 1000) -> float:
    """Turn a position in the provider's own popularity ordering into a 0..1 signal."""
    return max(0.0, 1.0 - position / depth)


def clamp01(value: float | None) -> float | None:
    if value is None:
        return None
    return max(0.0, min(1.0, float(value)))
