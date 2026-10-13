"""Audius — artist-uploaded music, streamable by third-party apps through its open API
(https://docs.audius.org/developers/api). No key needed; requests identify the app with `app_name`.

Most Audius tracks are "All rights reserved": artists upload them to be streamed by Audius clients,
which the API terms extend to third-party apps. We therefore stream them through Audius's own stream
endpoint, but never offer downloads, and skip tracks that are gated (purchase/follow), unlisted,
deleted, or restricted by the artist to specific apps.
"""

import math
from datetime import date

from app.core.config import get_settings
from app.music.http import ProviderClient, ProviderError
from app.music.licensing import PLATFORM_STREAM_ONLY, ProviderPolicy, parse_license
from app.music.providers.base import Capability, MusicProvider, ProviderTrack, clamp01

API = "https://api.audius.co/v1"
# Canonical genre -> Audius genre name.
_GENRES = {"Hip-Hop": "Hip-Hop/Rap", "R&B & Soul": "R&B/Soul", "Drum & Bass": "Drum & Bass", "Lo-Fi": "Lo-Fi",
           "Soundtrack": "Soundtrack", "Devotional": "Devotional", "Latin": "Latin", "Reggae": "Reggae",
           "Electronic": "Electronic", "House": "House", "Techno": "Techno", "Trance": "Trance",
           "Dubstep": "Dubstep", "Ambient": "Ambient", "Pop": "Pop", "Rock": "Rock", "Metal": "Metal",
           "Punk": "Punk", "Jazz": "Jazz", "Blues": "Blues", "Country": "Country", "Folk": "Folk",
           "Classical": "Classical", "World": "World", "Experimental": "Experimental", "Funk": "Funk",
           "Alternative": "Alternative", "Children's": "Kids", "Spoken Word": "Spoken Word"}


class AudiusProvider(MusicProvider):
    key = "audius"
    name = "Audius"
    homepage = "https://audius.co"
    terms_url = "https://audius.co/legal/terms-of-use"
    description = "Artist-owned uploads from a decentralized platform whose open API permits streaming in third-party apps."
    attribution_html = 'Streams powered by <a href="https://audius.co">Audius</a>; rights remain with each artist.'
    capabilities = frozenset({Capability.search, Capability.genre, Capability.popular, Capability.playback})
    policy = ProviderPolicy(stream=True, requires_open_license=False, download_links=False,
                            notes="Off by default: anyone can upload, so re-uploads of commercial songs exist. Stream-only; "
                                  "no downloads; gated, app-restricted and film-song-looking tracks are excluded.")
    open_uploads = True

    def __init__(self) -> None:
        settings = get_settings()
        self.app_name = settings.audius_app_name
        self.http = ProviderClient(self.key, rate_per_second=5, burst=5, daily_quota=settings.audius_daily_quota)

    def _get(self, path: str, params: dict | None = None, *, cache: bool = True) -> list[dict] | dict:
        body = self.http.get_json(f"{API}{path}", {"app_name": self.app_name, **(params or {})}, cache=cache)
        if not isinstance(body, dict) or "data" not in body:
            raise ProviderError(self.key, "bad_response", "Unexpected Audius response")
        return body["data"]

    def _to_track(self, t: dict) -> ProviderTrack | None:
        if t.get("is_unlisted"):
            return None  # not meant to be discovered outside the artist's own links
        restrictions = []
        if t.get("is_delete") or t.get("is_available") is False:
            restrictions.append("Removed by the artist")
        if t.get("is_stream_gated") or t.get("stream_conditions"):
            restrictions.append("The artist requires a purchase or follow on Audius to stream this track")
        if t.get("is_streamable") is False:
            restrictions.append("Not streamable")
        if t.get("allowed_api_keys"):
            restrictions.append("The artist limits which apps may stream this track")
        lic = parse_license(t.get("license"))
        user = t.get("user") or {}
        plays = t.get("play_count") or 0
        try:
            released = date.fromisoformat(str(t.get("release_date"))[:10]) if t.get("release_date") else None
        except ValueError:
            released = None
        return ProviderTrack(
            provider=self.key, provider_track_id=str(t["id"]), title=t.get("title") or "Untitled",
            artist_name=user.get("name") or user.get("handle") or "Unknown artist",
            provider_artist_id=str(user.get("id")) if user.get("id") else None,
            artist_url=f"https://audius.co/{user['handle']}" if user.get("handle") else None,
            release_date=released, duration_ms=int(t["duration"]) * 1000 if t.get("duration") else None,
            artwork_url=(t.get("artwork") or {}).get("480x480"),
            tags=[t.get("genre") or "", *(str(t.get("tags") or "").split(","))],
            stream_url=f"{API}/tracks/{t['id']}/stream?app_name={self.app_name}",
            source_url=f"https://audius.co{t['permalink']}" if t.get("permalink") else None,
            license=lic if lic.is_open else PLATFORM_STREAM_ONLY,
            popularity=clamp01(math.log10(plays + 1) / 7) if plays else None,
            explicit=t.get("parental_warning_type") == "explicit", isrc=t.get("isrc"),
            restrictions=restrictions,
        )

    def _tracks(self, rows) -> list[ProviderTrack]:
        return [track for t in rows if (track := self._to_track(t)) is not None]

    def search(self, query, *, language=None, limit=20, offset=0):
        if language:
            raise ProviderError(self.key, "unsupported", "Audius has no language data")
        return self._tracks(self._get("/tracks/search", {"query": query, "limit": limit, "offset": offset}))

    def browse(self, *, language=None, genre=None, limit=20, offset=0):
        if language:
            raise ProviderError(self.key, "unsupported", "Audius has no language data")
        params = {"time": "month", "limit": limit, "offset": offset}
        if genre:
            if genre not in _GENRES:
                raise ProviderError(self.key, "unsupported", "Audius has no matching genre")
            params["genre"] = _GENRES[genre]
        return self._tracks(self._get("/tracks/trending", params))

    def fetch_track(self, provider_track_id):
        try:
            row = self._get(f"/tracks/{provider_track_id}", cache=False)
        except ProviderError as exc:
            if exc.kind == "not_found":
                return None
            raise
        return self._to_track(row) if isinstance(row, dict) else None
