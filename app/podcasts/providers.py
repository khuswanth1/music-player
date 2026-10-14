"""Podcast discovery providers. Each returns plain dicts in one shape (see `podcast_dict`/`episode_dict`).

Podcast ids are composite: `<provider>:<provider id>` (e.g. `itunes:121493675`). Providers:
 * itunes        - Apple's public search/lookup API; no key. Gives the publisher's RSS feed URL.
 * podcastindex  - needs PODCAST_INDEX_KEY/SECRET (free). Open index with language metadata.
 * listennotes   - needs LISTEN_NOTES_API_KEY (optional; strict free-plan quota).
Episodes come from the publisher's RSS feed (authorized enclosure URLs) whenever a feed URL is known.
"""

import hashlib
import ipaddress
import socket
import time
from datetime import UTC, datetime
from urllib.parse import urlparse

from app.core.config import get_settings
from app.music.http import ProviderClient, ProviderError
from app.podcasts import rss

ITUNES = "https://itunes.apple.com"
PODCAST_INDEX = "https://api.podcastindex.org/api/1.0"
LISTEN_NOTES = "https://listen-api.listennotes.com/api/v2"

# Apple Podcasts category (genre) ids, from Apple's public taxonomy.
CATEGORY_CHOICES = [
    ("1303", "Comedy"),
    ("1489", "News"),
    ("1487", "History"),
    ("1318", "Technology"),
    ("1321", "Business"),
    ("1488", "True Crime"),
    ("1324", "Society & Culture"),
    ("1533", "Science"),
    ("1545", "Sports"),
    ("1310", "Music"),
    ("1512", "Health & Fitness"),
    ("1304", "Education"),
    ("1301", "Arts"),
    ("1305", "Kids & Family"),
    ("1309", "TV & Film"),
    ("1314", "Religion & Spirituality"),
]

# Listen Notes names languages in English.
_LN_LANGUAGES = {
    "en": "English",
    "es": "Spanish",
    "fr": "French",
    "de": "German",
    "ja": "Japanese",
    "ko": "Korean",
    "hi": "Hindi",
    "ta": "Tamil",
    "te": "Telugu",
    "pt": "Portuguese",
    "ar": "Arabic",
    "zh": "Chinese",
}


def split_id(podcast_id: str) -> tuple[str, str]:
    provider, _, pid = podcast_id.partition(":")
    if not provider or not pid:
        raise ProviderError("podcasts", "bad_response", "Malformed podcast id")
    return provider, pid


def public_http_url(url: str | None) -> bool:
    """Reject non-http(s) and private/loopback/link-local hosts before fetching a publisher-supplied URL."""
    if not url:
        return False
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        return False
    try:
        infos = socket.getaddrinfo(parsed.hostname, parsed.port or (443 if parsed.scheme == "https" else 80))
    except OSError:
        return False
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_reserved:
            return False
    return True


def podcast_dict(provider: str, pid, **kw) -> dict:
    base = {
        "id": f"{provider}:{pid}",
        "provider": provider,
        "provider_id": str(pid),
        "title": "",
        "publisher": None,
        "description": None,
        "image_url": None,
        "feed_url": None,
        "website": None,
        "language": None,
        "storefront_country": None,
        "categories": [],
        "episode_count": None,
        "latest_episode_at": None,
        "explicit": False,
        "source_url": None,
    }
    base.update({k: v for k, v in kw.items() if v is not None})
    return base


def episode_dict(podcast: dict, e: dict) -> dict:
    return {
        "id": f"{podcast['id']}#{e['key']}",
        "podcast_id": podcast["id"],
        "provider": podcast["provider"],
        "podcast_title": podcast["title"],
        "title": e["title"],
        "description": e.get("description"),
        "audio_url": e.get("audio_url"),
        "mime_type": e.get("mime_type"),
        "duration_s": e.get("duration_s"),
        "published_at": e.get("published_at"),
        "image_url": e.get("image_url") or podcast.get("image_url"),
        "season": e.get("season"),
        "episode": e.get("episode"),
        "explicit": e.get("explicit", False),
        "source_url": e.get("source_url"),
        "playable": bool(e.get("audio_url")),
    }


def _dt(value) -> datetime | None:
    if not value:
        return None
    try:
        if isinstance(value, (int, float)):
            return datetime.fromtimestamp(value, UTC)
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError, OSError:
        return None


def _http_or_none(url) -> str | None:
    return url if isinstance(url, str) and url.startswith(("http://", "https://")) else None


