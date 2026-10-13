"""Openverse — WordPress's search engine for openly licensed media (https://api.openverse.org/v1/).

Used for sources we don't integrate directly (by default Wikimedia Commons). Wikimedia files carry no
category, so instead of filtering on `category=music` we drop known non-music categories (pronunciations,
sound effects, podcasts...) and clips under 30 seconds. Jamendo and ccMixter results are excluded because
their own adapters cover them with richer data. Anonymous access works with a low daily limit.
"""

from app.core.config import get_settings
from app.music.http import ProviderClient, ProviderError
from app.music.licensing import ProviderPolicy, parse_license, with_version
from app.music.providers.base import Capability, MusicProvider, ProviderTrack

API = "https://api.openverse.org/v1"
_SKIP_SOURCES = {"jamendo", "ccmixter"}  # covered natively
_NON_MUSIC = {"pronunciation", "sound_effect", "podcast", "audiobook", "news", "sound"}
_MIN_DURATION_MS = 30_000


class OpenverseProvider(MusicProvider):
    key = "openverse"
    name = "Openverse"
    homepage = "https://openverse.org"
    terms_url = "https://docs.openverse.org/terms_of_service.html"
    description = "Openly licensed music indexed from Wikimedia Commons and other open repositories."
    attribution_html = 'Search powered by <a href="https://openverse.org">Openverse</a>; works credited to their creators.'
    capabilities = frozenset({Capability.search, Capability.playback})
    policy = ProviderPolicy(stream=True, requires_open_license=True, download_links=True,
                            notes="Downloads only for Wikimedia Commons files; other sources serve previews to apps.")

    def __init__(self) -> None:
        settings = get_settings()
        self.sources = [s for s in settings.openverse_sources if s not in _SKIP_SOURCES]
        self.http = ProviderClient(self.key, rate_per_second=0.5, burst=2, daily_quota=settings.openverse_daily_quota)

    def is_configured(self) -> bool:
        return bool(self.sources)

    def _to_track(self, r: dict) -> ProviderTrack | None:
        if not r.get("url") or r.get("source") in _SKIP_SOURCES or r.get("category") in _NON_MUSIC:
            return None
        if (r.get("duration") or 0) < _MIN_DURATION_MS:
            return None
        lic = with_version(parse_license(r.get("license_url") or r.get("license")), r.get("license_version"))
        wikimedia = r.get("source") == "wikimedia_audio"
        album = r.get("audio_set") or {}
        return ProviderTrack(
            provider=self.key, provider_track_id=str(r["id"]), title=(r.get("title") or "Untitled")[:200],
            artist_name=r.get("creator") or "Unknown artist", artist_url=r.get("creator_url"),
            album_title=album.get("title"), album_url=album.get("foreign_landing_url"),
            duration_ms=int(r["duration"]) if r.get("duration") else None, artwork_url=r.get("thumbnail"),
            tags=[*(r.get("genres") or []), *(t.get("name", "") for t in r.get("tags") or [])],
            stream_url=r["url"], download_url=r["url"] if wikimedia else None, provider_download_allowed=wikimedia,
            source_url=r.get("foreign_landing_url"), license=lic, attribution=r.get("attribution"),
            explicit=bool(r.get("mature")),
        )

    def search(self, query, *, language=None, limit=20, offset=0):
        if language:
            raise ProviderError(self.key, "unsupported", "Openverse has no language filter")
        if not self.sources:
            raise ProviderError(self.key, "not_configured", "No Openverse sources enabled")
        page_size = max(1, min(limit, 20))
        body = self.http.get_json(f"{API}/audio/", {"q": query, "source": ",".join(self.sources),
                                                    "page_size": page_size, "page": offset // page_size + 1})
        return [t for r in (body.get("results") or []) if (t := self._to_track(r)) is not None]

    def fetch_track(self, provider_track_id):
        try:
            return self._to_track(self.http.get_json(f"{API}/audio/{provider_track_id}/", cache=False))
        except ProviderError as exc:
            if exc.kind == "not_found":
                return None
            raise
