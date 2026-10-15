"""Real photos of singers, from Wikipedia's lead images (freely licensed, served from upload.wikimedia.org).

Artwork on a song or album is not a picture of the singer, so the onboarding and artist pages look up a portrait by
name. A page only counts when its title matches the name and its short description says it is about a musician, so
"Pushpa" the film or a namesake in another profession is never shown as the singer.
"""

import logging
import re
import threading
import time

import httpx

log = logging.getLogger(__name__)

_API = "https://en.wikipedia.org/w/api.php"
_UA = "Wavely/1.0 (music streaming app; artist portraits from Wikipedia)"
_MUSICIAN = re.compile(r"singer|vocalist|musician|playback|composer|songwriter|rapper|band|ghazal|qawwali|bhajan|artist", re.I)
_NEGATIVE_TTL = 24 * 3600
_cache: dict[str, tuple[str | None, float]] = {}  # lowercased name -> (url or None, expires)
_lock = threading.Lock()
_transport: httpx.BaseTransport | None = None  # tests inject httpx.MockTransport here


def set_transport(transport: httpx.BaseTransport | None) -> None:
    global _transport
    _transport = transport


def search_name(name: str) -> str:
    """The lead singer's name from a credit like "A.R. Rahman & Arijit Singh" or "Sagar, M.M. Manasi feat. X"."""
    name = re.sub(r"\(.*?\)|\[.*?\]", "", name or "")
    name = re.split(r"\s*(?:,|&|\band\b|\bfeat\.?\b|\bft\.?\b|\bx\b|;|/)\s*", name, maxsplit=1, flags=re.I)[0]
    return re.sub(r"\s+", " ", name).strip()


def _tokens(text: str) -> set[str]:
    return {t for t in re.split(r"[^\w]+", text.lower()) if len(t) > 1}


def _matches(title: str, wanted: str) -> bool:
    """Every word of the credited name appears in the page title (so "Kishore Kumar" matches "Kishore Kumar")."""
    want = _tokens(wanted)
    return bool(want) and want <= _tokens(title)


def portrait_url(name: str) -> str | None:
    """A portrait thumbnail for a singer, or None. Never raises: a failed lookup just means no photo."""
    wanted = search_name(name)
    if len(wanted) < 3 or wanted.startswith(("#", "@")):
        return None
    key = wanted.lower()
    with _lock:
        hit = _cache.get(key)
        if hit and hit[1] > time.time():
            return hit[0]
    url: str | None = None
    try:
        with httpx.Client(timeout=6, headers={"User-Agent": _UA}, transport=_transport) as client:
            res = client.get(_API, params={
                "action": "query", "format": "json", "formatversion": 2, "generator": "search", "gsrlimit": 6,
                "gsrsearch": f"{wanted} singer musician", "prop": "pageimages|description", "piprop": "thumbnail",
                "pithumbsize": 320, "pilicense": "any"})
            res.raise_for_status()
            pages = sorted(res.json().get("query", {}).get("pages", []), key=lambda p: p.get("index", 99))
        for page in pages:
            thumb = (page.get("thumbnail") or {}).get("source")
            if thumb and _matches(page.get("title", ""), wanted) and _MUSICIAN.search(page.get("description") or ""):
                url = thumb
                break
    except (httpx.HTTPError, ValueError) as exc:
        log.info("artist_photo.lookup_failed", extra={"name": wanted, "error": str(exc)})
        return None  # transient: try again next time rather than caching a miss
    with _lock:
        _cache[key] = (url, time.time() + (_NEGATIVE_TTL if url is None else 7 * _NEGATIVE_TTL))
    return url
