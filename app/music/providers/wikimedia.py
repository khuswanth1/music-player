"""Wikimedia Commons - freely licensed recordings from around the world (https://commons.wikimedia.org).

Commons holds folk songs, field recordings, classical performances and anthems from nearly every country, each file
with its own stated license. Like every open-upload source, a track is only playable when its license is a recognized
Creative Commons or public-domain one and passes the usual screening. Speech, pronunciations, sound effects, MIDI and
anything under 45 seconds are dropped. No key is needed; Wikimedia asks for a descriptive User-Agent (MUSIC_USER_AGENT).
"""

import html
import re
from datetime import date

from app.core.config import get_settings
from app.music import languages as langs
from app.music.genres import CANONICAL
from app.music.http import ProviderClient, ProviderError
from app.music.licensing import ProviderPolicy, attribution_line, parse_license, with_version
from app.music.providers.base import Capability, MusicProvider, ProviderTrack

API = "https://commons.wikimedia.org/w/api.php"
_MIN_DURATION_S = 45
_PLAYABLE_MIME = {
    "audio/ogg",
    "application/ogg",
    "audio/mpeg",
    "audio/mp3",
    "audio/wav",
    "audio/x-wav",
    "audio/flac",
    "audio/opus",
    "audio/webm",
}
_NOT_MUSIC = re.compile(
    r"pronunciation|spoken|speech|sound effect|sound effects|noise|audiobook|lecture|interview|podcast|"
    r"ringtone|midi|voice|radio broadcast|news|sermon|recitation of|wikipedia",
    re.I,
)
_TAG = re.compile(r"<[^>]+>")
# "Audio files in Hindi" says what language is sung or spoken. ("... with closed captioning in Hindi" is a subtitle
# track, not the audio, so the pattern is anchored to avoid it.)
_LANG_CATEGORY = re.compile(r"^(?:Audio files|Songs|Vocal music|Music) in ([A-Za-z' -]+)$")
_CC_NAME = re.compile(r"^CC[ -](BY(?:-[A-Z]{2})*)[ -]?([\d.]+)?", re.I)
_PROPS = {
    "action": "query",
    "format": "json",
    "formatversion": "2",
    "prop": "imageinfo",
    "iiprop": "url|mime|size|extmetadata",
    "iiextmetadatafilter": "LicenseShortName|LicenseUrl|Artist|ObjectName|DateTimeOriginal|Categories|Credit",
}


def _plain(value: str | None) -> str:
    return re.sub(r"\s+", " ", html.unescape(_TAG.sub(" ", value or ""))).strip()


def _license(meta: dict):
    url = (meta.get("LicenseUrl") or {}).get("value")
    lic = parse_license(url)
    if lic.is_open:
        return with_version(lic, lic.version)
    name = (meta.get("LicenseShortName") or {}).get("value") or ""
    m = _CC_NAME.match(name.strip())
    if m:
        return with_version(parse_license(m.group(1).lower()), m.group(2))
    return parse_license(name)  # "CC0" / "Public domain"; anything else stays unverified (and unplayable)


def _year(value: str | None) -> date | None:
    m = re.search(r"\b(1[5-9]\d\d|20\d\d)\b", value or "")
    return date(int(m.group(1)), 1, 1) if m else None


