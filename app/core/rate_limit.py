"""Sliding-window rate limiter.

In-process state is correct for a single backend instance. With several replicas,
replace `_store` with Redis (INCR + EXPIRE per window) behind the same interface.
"""

import threading
import time
from collections import deque

from fastapi import Request

from app.core.config import get_settings
from app.core.errors import RateLimited


class SlidingWindowLimiter:
    def __init__(self) -> None:
        self._store: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def hit(self, key: str, limit: int, window: float) -> float | None:
        """Record a hit. Returns seconds to wait if the limit is exceeded, else None."""
        now = time.monotonic()
        with self._lock:
            hits = self._store.setdefault(key, deque())
            while hits and hits[0] <= now - window:
                hits.popleft()
            if len(hits) >= limit:
                return max(0.0, hits[0] + window - now)
            hits.append(now)
            if len(self._store) > 50_000:  # bound memory under abuse
                self._evict(now - window)
            return None

    def _evict(self, cutoff: float) -> None:
        for k in [k for k, v in self._store.items() if not v or v[-1] <= cutoff]:
            del self._store[k]

    def reset(self) -> None:
        with self._lock:
            self._store.clear()


limiter = SlidingWindowLimiter()


def client_ip(request: Request) -> str:
    # uvicorn --proxy-headers rewrites request.client from X-Forwarded-For for trusted proxies.
    return request.client.host if request.client else "unknown"


def rate_limit(scope: str, limit: int | None = None, window: int | None = None):
    def dependency(request: Request) -> None:
        settings = get_settings()
        if not settings.rate_limit_enabled:
            return
        retry = limiter.hit(f"{scope}:{client_ip(request)}", limit or settings.auth_rate_limit,
                            window or settings.auth_rate_window_seconds)
        if retry is not None:
            raise RateLimited("Too many requests, please slow down", details={"retry_after": int(retry) + 1})

    return dependency
