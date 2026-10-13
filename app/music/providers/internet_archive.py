"""Internet Archive — individually verified, openly licensed audio (https://archive.org/developers).

The search index is only used to find candidates. Each item is then verified from its own metadata
record before any of its files are offered: it must carry a recognized Creative Commons or public-domain
license URL, must not be dark or access-restricted, and only public audio files are used. Items without
a license URL (most 78rpm and live-music collections) are never imported.
"""

import hashlib
import math
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from urllib.parse import quote

from app.core.config import get_settings
from app.music import languages as langs
from app.music.genres import CANONICAL
from app.music.http import ProviderClient, ProviderError
from app.music.licensing import ProviderPolicy, parse_license
from app.music.providers.base import Capability, MusicProvider, ProviderTrack, clamp01

SEARCH = "https://archive.org/advancedsearch.php"
METADATA = "https://archive.org/metadata/{}"
# Collections that are speech, not music.
_EXCLUDED_COLLECTIONS = ("librivoxaudio", "podcasts", "audio_podcast", "audio_religion", "radioprograms",
                         "audio_news", "audio_tech", "audio_bookspoetry", "oldtimeradio", "audio_foreign")
_EXCLUDED_SUBJECTS = ("sermon", "sermons", "podcast", "lecture", "audiobook", "speech", "interview", "talk",
                      "news", "preaching", "radio show", "discourse", "discourses", "pravachanam", "pravachan",
                      "upanyasam", "bhashyam", "commentary", "satsang", "bible study", "quran recitation")
_MUSIC_COLLECTIONS = ("netlabels", "audio_music", "opensource_audio_music", "freemusicarchive", "jamendo-albums",
                      "unlocked_recordings", "folksoundomy_music")
_MUSIC_SUBJECTS = ("music", "musica", "musique", "musik", "song", "songs", "album", "band", "instrumental", "singing",
                   "folk music", "film songs", "bhajan", "bhajans", "keerthana", "keertanalu", "kirtan", "carnatic",
                   "hindustani", "ghazal", "qawwali", "pop", "rock", "jazz", "hip hop", "rap", "electronic", "classical",
                   "devotional songs", "patalu", "geet", "geetham", "gaana", "gana", "lagu", "canción", "chanson", "lied")
# Best first. Lossless originals are skipped: too large to stream comfortably.
_FORMATS = ("VBR MP3", "320Kbps MP3", "256Kbps MP3", "192Kbps MP3", "160Kbps MP3", "128Kbps MP3", "MP3",
            "64Kbps MP3", "Ogg Vorbis")
_MAX_TRACKS_PER_ITEM = 25
_LUCENE_SPECIAL = re.compile(r'[+\-!(){}\[\]^"~*?:\\/&|]')


def _as_list(value) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(v) for v in value]
    return [s.strip() for s in str(value).split(";") if s.strip()]


def _duration_ms(value) -> int | None:
    if not value:
        return None
    try:
        if ":" in str(value):
            secs = 0.0
            for part in str(value).split(":"):
                secs = secs * 60 + float(part)
        else:
            secs = float(value)
    except ValueError:
        return None
    return int(secs * 1000) if secs > 0 else None


def _date(value) -> date | None:
    """'2015-11-20', '2015-11' or '2015' (a bare year becomes January 1st of that year)."""
    m = re.match(r"(\d{4})(?:-(\d{1,2}))?(?:-(\d{1,2}))?", str(value or "").strip())
    if not m:
        return None
    try:
        return date(int(m[1]), int(m[2] or 1), int(m[3] or 1))
    except ValueError:
        return None


def _track_id(identifier: str, filename: str) -> str:
    full = f"{identifier}/{filename}"
    if len(full) <= 128:
        return full
    return f"{identifier[:90]}#{hashlib.sha1(filename.encode()).hexdigest()[:24]}"


