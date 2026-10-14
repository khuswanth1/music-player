"""Parse a publisher's podcast RSS feed into display metadata and playable episodes.

Feeds are untrusted XML: parsed with defusedxml (no entity expansion or external resources), size-capped,
and only `http(s)` enclosure URLs are accepted. The enclosure is the publisher's own audio URL; we link to
it and never copy it.
"""

import hashlib
import re
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from html import unescape
from urllib.parse import urlparse

from defusedxml import ElementTree as ET

NS = {
    "itunes": "http://www.itunes.com/dtds/podcast-1.0.dtd",
    "content": "http://purl.org/rss/1.0/modules/content/",
    "podcast": "https://podcastindex.org/namespace/1.0",
}
_TAG = re.compile(r"<[^>]+>")


class FeedError(ValueError):
    pass


def episode_key(guid: str | None, fallback: str | None) -> str:
    return hashlib.sha1((guid or fallback or "").encode()).hexdigest()[:16]  # noqa: S324 (identifier, not security)


def _text(el, path: str) -> str | None:
    node = el.find(path, NS)
    return node.text.strip() if node is not None and node.text and node.text.strip() else None


def clean_html(value: str | None, limit: int = 2000) -> str | None:
    if not value:
        return None
    text = unescape(_TAG.sub(" ", value))
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit] or None


def parse_duration(value) -> int | None:
    """`itunes:duration` is seconds, MM:SS or HH:MM:SS."""
    if value in (None, ""):
        return None
    try:
        parts = [int(float(p)) for p in str(value).strip().split(":")]
    except ValueError:
        return None
    seconds = 0
    for p in parts[-3:]:
        seconds = seconds * 60 + p
    return seconds or None


def parse_date(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        dt = parsedate_to_datetime(value)
    except TypeError, ValueError:
        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def _http(url: str | None) -> str | None:
    return url if url and urlparse(url).scheme in ("http", "https") else None


def _int(value: str | None) -> int | None:
    try:
        return int(value) if value else None
    except ValueError:
        return None


def parse_feed(xml_text: str | bytes, limit: int = 300) -> tuple[dict, list[dict]]:
    try:
        root = ET.fromstring(xml_text.encode() if isinstance(xml_text, str) else xml_text)
    except Exception as exc:  # defusedxml raises several types (parse errors, forbidden constructs)
        raise FeedError("The feed isn't valid XML") from exc
    channel = root.find("channel")
    if channel is None:
        raise FeedError("The feed has no channel")

    image = channel.find("itunes:image", NS)
    image_url = _http(image.get("href")) if image is not None else None
    if not image_url:
        image_url = _http(_text(channel, "image/url"))
    meta = {
        "title": _text(channel, "title") or "Untitled podcast",
        "publisher": _text(channel, "itunes:author") or _text(channel, "managingEditor"),
        "description": clean_html(_text(channel, "description")),
        "image_url": image_url,
        "language": _text(channel, "language"),
        "website": _http(_text(channel, "link")),
        "explicit": (_text(channel, "itunes:explicit") or "").lower() in ("yes", "true", "explicit"),
        "categories": [c.get("text") for c in channel.findall("itunes:category", NS) if c.get("text")],
    }

    episodes = []
    for item in channel.findall("item")[:limit]:
        enc = item.find("enclosure")
        audio_url = _http(enc.get("url")) if enc is not None else None
        mime = enc.get("type") if enc is not None else None
        if audio_url and mime and not (mime.startswith("audio/") or mime == "application/octet-stream"):
            audio_url = None  # not audio we can play
        guid = _text(item, "guid")
        img = item.find("itunes:image", NS)
        episodes.append(
            {
                "key": episode_key(guid, audio_url or _text(item, "link") or _text(item, "title")),
                "title": _text(item, "title") or "Untitled episode",
                "description": clean_html(_text(item, "itunes:summary") or _text(item, "description")),
                "audio_url": audio_url,
                "mime_type": mime,
                "duration_s": parse_duration(_text(item, "itunes:duration")),
                "published_at": parse_date(_text(item, "pubDate")),
                "image_url": _http(img.get("href")) if img is not None else None,
                "season": _int(_text(item, "itunes:season")),
                "episode": _int(_text(item, "itunes:episode")),
                "explicit": (_text(item, "itunes:explicit") or "").lower() in ("yes", "true", "explicit"),
                "source_url": _http(_text(item, "link")),
            }
        )
    return meta, episodes