class WikimediaCommonsProvider(MusicProvider):
    key = "wikimedia_commons"
    name = "Wikimedia Commons"
    homepage = "https://commons.wikimedia.org"
    terms_url = "https://foundation.wikimedia.org/wiki/Policy:Terms_of_Use"
    description = "Folk, classical and field recordings from around the world, each under its own open license."
    attribution_html = 'Recordings from <a href="https://commons.wikimedia.org">Wikimedia Commons</a>, credited to their creators.'
    capabilities = frozenset({Capability.search, Capability.language, Capability.genre, Capability.playback})
    policy = ProviderPolicy(
        stream=True,
        requires_open_license=True,
        download_links=True,
        notes="Only files whose own metadata states a Creative Commons or public-domain license.",
    )
    open_uploads = True  # anyone can upload: screened like the other open platforms

    def __init__(self) -> None:
        self.http = ProviderClient(self.key, rate_per_second=4, burst=4, daily_quota=get_settings().wikimedia_daily_quota)

    def _to_track(self, page: dict) -> ProviderTrack | None:
        info = (page.get("imageinfo") or [None])[0]
        if not info or info.get("mime") not in _PLAYABLE_MIME or not info.get("url"):
            return None
        duration = info.get("duration")
        if not duration or duration < _MIN_DURATION_S:
            return None
        meta = info.get("extmetadata") or {}
        categories = (meta.get("Categories") or {}).get("value") or ""
        title_file = re.sub(r"\.\w+$", "", page["title"].removeprefix("File:")).replace("_", " ")
        if _NOT_MUSIC.search(categories) or _NOT_MUSIC.search(title_file):
            return None
        title = _plain((meta.get("ObjectName") or {}).get("value")) or title_file
        artist = _plain((meta.get("Artist") or {}).get("value")) or "Unknown artist"
        lic = _license(meta)
        tags = [c for c in categories.split("|") if c]
        language = next((code for c in tags if (m := _LANG_CATEGORY.match(c)) and (code := langs.normalize(m.group(1)))), None)
        return ProviderTrack(
            provider=self.key,
            provider_track_id=str(page["pageid"]),
            title=title[:200],
            artist_name=artist[:120],
            duration_ms=int(duration * 1000),
            release_date=_year((meta.get("DateTimeOriginal") or {}).get("value")),
            tags=tags,
            language=language,
            language_source="tag",
            stream_url=info["url"],
            download_url=info["url"],
            provider_download_allowed=True,
            source_url=info.get("descriptionurl") or f"https://commons.wikimedia.org/?curid={page['pageid']}",
            license=lic,
            attribution=attribution_line(title, artist, lic, self.name),
        )

    def _query(self, text: str, limit: int, offset: int) -> list[dict]:
        params = {
            **_PROPS,
            "generator": "search",
            "gsrsearch": f"{text} filetype:audio",
            "gsrnamespace": 6,
            "gsrlimit": min(limit, 50),
            "gsroffset": offset,
        }
        body = self.http.get_json(API, params)
        return (body.get("query") or {}).get("pages") or []

    def search(self, query: str, *, language: str | None = None, limit: int = 20, offset: int = 0) -> list[ProviderTrack]:
        text = query
        if language:
            lang = langs.BY_CODE.get(language)
            if lang is None:
                raise ProviderError(self.key, "unsupported", "Unknown language")
            text = f"{query} {lang.name}".strip()
        pages = sorted(self._query(text, limit, offset), key=lambda p: p.get("index", 0))
        return [t for p in pages if (t := self._to_track(p)) is not None]

    def browse(self, *, language: str | None = None, genre: str | None = None, limit: int = 20, offset: int = 0) -> list[ProviderTrack]:
        if not language and not genre:
            raise ProviderError(self.key, "unsupported", "Browsing needs a language or a genre")
        if language and language not in langs.BY_CODE:
            raise ProviderError(self.key, "unsupported", "Unknown language")
        parts = []
        if language:
            parts.append(langs.BY_CODE[language].name)
        if genre:
            parts.append(CANONICAL.get(genre, ("", (genre.lower(),)))[1][0] if CANONICAL.get(genre, ("", ()))[1] else genre.lower())
        text = " ".join(parts) + " music"
        found = self.search(text, limit=limit, offset=offset)
        if language:  # keep only what a category or the script says is in this language
            found = [t for t in found if (t.language or langs.detect_from_script(t.title, t.artist_name)) == language]
        return found

    def fetch_track(self, provider_track_id: str) -> ProviderTrack | None:
        body = self.http.get_json(API, {**_PROPS, "pageids": provider_track_id}, cache=False)
        pages = (body.get("query") or {}).get("pages") or []
        return self._to_track(pages[0]) if pages and not pages[0].get("missing") else None
