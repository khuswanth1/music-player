"""Jamendo — independent music under Creative Commons licenses (https://developer.jamendo.com/v3.0).

Needs a free client ID from https://devportal.jamendo.com. The free API tier is for non-commercial
use; a commercial service needs a Jamendo Licensing agreement. Every track carries its own CC license
URL and an `audiodownload_allowed` flag set by the artist, both of which we honor.
"""

from datetime import date

from app.core.config import get_settings
from app.music.http import ProviderClient, ProviderError
from app.music.licensing import ProviderPolicy, parse_license
from app.music.providers.base import Capability, MusicProvider, ProviderTrack, rank_popularity

API = "https://api.jamendo.com/v3.0"
# Canonical genre -> Jamendo tag where the names differ.
_GENRE_TAGS = {"Hip-Hop": "hiphop", "R&B & Soul": "rnb", "Soundtrack": "soundtrack", "Drum & Bass": "drumnbass",
               "Lo-Fi": "lofi", "Chillout": "chillout", "Electronic": "electronic", "World": "world"}


class JamendoProvider(MusicProvider):
    key = "jamendo"
    name = "Jamendo"
    homepage = "https://www.jamendo.com"
    terms_url = "https://devportal.jamendo.com/api_terms_of_use"
    description = "Independent artists worldwide, every track under a Creative Commons license."
    attribution_html = 'Music from <a href="https://www.jamendo.com">Jamendo</a>, used under each track\'s Creative Commons license.'
    capabilities = frozenset({Capability.search, Capability.language, Capability.genre, Capability.popular,
                              Capability.playback})
    policy = ProviderPolicy(stream=True, requires_open_license=True, download_links=True,
                            notes="Free API tier is non-commercial; commercial use needs Jamendo Licensing.")
    requires_credentials = True

    def __init__(self) -> None:
        settings = get_settings()
        self.client_id = settings.jamendo_client_id
        self.http = ProviderClient(self.key, rate_per_second=5, burst=5, daily_quota=settings.jamendo_daily_quota)

    def is_configured(self) -> bool:
        return bool(self.client_id)

    def _tracks(self, params: dict) -> list[dict]:
        if not self.client_id:
            raise ProviderError(self.key, "not_configured", "Set JAMENDO_CLIENT_ID to enable Jamendo")
        body = self.http.get_json(f"{API}/tracks/", {
            "client_id": self.client_id, "format": "json", "include": "musicinfo licenses",
            "audioformat": "mp32", "imagesize": 300, **params})
        headers = body.get("headers") or {}
        if headers.get("status") != "success":
            kind = "not_configured" if headers.get("code") == 5 else "bad_response"
            raise ProviderError(self.key, kind, headers.get("error_message") or "Jamendo request failed")
        return body.get("results") or []

    def _to_track(self, r: dict, popularity: float | None = None) -> ProviderTrack:
        info = r.get("musicinfo") or {}
        tags = info.get("tags") or {}
        instrumental = info.get("vocalinstrumental") == "instrumental"
        try:
            released = date.fromisoformat(r["releasedate"]) if r.get("releasedate") else None
        except ValueError:
            released = None
        return ProviderTrack(
            provider=self.key, provider_track_id=str(r["id"]), title=r.get("name") or "Untitled",
            artist_name=r.get("artist_name") or "Unknown artist", provider_artist_id=str(r.get("artist_id") or "") or None,
            artist_url=f"https://www.jamendo.com/artist/{r['artist_id']}" if r.get("artist_id") else None,
            album_title=r.get("album_name") or None, provider_album_id=str(r.get("album_id") or "") or None,
            album_url=f"https://www.jamendo.com/album/{r['album_id']}" if r.get("album_id") else None,
            release_date=released, duration_ms=int(r["duration"]) * 1000 if r.get("duration") else None,
            artwork_url=r.get("album_image") or r.get("image") or None,
            language="zxx" if instrumental else (info.get("lang") or None),
            tags=[*(tags.get("genres") or []), *(tags.get("vartags") or [])],
            stream_url=r.get("audio") or None, download_url=r.get("audiodownload") or None,
            provider_download_allowed=bool(r.get("audiodownload_allowed")),
            source_url=r.get("shareurl") or f"https://www.jamendo.com/track/{r['id']}",
            license=parse_license(r.get("license_ccurl")), popularity=popularity,
        )

    def search(self, query, *, language=None, limit=20, offset=0):
        params = {"search": query, "limit": limit, "offset": offset, "order": "relevance", "boost": "popularity_month"}
        params.update(self._language_params(language))
        return [self._to_track(r) for r in self._tracks(params)]

    def browse(self, *, language=None, genre=None, limit=20, offset=0):
        params = {"limit": limit, "offset": offset, "order": "popularity_month"}
        params.update(self._language_params(language))
        if genre:
            params["tags"] = _GENRE_TAGS.get(genre, genre.lower().replace(" ", ""))
        return [self._to_track(r, rank_popularity(offset + i)) for i, r in enumerate(self._tracks(params))]

    def fetch_track(self, provider_track_id):
        results = self._tracks({"id": provider_track_id})
        return self._to_track(results[0]) if results else None

    def _language_params(self, language: str | None) -> dict:
        if not language:
            return {}
        if language == "zxx":
            return {"vocalinstrumental": "instrumental"}
        if len(language) != 2:  # Jamendo filters by ISO 639-1 only
            raise ProviderError(self.key, "unsupported", "Jamendo can't filter by this language")
        return {"lang": language}