class ITunesPodcasts:
    key = "itunes"
    name = "Apple Podcasts (iTunes Search)"

    def __init__(self) -> None:
        self.http = ProviderClient("itunes_podcast", rate_per_second=3, burst=5, daily_quota=get_settings().itunes_podcast_daily_quota)

    def is_configured(self) -> bool:
        return True

    def _podcast(self, r: dict) -> dict | None:
        pid = r.get("collectionId") or r.get("trackId")
        if not pid:
            return None
        genres = [g for g in (r.get("genres") or []) if isinstance(g, str)]
        return podcast_dict(
            self.key,
            pid,
            title=r.get("collectionName") or r.get("trackName") or "Untitled",
            publisher=r.get("artistName"),
            image_url=r.get("artworkUrl600") or r.get("artworkUrl100"),
            feed_url=r.get("feedUrl"),
            storefront_country=(r.get("country") or "")[:3] or None,
            categories=genres,
            episode_count=r.get("trackCount"),
            latest_episode_at=_dt(r.get("releaseDate")),
            explicit=r.get("collectionExplicitness") == "explicit",
            source_url=r.get("collectionViewUrl"),
        )

    def search(self, q: str, *, country: str | None = None, category: str | None = None, limit: int = 25, offset: int = 0) -> list[dict]:
        params = {
            "term": q,
            "media": "podcast",
            "entity": "podcast",
            "limit": min(limit, 50),
            "offset": offset,
            "country": (country or "US").upper(),
            "genreId": category,
        }
        body = self.http.get_json(f"{ITUNES}/search", params)
        return [p for p in (self._podcast(r) for r in body.get("results", [])) if p]

    def search_episodes(self, q: str, *, country: str | None = None, limit: int = 20) -> list[dict]:
        params = {"term": q, "media": "podcast", "entity": "podcastEpisode", "limit": min(limit, 50), "country": (country or "US").upper()}
        body = self.http.get_json(f"{ITUNES}/search", params)
        out = []
        for r in body.get("results", []):
            if r.get("kind") != "podcast-episode":
                continue
            podcast = podcast_dict(
                self.key,
                r.get("collectionId"),
                title=r.get("collectionName") or "",
                feed_url=r.get("feedUrl"),
                image_url=r.get("artworkUrl600"),
            )
            audio = _http_or_none(r.get("episodeUrl"))
            out.append(
                episode_dict(
                    podcast,
                    {
                        "key": rss.episode_key(r.get("episodeGuid"), audio),
                        "title": r.get("trackName") or "Untitled episode",
                        "description": rss.clean_html(r.get("description")),
                        "audio_url": audio,
                        "duration_s": (r.get("trackTimeMillis") or 0) // 1000 or None,
                        "published_at": _dt(r.get("releaseDate")),
                        "image_url": r.get("artworkUrl600"),
                        "source_url": r.get("trackViewUrl"),
                    },
                )
            )
        return out

    def get(self, pid: str) -> dict | None:
        body = self.http.get_json(f"{ITUNES}/lookup", {"id": pid, "entity": "podcast"})
        for r in body.get("results", []):
            if str(r.get("collectionId")) == pid or str(r.get("trackId")) == pid:
                return self._podcast(r)
        return None


class PodcastIndex:
    key = "podcastindex"
    name = "Podcast Index"

    def __init__(self) -> None:
        self.http = ProviderClient("podcastindex", rate_per_second=2, burst=4, daily_quota=get_settings().podcast_index_daily_quota)

    def is_configured(self) -> bool:
        s = get_settings()
        return bool(s.podcast_index_key and s.podcast_index_secret)

    def _headers(self) -> dict:
        s = get_settings()
        ts = str(int(time.time()))
        digest = hashlib.sha1(f"{s.podcast_index_key}{s.podcast_index_secret}{ts}".encode()).hexdigest()  # noqa: S324 (the API's scheme)
        return {"X-Auth-Date": ts, "X-Auth-Key": s.podcast_index_key, "Authorization": digest, "User-Agent": s.music_user_agent}

    def _get(self, path: str, params: dict) -> dict:
        if not self.is_configured():
            raise ProviderError(self.key, "not_configured", "Set PODCAST_INDEX_KEY and PODCAST_INDEX_SECRET")
        return self.http.get_json(f"{PODCAST_INDEX}{path}", params, headers=self._headers())

    def _podcast(self, r: dict) -> dict:
        cats = list(r["categories"].values()) if isinstance(r.get("categories"), dict) else []
        return podcast_dict(
            self.key,
            r.get("id"),
            title=r.get("title") or "Untitled",
            publisher=r.get("author") or r.get("ownerName"),
            description=rss.clean_html(r.get("description")),
            image_url=r.get("artwork") or r.get("image") or None,
            feed_url=r.get("url"),
            website=r.get("link") or None,
            language=r.get("language") or None,
            categories=cats,
            episode_count=r.get("episodeCount"),
            latest_episode_at=_dt(r.get("newestItemPubdate") or r.get("lastUpdateTime")),
            explicit=bool(r.get("explicit")),
            source_url=r.get("link") or None,
        )

    def search(self, q: str, *, limit: int = 25) -> list[dict]:
        body = self._get("/search/byterm", {"q": q, "max": min(limit, 50)})
        return [self._podcast(r) for r in body.get("feeds", []) if r.get("id")]

    def trending(self, *, language: str | None = None, category: str | None = None, limit: int = 25) -> list[dict]:
        body = self._get("/podcasts/trending", {"max": min(limit, 50), "lang": language, "cat": category})
        return [self._podcast(r) for r in body.get("feeds", []) if r.get("id")]

    def get(self, pid: str) -> dict | None:
        feed = self._get("/podcasts/byfeedid", {"id": pid}).get("feed")
        return self._podcast(feed) if feed else None

    def episodes(self, pid: str, limit: int = 50) -> list[dict]:
        body = self._get("/episodes/byfeedid", {"id": pid, "max": min(limit, 100)})
        return [
            {
                "key": rss.episode_key(str(e.get("guid") or ""), e.get("enclosureUrl")),
                "title": e.get("title") or "Untitled episode",
                "description": rss.clean_html(e.get("description")),
                "audio_url": _http_or_none(e.get("enclosureUrl")),
                "mime_type": e.get("enclosureType") or None,
                "duration_s": e.get("duration") or None,
                "published_at": _dt(e.get("datePublished")),
                "image_url": e.get("image") or e.get("feedImage") or None,
                "season": e.get("season") or None,
                "episode": e.get("episode") or None,
                "source_url": e.get("link") or None,
            }
            for e in body.get("items", [])
        ]


