"""Full audio stream resolver for tracks with short previews or external catalog references.

Finds and extracts high-quality full-length audio streams using yt-dlp, with in-memory caching.
"""

import logging
import re
import threading
import time

import yt_dlp

log = logging.getLogger(__name__)

# In-memory cache: cache_key -> (stream_url, expire_timestamp, duration_seconds)
_STREAM_CACHE: dict[str, tuple[str, float, int | None]] = {}
_NEGATIVE_TTL = 10 * 60  # don't re-run a failed lookup on every click
_LOCKS: dict[str, threading.Lock] = {}
_LOCKS_GUARD = threading.Lock()
_CACHE_TTL = 5 * 3600  # 5 hours (Google Video URLs typically expire after 6 hours)

_YDL_OPTS = {
    'format': 'bestaudio[ext=m4a]/bestaudio/best',
    'default_search': 'ytsearch1',  # only the top hit is used; searching 3 triples the wait
    'quiet': True,
    'no_warnings': True,
    'skip_download': True,
    'nocheckcertificate': True,
    'noplaylist': True,
    'socket_timeout': 10,
    'extract_flat': False,
    'ignoreerrors': True,
}


def _cache_key(title: str, artist: str | None) -> str:
    t = (title or "").strip().lower()
    a = (artist or "").strip().lower()
    return f"{a}::{t}"


def resolve_full_stream(title: str, artist: str | None = None, fallback_url: str | None = None) -> tuple[str, int | None]:
    """Resolves a full-length audio stream URL for a given track title and artist.

    Returns (stream_url, duration_seconds). Falls back to fallback_url on failure.
    """
    if not title:
        return fallback_url or "", None

    key = _cache_key(title, artist)
    # One lookup per song at a time: a hover prefetch, the click and the look-ahead all share the same result.
    with _LOCKS_GUARD:
        lock = _LOCKS.setdefault(key, threading.Lock())
    with lock:
        return _resolve(key, title, artist, fallback_url)


def _resolve(key: str, title: str, artist: str | None, fallback_url: str | None) -> tuple[str, int | None]:
    now = time.time()
    if key in _STREAM_CACHE:
        url, exp, dur = _STREAM_CACHE[key]
        if exp > now:
            return (url or fallback_url or ""), dur

    clean_artist = (artist or "").split(",")[0].split("&")[0].split("feat")[0].strip()
    clean_title = re.sub(r"[\(\[][^\)\]]*(?:soundtrack|from|ost|version|mix|original)[^\)\]]*[\)\]]", "", title, flags=re.I)
    clean_title = clean_title.split("[")[0].split("(")[0].strip() or title.strip()

    if clean_artist and clean_artist.lower() in clean_title.lower():
        query = f"{clean_title} audio"
    elif clean_artist:
        query = f"{clean_title} {clean_artist} audio"
    else:
        query = f"{clean_title} audio"

    try:
        with yt_dlp.YoutubeDL(_YDL_OPTS) as ydl:
            info = ydl.extract_info(query, download=False)
            if not info:
                _STREAM_CACHE[key] = ("", now + _NEGATIVE_TTL, None)
                return fallback_url or "", None
            entries = info.get('entries') if isinstance(info, dict) and 'entries' in info else [info]
            for entry in (entries or []):
                if entry and isinstance(entry, dict) and entry.get('url'):
                    url = entry.get('url')
                    dur = entry.get('duration')
                    _STREAM_CACHE[key] = (url, now + _CACHE_TTL, dur)
                    return url, dur
    except Exception as exc:
        log.warning("Full stream resolution failed for '%s - %s': %s", artist, title, exc)

    _STREAM_CACHE[key] = ("", now + _NEGATIVE_TTL, None)

    return fallback_url or "", None




def is_cached(title: str, artist: str | None = None) -> bool:
    """True when a full stream (or a recent failed lookup) is already known, so resolving again costs nothing."""
    entry = _STREAM_CACHE.get(_cache_key(title, artist))
    return bool(entry and entry[1] > time.time())


def warm(title: str, artist: str | None = None, fallback_url: str | None = None) -> None:
    """Resolve in a background thread so the caller can answer right away (a no-op if it is already cached)."""
    if not title or is_cached(title, artist):
        return
    threading.Thread(target=resolve_full_stream, args=(title, artist, fallback_url), daemon=True).start()
