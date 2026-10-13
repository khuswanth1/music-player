"""Takedowns and rights notifications.

A takedown writes a `rights_blocks` row (so the track stays blocked even if it is imported later) and
immediately makes any existing copy unplayable. Restoring removes the block and re-verifies the track
with its provider, so it only becomes playable again if its license and provider terms still allow it.

Rights holders' notices can arrive as signed webhooks (POST /api/v1/catalog/webhooks), stored and
retried through the same pipeline as billing webhooks.
"""

import logging

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.billing.webhooks import register_handler
from app.core.errors import AppError
from app.models import RightsBlock, Song
from app.music.federation import verify
from app.music.http import ProviderError
from app.music.ingest import block_track

log = logging.getLogger(__name__)
WEBHOOK_PROVIDER = "catalog"


def find_song(db: Session, source: str, provider_track_id: str) -> Song | None:
    return db.scalar(select(Song).where(Song.source == source, Song.provider_track_id == provider_track_id))


def takedown(db: Session, source: str, provider_track_id: str, reason: str, requested_by: str) -> Song | None:
    return block_track(db, source, provider_track_id, reason, requested_by)


def restore(db: Session, source: str, provider_track_id: str) -> Song | None:
    db.execute(delete(RightsBlock).where(RightsBlock.source == source, RightsBlock.provider_track_id == provider_track_id))
    song = find_song(db, source, provider_track_id)
    if song is not None:
        song.takedown_at = None
        song.restriction_reason = None
        song.rights_checked_at = None  # force a fresh check
    db.commit()
    if song is not None:
        try:
            verify(db, song)
        except ProviderError as exc:  # stays unverified; playback re-checks before streaming
            log.warning("music.restore_verify_failed", extra={"song_id": str(song.id), "error": exc.message})
    return song


def _handle(db: Session, event_type: str, payload: dict) -> bool:
    data = payload.get("data") or {}
    source, track_id = str(data.get("provider") or ""), str(data.get("provider_track_id") or "")
    if not source or not track_id:
        raise AppError("data.provider and data.provider_track_id are required", code="invalid_event")
    match event_type:
        case "track.takedown":
            takedown(db, source, track_id, str(data.get("reason") or "Removed following a rights notice"),
                     f"webhook:{payload.get('id')}")
            return True
        case "track.restore":
            restore(db, source, track_id)
            return True
        case "track.rights_changed":
            song = find_song(db, source, track_id)
            if song is None:
                return False
            verify(db, song)
            return True
        case _:
            return False


register_handler(WEBHOOK_PROVIDER, _handle)