class InternetArchiveProvider(MusicProvider):
    key = "internet_archive"
    name = "Internet Archive"
    homepage = "https://archive.org/details/audio"
    terms_url = "https://archive.org/about/terms.php"
    description = "Netlabels, community uploads and archival recordings — only items with a verified open license."
    attribution_html = ('Recordings hosted by the <a href="https://archive.org">Internet Archive</a>; '
                        'each credited to its uploader under its stated license.')
    capabilities = frozenset({Capability.search, Capability.language, Capability.genre, Capability.popular,
                              Capability.playback})
    policy = ProviderPolicy(stream=True, requires_open_license=True, download_links=True,
                            notes="Only items whose own metadata carries a Creative Commons or public-domain license URL.")
    open_uploads = True

    def __init__(self) -> None:
        self.http = ProviderClient(self.key, rate_per_second=4, burst=4,
                                   daily_quota=get_settings().internet_archive_daily_quota)

    # --- query building ----------------------------------------------------------------------
    def _query(self, text: str | None = None, *, language: str | None = None, genre: str | None = None) -> str:
        parts = ["mediatype:audio", "licenseurl:*creativecommons.org*",
                 f"-collection:({' OR '.join(_EXCLUDED_COLLECTIONS)})",
                 "-subject:(" + " OR ".join(f'"{s}"' for s in _EXCLUDED_SUBJECTS) + ")",
                 "-access-restricted-item:true"]
        # Positive music signal: a music collection, or a music subject. Excluding speech alone isn't enough.
        parts.append(f"(collection:({' OR '.join(_MUSIC_COLLECTIONS)}) OR "
                     f"subject:({' OR '.join(f'{chr(34)}{s}{chr(34)}' for s in _MUSIC_SUBJECTS)}))")
        if text:
            cleaned = _LUCENE_SPECIAL.sub(" ", text).strip()
            if cleaned:
                parts.append(f"({cleaned})")
        if language:
            lang = langs.BY_CODE.get(language)
            if lang is None:
                raise ProviderError(self.key, "unsupported", "Unknown language")
            if language == langs.INSTRUMENTAL:
                parts.append('subject:(instrumental)')
            else:
                values = {lang.iso639_3, lang.code, f'"{lang.name}"'}
                parts.append(f"language:({' OR '.join(sorted(values))})")
        if genre:
            aliases = [genre.lower(), *CANONICAL.get(genre, ("", ()))[1][:6]]
            parts.append("subject:(" + " OR ".join(f'"{a}"' for a in aliases if a) + ")")
        return " AND ".join(parts)

    def _search_items(self, q: str, *, limit: int, offset: int, sort: str | None) -> list[dict]:
        """One page of items. An item holds several tracks, so a page of `limit` tracks needs ~limit/2 items;
        pages are counted in units of `limit` so successive offsets never skip results."""
        rows = max(4, min(limit // 2, 50))
        params = {"q": q, "fl[]": ["identifier", "downloads"], "rows": rows,
                  "page": offset // max(limit, 1) + 1, "output": "json"}
        if sort:
            params["sort[]"] = sort
        body = self.http.get_json(SEARCH, params)
        try:
            return body["response"]["docs"]
        except (KeyError, TypeError) as exc:
            raise ProviderError(self.key, "bad_response", "Unexpected search response") from exc

    # --- item verification -------------------------------------------------------------------
    def _item(self, identifier: str, *, fresh: bool = False) -> dict | None:
        try:
            return self.http.get_json(METADATA.format(quote(identifier)), cache=not fresh, ttl=timedelta(hours=24))
        except ProviderError as exc:
            if exc.kind == "not_found":
                return None
            raise

    def _item_tracks(self, identifier: str, popularity: float | None, item: dict | None = None) -> list[ProviderTrack]:
        item = item if item is not None else self._item(identifier)
        if not item or not item.get("metadata") or item.get("is_dark"):
            return []
        meta = item["metadata"]
        lic = parse_license(meta.get("licenseurl"))
        restrictions = []
        if str(meta.get("access-restricted-item", "")).lower() == "true":
            restrictions.append("Access to this item is restricted by the Internet Archive")
        album = str(meta.get("title") or identifier)
        album_artist = (_as_list(meta.get("creator")) or ["Unknown artist"])[0]
        tags = _as_list(meta.get("subject"))
        language = (_as_list(meta.get("language")) or [None])[0]

        # Group derivatives with their original and pick the best streamable format per recording.
        files = [f for f in item.get("files") or [] if str(f.get("private", "")).lower() != "true"]
        by_name = {f["name"]: f for f in files}
        best: dict[str, tuple[int, dict]] = {}
        for f in files:
            fmt = f.get("format")
            if fmt not in _FORMATS:
                continue
            group = f.get("original") if f.get("source") == "derivative" and f.get("original") else f["name"]
            rank = _FORMATS.index(fmt)
            if group not in best or rank < best[group][0]:
                best[group] = (rank, f)

        tracks = []
        # Tags (title, creator, track) usually live on the original upload, not on the derived MP3.
        chosen = [(f, {**by_name.get(group, {}), **{k: v for k, v in f.items() if v}}) for group, (_, f) in best.items()]
        for f, info in sorted(chosen, key=lambda fi: (str(fi[1].get("track") or "").zfill(4), fi[0]["name"])):
            url = f"https://archive.org/download/{quote(identifier)}/{quote(f['name'])}"
            title = info.get("title") or re.sub(r"\.[^.]+$", "", f["name"].rsplit("/", 1)[-1]).replace("_", " ").strip()
            if re.fullmatch(r"[\d\s._-]*", title):  # "03" says nothing on its own
                title = f"{album} ({title})" if title else album
            tracks.append(ProviderTrack(
                provider=self.key, provider_track_id=_track_id(identifier, f["name"]), title=title[:200],
                artist_name=info.get("creator") or info.get("artist") or album_artist,
                provider_artist_id=None, album_title=album[:200], provider_album_id=identifier[:128],
                album_url=f"https://archive.org/details/{identifier}", release_date=_date(meta.get("date") or meta.get("year")),
                duration_ms=_duration_ms(info.get("length")), artwork_url=f"https://archive.org/services/img/{quote(identifier)}",
                language=language, tags=tags, stream_url=url, download_url=url, provider_download_allowed=True,
                source_url=f"https://archive.org/details/{identifier}", license=lic, popularity=popularity,
                restrictions=list(restrictions),
            ))
            if len(tracks) >= _MAX_TRACKS_PER_ITEM:
                break
        return tracks

    def _collect(self, docs: list[dict], limit: int) -> list[ProviderTrack]:
        def load(doc: dict) -> list[ProviderTrack]:
            downloads = doc.get("downloads") or 0
            popularity = clamp01(math.log10(downloads + 1) / 6) if downloads else None
            try:
                return self._item_tracks(doc["identifier"], popularity)
            except ProviderError:
                return []  # one bad item never sinks the batch

        with ThreadPoolExecutor(max_workers=4) as pool:
            batches = list(pool.map(load, docs))
        tracks: list[ProviderTrack] = []
        for batch in batches:
            tracks.extend(batch)
        return tracks[: max(limit, 1) * 2]

    # --- MusicProvider -----------------------------------------------------------------------
    def search(self, query, *, language=None, limit=20, offset=0):
        docs = self._search_items(self._query(query, language=language), limit=limit, offset=offset, sort=None)
        return self._collect(docs, limit)

    def browse(self, *, language=None, genre=None, limit=20, offset=0):
        docs = self._search_items(self._query(language=language, genre=genre), limit=limit, offset=offset,
                                  sort="downloads desc")
        return self._collect(docs, limit)

    def fetch_track(self, provider_track_id):
        identifier, sep, name = provider_track_id.partition("/")
        if not sep:
            identifier = provider_track_id.split("#", 1)[0]
        item = self._item(identifier, fresh=True)
        for track in self._item_tracks(identifier, None, item=item):
            if track.provider_track_id == provider_track_id:
                return track
        return None