class ListenNotes:
    key = "listennotes"
    name = "Listen Notes"

    def __init__(self) -> None:
        self.http = ProviderClient("listennotes", rate_per_second=1, burst=2, daily_quota=get_settings().listen_notes_daily_quota)

    def is_configured(self) -> bool:
        return bool(get_settings().listen_notes_api_key)

    def _get(self, path: str, params: dict) -> dict:
        if not self.is_configured():
            raise ProviderError(self.key, "not_configured", "Set LISTEN_NOTES_API_KEY")
        return self.http.get_json(f"{LISTEN_NOTES}{path}", params, headers={"X-ListenAPI-Key": get_settings().listen_notes_api_key})

    @staticmethod
    def _language(name: str | None) -> str | None:
        return next((code for code, n in _LN_LANGUAGES.items() if n == (name or "").strip()), None)

    def _podcast(self, r: dict) -> dict:
        return podcast_dict(
            self.key,
            r.get("id"),
            title=r.get("title_original") or r.get("title") or "Untitled",
            publisher=r.get("publisher_original") or r.get("publisher"),
            description=rss.clean_html(r.get("description_original") or r.get("description")),
            image_url=r.get("image") or r.get("thumbnail"),
            website=r.get("website") or None,
            language=self._language(r.get("language")),
            episode_count=r.get("total_episodes"),
            latest_episode_at=_dt((r.get("latest_pub_date_ms") or 0) / 1000 or None),
            explicit=bool(r.get("explicit_content")),
            source_url=r.get("listennotes_url"),
        )

    def search(self, q: str, *, language: str | None = None, region: str | None = None, limit: int = 10) -> list[dict]:
        body = self._get(
            "/search",
            {
                "q": q,
                "type": "podcast",
                "language": _LN_LANGUAGES.get(language or ""),
                "region": (region or "").lower() or None,
                "page_size": min(limit, 10),
            },
        )
        return [self._podcast(r) for r in body.get("results", []) if r.get("id")]

    def get(self, pid: str) -> tuple[dict, list[dict]]:
        body = self._get(f"/podcasts/{pid}", {"sort": "recent_first"})
        episodes = [
            {
                "key": rss.episode_key(e.get("id"), e.get("audio")),
                "title": e.get("title") or "Untitled episode",
                "description": rss.clean_html(e.get("description")),
                "audio_url": _http_or_none(e.get("audio")),
                "duration_s": e.get("audio_length_sec"),
                "published_at": _dt((e.get("pub_date_ms") or 0) / 1000 or None),
                "image_url": e.get("image") or e.get("thumbnail"),
                "explicit": bool(e.get("explicit_content")),
                "source_url": e.get("listennotes_url"),
            }
            for e in body.get("episodes", [])
        ]
        return self._podcast(body), episodes


itunes = ITunesPodcasts()
podcast_index = PodcastIndex()
listen_notes = ListenNotes()
PROVIDERS = {p.key: p for p in (itunes, podcast_index, listen_notes)}

_rss_http = ProviderClient("rss", rate_per_second=5, burst=5, daily_quota=get_settings().rss_daily_quota)


def fetch_feed(feed_url: str, limit: int = 300) -> tuple[dict, list[dict]]:
    if not public_http_url(feed_url):
        raise ProviderError("rss", "bad_response", "The feed address isn't a public web address")
    text = _rss_http.get_text(feed_url, headers={"Accept": "application/rss+xml, application/xml, text/xml;q=0.9, */*;q=0.5"})
    if len(text) > get_settings().rss_max_bytes:
        raise ProviderError("rss", "bad_response", "The feed is too large")
    try:
        return rss.parse_feed(text, limit)
    except rss.FeedError as exc:
        raise ProviderError("rss", "bad_response", str(exc)) from exc
