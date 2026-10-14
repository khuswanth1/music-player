"""Periodic background jobs, run inside the API process's event loop.

Each job runs in a worker thread so blocking DB work never stalls WebSockets. If several API
replicas run, the jobs remain safe: webhook rows are claimed with SKIP LOCKED, and cleanup is idempotent.
"""

import asyncio
import logging
from datetime import timedelta

from sqlalchemy import delete, or_

from app.billing.webhooks import retry_due_events
from app.core.config import get_settings
from app.core.security import utcnow
from app.db.session import SessionLocal
from app.models import LoginCode, PasswordResetToken, RefreshToken
from app.music import federation
from app.music.http import purge_expired_cache

log = logging.getLogger(__name__)


def purge_expired_tokens() -> int:
    cutoff = utcnow() - timedelta(days=7)
    with SessionLocal() as db:
        removed = db.execute(delete(RefreshToken).where(
            or_(RefreshToken.expires_at < cutoff, RefreshToken.revoked_at < cutoff))).rowcount
        removed += db.execute(delete(PasswordResetToken).where(PasswordResetToken.expires_at < cutoff)).rowcount
        removed += db.execute(delete(LoginCode).where(LoginCode.expires_at < cutoff)).rowcount
        db.commit()
    return removed


async def _music_jobs(ticks: int) -> None:
    """Keep configured languages warm and enrich new imports from MusicBrainz. Failures are logged per job."""
    settings = get_settings()
    if settings.catalog_sync_enabled and ticks % max(1, settings.catalog_sync_every_ticks) == 0:
        try:
            await asyncio.to_thread(federation.sync_tick)
            await asyncio.to_thread(federation.genre_sync_tick)
        except Exception:
            log.exception("worker.music_sync_error")
    try:
        enriched = await asyncio.to_thread(federation.enrich_tick)
        if enriched:
            log.info("worker.music_enriched", extra={"count": enriched})
    except Exception:
        log.exception("worker.music_enrich_error")


async def run_worker(stop: asyncio.Event) -> None:
    interval = get_settings().worker_interval_seconds
    ticks = 0
    while not stop.is_set():
        try:
            retried = await asyncio.to_thread(retry_due_events)
            if retried:
                log.info("worker.webhooks_retried", extra={"count": retried})
            if ticks % 120 == 0:  # roughly hourly at the default interval
                purged = await asyncio.to_thread(purge_expired_tokens)
                if purged:
                    log.info("worker.tokens_purged", extra={"count": purged})
                cached = await asyncio.to_thread(purge_expired_cache)
                if cached:
                    log.info("worker.provider_cache_purged", extra={"count": cached})
            await _music_jobs(ticks)
        except Exception:
            log.exception("worker.error")
        ticks += 1
        try:
            await asyncio.wait_for(stop.wait(), timeout=interval)
        except TimeoutError:
            pass
