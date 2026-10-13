"""ccMixter — a Creative Commons remix community (https://ccmixter.org/query-api).

Every upload carries a license URL. Uploads under the retired Sampling licenses classify as unknown and
are therefore never streamed. ccMixter has no language field; a language is taken only from a tag that
is exactly a language name ("hindi", "japanese"), and recorded as tag-derived.
"""

import math
from datetime import datetime

from app.core.config import get_settings
from app.music import languages as langs
from app.music.genres import CANONICAL
from app.music.http import ProviderClient, ProviderError
from app.music.licensing import ProviderPolicy, parse_license
from app.music.providers.base import Capability, MusicProvider, ProviderTrack, clamp01

API = "https://ccmixter.org/api/query"


def _duration_ms(ps: str | None) -> int | None:
    if not ps:
        return None
    try:
        secs = 0
        for part in str(ps).split(":"):
            secs = secs * 60 + int(part)
    except ValueError:
        return None
    return secs * 1000 if secs > 0 else None


def _tag_language(tags: list[str]) -> str | None:
    for tag in tags:
        tag = tag.replace("_", " ")
        code = langs.normalize(tag) if len(tag) >= 4 else None
        if code and tag.casefold() == langs.BY_CODE[code].name.casefold():
            return code
    return None


class CcMixterProvider(MusicProvider):
    key = "ccmixter"
    name = "ccMixter"
    homepage = "https://ccmixter.org"
    terms_url = "https://ccmixter.org/terms"
    description = "Remixes, a cappellas and instrumentals shared under Creative Commons licenses."
    attribution_html = 'Remixes from <a href="https://ccmixter.org">ccMixter</a>, credited to each artist under their license.'
    capabilities = frozenset({Capability.search, Capability.language, Capability.genre, Capability.popular,
                              Capability.playback})
    policy = ProviderPolicy(stream=True, requires_open_license=True, download_links=True)

    def __init__(self) -> None:
        self.http = ProviderClient(self.key, rate_per_second=2, burst=2, daily_quota=get_settings().ccmixter_daily_quota)

    def _query(self, params: dict) -> list[dict]:
        body = self.http.get_json(API, {"f": "json", **params})
        if not isinstance(body, list):
            raise ProviderError(self.key, "bad_response", "Unexpected ccMixter response")
        return body

    def _to_track(self, u: dict) -> ProviderTrack | None:
        audio = next((f for f in u.get("files") or []
                      if (f.get("file_format_info") or {}).get("media-type") == "audio"
                      and (f.get("file_format_info") or {}).get("mime_type") in ("audio/mpeg", "audio/ogg")), None)
        if audio is None:
            return None  # sample packs and stems-only uploads
        extra = u.get("upload_extra") or {}
        tags = [t.strip() for t in str(extra.get("usertags") or "").split(",") if t.strip()]
        language = _tag_language(tags)
        try:
            released = datetime.strptime(u.get("upload_date_format", ""), "%a, %b %d, %Y @ %I:%M %p").date()
        except ValueError:
            released = None
        scores = u.get("upload_num_scores") or 0
        return ProviderTrack(
            provider=self.key, provider_track_id=str(u["upload_id"]), title=(u.get("upload_name") or "Untitled")[:200],
            artist_name=u.get("user_real_name") or u.get("user_name") or "Unknown artist",
            provider_artist_id=u.get("user_name"), artist_url=u.get("artist_page_url"), release_date=released,
            duration_ms=_duration_ms((audio.get("file_format_info") or {}).get("ps")),
            language=language, language_source="tag", tags=tags,
            stream_url=audio.get("download_url"), download_url=audio.get("download_url"), provider_download_allowed=True,
            source_url=u.get("file_page_url"), license=parse_license(u.get("license_url") or u.get("license_name")),
            popularity=clamp01(math.log10(scores + 1) / 3) if scores else None,
            explicit=bool(extra.get("nsfw")),
        )

    def _tracks(self, rows: list[dict]) -> list[ProviderTrack]:
        return [t for u in rows if (t := self._to_track(u)) is not None]

    def search(self, query, *, language=None, limit=20, offset=0):
        params = {"search": query, "search_type": "all", "limit": limit, "offset": offset, "sort": "rank"}
        if language:
            params["tags"] = self._language_tag(language)
        return self._tracks(self._query(params))

    def browse(self, *, language=None, genre=None, limit=20, offset=0):
        tags = []
        if language:
            tags.append(self._language_tag(language))
        if genre:
            tags.append(next(iter(CANONICAL.get(genre, ("", (genre.lower(),)))[1]), genre.lower()).replace(" ", "_"))
        params = {"limit": limit, "offset": offset, "sort": "rank", "tags": "+".join(tags) or None}
        return self._tracks(self._query(params))

    def fetch_track(self, provider_track_id):
        rows = self.http.get_json(API, {"f": "json", "ids": provider_track_id}, cache=False)
        return self._to_track(rows[0]) if isinstance(rows, list) and rows else None

    def _language_tag(self, language: str) -> str:
        if language == langs.INSTRUMENTAL:
            return "instrumental"
        lang = langs.BY_CODE.get(language)
        if lang is None:
            raise ProviderError(self.key, "unsupported", "Unknown language")
        return lang.name.lower().replace(" ", "_")
