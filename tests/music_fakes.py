"""A configurable in-memory provider, plus helpers for routing mocked provider HTTP."""

import json
from collections.abc import Callable

import httpx

from app.music.licensing import ProviderPolicy, parse_license
from app.music.providers.base import Capability, MusicProvider, ProviderTrack

CC_BY = "https://creativecommons.org/licenses/by/4.0/"
CC_BY_NC = "https://creativecommons.org/licenses/by-nc/4.0/"


def track(pid: str, title: str, *, language: str | None = "te", license_url: str | None = CC_BY,
          duration_ms: int | None = 180_000, artist: str = "Fake Artist", stream: bool = True,
          download: bool = True, popularity: float | None = 0.5, restrictions: list[str] | None = None,
          tags: list[str] | None = None, album: str | None = "Fake Album") -> ProviderTrack:
    return ProviderTrack(
        provider="fake", provider_track_id=pid, title=title, artist_name=artist, provider_artist_id=f"artist-{artist}",
        album_title=album, provider_album_id=f"album-{album}" if album else None, duration_ms=duration_ms,
        language=language, tags=tags or ["folk"], stream_url=f"https://cdn.fake.test/{pid}.mp3" if stream else None,
        download_url=f"https://cdn.fake.test/{pid}.mp3?download=1" if download else None,
        provider_download_allowed=download, source_url=f"https://fake.test/track/{pid}",
        license=parse_license(license_url), popularity=popularity, restrictions=restrictions or [])


class FakeProvider(MusicProvider):
    key = "fake"
    name = "Fake FM"
    homepage = "https://fake.test"
    terms_url = "https://fake.test/terms"
    description = "In-memory provider for tests."
    capabilities = frozenset({Capability.search, Capability.language, Capability.popular, Capability.playback})
    policy = ProviderPolicy(stream=True, requires_open_license=True, download_links=True)

    catalog: dict[str, ProviderTrack] = {}
    calls: list[tuple] = []

    def search(self, query, *, language=None, limit=20, offset=0):
        self.calls.append(("search", query, language))
        hits = [t for t in self.catalog.values()
                if query.lower() in t.title.lower() and (language is None or t.language == language)]
        return hits[offset:offset + limit]

    def browse(self, *, language=None, genre=None, limit=20, offset=0):
        self.calls.append(("browse", language, offset))
        hits = [t for t in self.catalog.values() if language is None or t.language == language]
        return hits[offset:offset + limit]

    def fetch_track(self, provider_track_id):
        self.calls.append(("fetch", provider_track_id))
        return self.catalog.get(provider_track_id)


def routes(table: dict[str, Callable[[httpx.Request], httpx.Response] | dict | list]) -> httpx.MockTransport:
    """MockTransport answering by URL prefix (host + path). Values are JSON bodies or handler functions."""
    def handler(request: httpx.Request) -> httpx.Response:
        url = f"{request.url.host}{request.url.path}"
        for prefix, answer in sorted(table.items(), key=lambda kv: -len(kv[0])):
            if url.startswith(prefix):
                if callable(answer):
                    return answer(request)
                return httpx.Response(200, content=json.dumps(answer), headers={"content-type": "application/json"})
        return httpx.Response(404)
    return httpx.MockTransport(handler)
