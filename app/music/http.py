"""Outbound HTTP for music providers: caching, rate limits, daily quotas and retries in one place.

Every provider request goes through `ProviderClient.get_json`:

1. **Cache** — responses are stored in `provider_cache` (PostgreSQL, shared by all replicas) for a TTL.
2. **Quota** — `provider_usage` counts requests per provider per UTC day; past the configured quota the
   request is refused locally instead of being sent.
3. **Rate limit** — an in-process token bucket per provider spaces requests (e.g. MusicBrainz: 1/s).
   With several API replicas, divide the configured rate by the replica count.
4. **Retries** — one retry on network errors and 5xx; `429`/`503` honor `Retry-After` (if short).

Failures raise `ProviderError` with a `kind` the API reports per provider, so one provider's outage
never fails a whole search.
"""

import hashlib
import json
import logging
import threading
import time
from datetime import timedelta
from typing import Any

import httpx
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert

from app.core.config import get_settings
from app.core.security import utcnow
from app.db.session import SessionLocal
from app.models import ProviderCache, ProviderUsage

log = logging.getLogger(__name__)


class ProviderError(Exception):
    """kind: not_configured | unsupported | rate_limited | quota_exceeded | unavailable | bad_response | not_found"""

    def __init__(self, provider: str, kind: str, message: str) -> None:
        super().__init__(f"{provider}: {message}")
        self.provider, self.kind, self.message = provider, kind, message


class TokenBucket:
    def __init__(self, rate: float, burst: int) -> None:
        self.rate, self.capacity = rate, float(burst)
        self.tokens, self.updated = float(burst), time.monotonic()
        self.lock = threading.Lock()

    def acquire(self, max_wait: float) -> bool:
        """Take one token, sleeping up to `max_wait` seconds for it. Returns False if none came in time."""
        deadline = time.monotonic() + max_wait
        while True:
            with self.lock:
                now = time.monotonic()
                self.tokens = min(self.capacity, self.tokens + (now - self.updated) * self.rate)
                self.updated = now
                if self.tokens >= 1:
                    self.tokens -= 1
                    return True
                wait = (1 - self.tokens) / self.rate
            if time.monotonic() + wait > deadline:
                return False
            time.sleep(wait)


_buckets: dict[str, TokenBucket] = {}
_clients: dict[str, httpx.Client] = {}
_registry_lock = threading.Lock()
_transport: httpx.BaseTransport | None = None  # tests inject httpx.MockTransport here


def set_transport(transport: httpx.BaseTransport | None) -> None:
    """Route all provider traffic through `transport` (tests). Resets pooled clients and limiters."""
    global _transport
    with _registry_lock:
        _transport = transport
        for client in _clients.values():
            client.close()
        _clients.clear()
        _buckets.clear()


def _public_only(request: httpx.Request) -> None:
    """Runs before every request - including each redirect hop - of clients that fetch publisher-supplied URLs."""
    from app.podcasts.providers import public_http_url

    if not public_http_url(str(request.url)):
        raise httpx.UnsupportedProtocol("Blocked: not a public web address")


def _size_capped(response: httpx.Response) -> None:
    limit = get_settings().rss_max_bytes
    if int(response.headers.get("content-length") or 0) > limit:
        raise httpx.TooManyRedirects("Blocked: response too large", request=response.request)


# Providers whose URLs come from third-party data (podcast feeds) rather than from our own adapter code.
_UNTRUSTED_URLS = {"rss"}


def _client(provider: str) -> httpx.Client:
    with _registry_lock:
        if provider not in _clients:
            settings = get_settings()
            hooks = {"request": [_public_only], "response": [_size_capped]} if provider in _UNTRUSTED_URLS else {}
            _clients[provider] = httpx.Client(
                transport=_transport, timeout=settings.music_http_timeout_seconds, follow_redirects=True,
                headers={"User-Agent": settings.music_user_agent, "Accept": "application/json"}, event_hooks=hooks)
        return _clients[provider]


def _bucket(provider: str, rate: float, burst: int) -> TokenBucket:
    with _registry_lock:
        return _buckets.setdefault(provider, TokenBucket(rate, burst))


def cache_key(provider: str, url: str, params: dict | None) -> str:
    raw = json.dumps([provider, url, sorted((params or {}).items())], default=str, ensure_ascii=False)
    return hashlib.sha256(raw.encode()).hexdigest()


_MEM_CACHE: dict[str, tuple[Any, float]] = {}
_MEM_CACHE_LOCK = threading.Lock()
_MEM_CACHE_MAX_ENTRIES = 5000


def _cache_get(key: str) -> Any | None:
    now_m = time.monotonic()
    with _MEM_CACHE_LOCK:
        if key in _MEM_CACHE:
            body, exp = _MEM_CACHE[key]
            if exp > now_m:
                return body
            del _MEM_CACHE[key]

    with SessionLocal() as db:
        res = db.scalar(select(ProviderCache.body).where(ProviderCache.key == key, ProviderCache.expires_at > utcnow()))
        if res is not None:
            with _MEM_CACHE_LOCK:
                if len(_MEM_CACHE) > _MEM_CACHE_MAX_ENTRIES:
                    _MEM_CACHE.clear()
                _MEM_CACHE[key] = (res, now_m + 1800)  # 30 min memory cache
        return res


def _cache_put(key: str, provider: str, url: str, body: Any, ttl: timedelta) -> None:
    now_m = time.monotonic()
    ttl_seconds = ttl.total_seconds()
    with _MEM_CACHE_LOCK:
        if len(_MEM_CACHE) > _MEM_CACHE_MAX_ENTRIES:
            _MEM_CACHE.clear()
        _MEM_CACHE[key] = (body, now_m + min(ttl_seconds, 1800))

    now = utcnow()
    values = {"provider": provider, "url": url[:2000], "body": body, "fetched_at": now, "expires_at": now + ttl}
    with SessionLocal() as db:
        db.execute(insert(ProviderCache).values(key=key, **values)
                   .on_conflict_do_update(index_elements=[ProviderCache.key], set_=values))
        db.commit()



def _count_request(provider: str, quota: int | None) -> None:
    """Atomically count one outbound request; refuse it if today's quota is already used up."""
    with SessionLocal() as db:
        used = db.scalar(insert(ProviderUsage).values(provider=provider, day=utcnow().date(), requests=1)
                         .on_conflict_do_update(index_elements=[ProviderUsage.provider, ProviderUsage.day],
                                                set_={"requests": ProviderUsage.requests + 1})
                         .returning(ProviderUsage.requests))
        if quota is not None and used > quota:
            db.rollback()
            raise ProviderError(provider, "quota_exceeded", f"Daily request quota ({quota}) reached")
        db.commit()


def record_error(provider: str, message: str) -> None:
    now = utcnow()
    with SessionLocal() as db:
        db.execute(insert(ProviderUsage).values(provider=provider, day=now.date(), requests=0, errors=1,
                                                last_error=message[:500], last_error_at=now)
                   .on_conflict_do_update(index_elements=[ProviderUsage.provider, ProviderUsage.day],
                                          set_={"errors": ProviderUsage.errors + 1, "last_error": message[:500],
                                                "last_error_at": now}))
        db.commit()


def purge_expired_cache() -> int:
    with SessionLocal() as db:
        removed = db.execute(delete(ProviderCache).where(ProviderCache.expires_at < utcnow())).rowcount
        db.commit()
    return removed


def _retry_after(resp: httpx.Response) -> float | None:
    try:
        return float(resp.headers.get("retry-after", ""))
    except ValueError:
        return None


class ProviderClient:
    def __init__(self, provider: str, *, rate_per_second: float, burst: int = 1, daily_quota: int | None = None,
                 ttl: timedelta | None = None) -> None:
        self.provider = provider
        self.rate, self.burst, self.quota = rate_per_second, burst, daily_quota
        self.ttl = ttl or timedelta(minutes=get_settings().music_cache_ttl_minutes)

    def get_text(self, url: str, params: dict | None = None, *, headers: dict | None = None,
                 ttl: timedelta | None = None, cache: bool = True, max_wait: float = 3.0) -> str:
        """Like `get_json` for non-JSON bodies (RSS/XML). Cached as `{"text": ...}`."""
        body = self.get_json(url, params, headers=headers, ttl=ttl, cache=cache, max_wait=max_wait, raw=True)
        return body["text"]

    def get_json(self, url: str, params: dict | None = None, *, headers: dict | None = None,
                 ttl: timedelta | None = None, cache: bool = True, max_wait: float = 3.0, raw: bool = False) -> Any:
        params = {k: v for k, v in (params or {}).items() if v is not None}
        key = cache_key(self.provider, url, params)
        if cache:
            hit = _cache_get(key)
            if hit is not None:
                return hit

        last_error = "unknown error"
        for attempt in range(2):
            _count_request(self.provider, self.quota)
            if not _bucket(self.provider, self.rate, self.burst).acquire(max_wait):
                raise ProviderError(self.provider, "rate_limited", "Local rate limit reached; try again shortly")
            try:
                resp = _client(self.provider).get(url, params=params, headers=headers)
            except httpx.TimeoutException:
                last_error = "timed out"
                continue
            except httpx.HTTPError as exc:
                last_error = f"network error: {type(exc).__name__}"
                continue

            if resp.status_code in (429, 503):
                wait = _retry_after(resp)
                if attempt == 0 and wait is not None and wait <= 3:
                    time.sleep(wait)
                    continue
                record_error(self.provider, f"HTTP {resp.status_code}")
                raise ProviderError(self.provider, "rate_limited", "The provider asked us to slow down")
            if resp.status_code == 404:
                raise ProviderError(self.provider, "not_found", "Not found at the provider")
            if resp.status_code >= 500:
                last_error = f"HTTP {resp.status_code}"
                continue
            if resp.status_code >= 400:
                record_error(self.provider, f"HTTP {resp.status_code}")
                raise ProviderError(self.provider, "bad_response", f"The provider rejected the request (HTTP {resp.status_code})")
            if raw:
                body = {"text": resp.text}
                if cache:
                    _cache_put(key, self.provider, url, body, ttl or self.ttl)
                return body
            try:
                body = resp.json()
            except ValueError as exc:
                record_error(self.provider, "invalid JSON")
                raise ProviderError(self.provider, "bad_response", "The provider returned invalid JSON") from exc
            if cache:
                _cache_put(key, self.provider, url, body, ttl or self.ttl)
            return body

        record_error(self.provider, last_error)
        log.warning("provider.request_failed", extra={"provider": self.provider, "error": last_error})
        raise ProviderError(self.provider, "unavailable", f"The provider is unavailable ({last_error})")
