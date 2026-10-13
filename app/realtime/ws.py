"""WebSocket endpoint: /api/v1/ws

Protocol (JSON text frames):
  client → {"type": "auth", "token": "<access token>"}            must be the first frame, within 10 s
  server → {"type": "ready", "user_id": ..., "heartbeat_interval": 25}
  client → {"type": "subscribe", "channel": "playlist:<id>" | "session:<id>" | "user:me" | "catalog", "id": "<ref>"}
  client → {"type": "unsubscribe", "channel": ...}
  client → {"type": "session.control", "session_id": ..., "action": ..., "song_id"?, "position_ms"?, "index"?}
  client → {"type": "ping"}  /  server → {"type": "pong"}
  server → {"type": "ping"} every 25 s; any client frame counts as liveness, silence for 60 s closes (4408)

Close codes: 4401 unauthenticated, 4408 heartbeat timeout, 4429 too many messages.
The token travels in the first frame rather than the URL so it never lands in access logs.
"""

import asyncio
import json
import logging
import re
import time
import uuid
from collections import deque

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from starlette.concurrency import run_in_threadpool

from app.core.errors import AppError
from app.core.security import decode_token
from app.db.session import SessionLocal
from app.models import PlaybackSession, Playlist, User
from app.realtime.hub import BROADCAST_ONLY, Connection, hub
from app.services import playlists as playlist_svc
from app.services import sessions as session_svc

log = logging.getLogger(__name__)
router = APIRouter()

AUTH_TIMEOUT = 10
HEARTBEAT_INTERVAL = 25
IDLE_TIMEOUT = 60
MAX_FRAME = 16 * 1024
BURST_LIMIT, BURST_WINDOW = 60, 10.0
_CHANNEL = re.compile(r"^(playlist|session|user):([0-9a-fA-F-]{36}|me)$")


class WSError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code, self.message = code, message


def _authenticate(token: str) -> tuple[uuid.UUID, str, str | None] | None:
    try:
        payload = decode_token(token, "access")
        user_id = uuid.UUID(payload["sub"])
    except (AppError, ValueError, KeyError):
        return None
    with SessionLocal() as db:
        user = db.get(User, user_id)
        if user is None or not user.is_active:
            return None
        return user.id, user.display_name, user.avatar_url


def _authorize(user_id: uuid.UUID, kind: str, target: uuid.UUID) -> dict | None:
    """Raises WSError if the user may not join the channel. Returns an optional snapshot to send."""
    with SessionLocal() as db:
        user = db.get(User, user_id)
        if kind == "user":
            if target != user_id:
                raise WSError("forbidden", "You can only subscribe to your own user channel")
            return None
        if kind == "playlist":
            playlist = db.get(Playlist, target)
            if playlist is None or not playlist_svc.can_view(db, playlist, user):
                raise WSError("not_found", "Playlist not found")
            return None
        session = db.get(PlaybackSession, target)
        if session is None or not session_svc.is_participant(db, session, user_id):
            raise WSError("not_found", "Session not found")
        state = session_svc.serialize(db, session, None).model_dump(mode="json", exclude={"is_host"})
        return {"type": "session.state", "session": state}


def _session_control(user_id: uuid.UUID, msg: dict) -> tuple[str, dict]:
    with SessionLocal() as db:
        user = db.get(User, user_id)
        try:
            session_id = uuid.UUID(str(msg.get("session_id")))
        except ValueError as exc:
            raise WSError("validation_error", "session_id is required") from exc
        try:
            session = session_svc.apply_control(
                db, user, session_id, str(msg.get("action")), song_id=msg.get("song_id"),
                position_ms=msg.get("position_ms") if isinstance(msg.get("position_ms"), int) else None,
                index=msg.get("index") if isinstance(msg.get("index"), int) else None)
        except AppError as exc:
            raise WSError(exc.code, exc.message) from exc
        state = session_svc.serialize(db, session, None).model_dump(mode="json", exclude={"is_host"})
        return f"session:{session.id}", {"type": "session.state", "session": state}


@router.websocket("/ws")
async def websocket_endpoint(ws: WebSocket) -> None:
    await ws.accept()
    try:
        first = json.loads(await asyncio.wait_for(ws.receive_text(), timeout=AUTH_TIMEOUT))
        identity = await run_in_threadpool(_authenticate, str(first.get("token", ""))) \
            if isinstance(first, dict) and first.get("type") == "auth" else None
    except (TimeoutError, ValueError, WebSocketDisconnect):
        identity = None
    if identity is None:
        await _close(ws, 4401, "unauthenticated")
        return

    user_id, display_name, avatar = identity
    conn = Connection(ws=ws, user_id=user_id, display_name=display_name, avatar_url=avatar)
    await conn.send({"type": "ready", "user_id": str(user_id), "heartbeat_interval": HEARTBEAT_INTERVAL})
    log.info("ws.connected", extra={"user_id": str(user_id), "conn": conn.id})

    last_seen = time.monotonic()
    recent: deque[float] = deque()

    async def heartbeat() -> None:
        while True:
            await asyncio.sleep(HEARTBEAT_INTERVAL)
            if time.monotonic() - last_seen > IDLE_TIMEOUT:
                await _close(ws, 4408, "heartbeat timeout")
                return
            await conn.send({"type": "ping", "ts": int(time.time() * 1000)})

    beat = asyncio.create_task(heartbeat())
    try:
        while True:
            raw = await ws.receive_text()
            last_seen = time.monotonic()
            recent.append(last_seen)
            while recent and recent[0] < last_seen - BURST_WINDOW:
                recent.popleft()
            if len(recent) > BURST_LIMIT:
                await _close(ws, 4429, "too many messages")
                return
            await _handle(conn, raw)
    except WebSocketDisconnect:
        pass
    except RuntimeError:  # receive after close
        pass
    finally:
        beat.cancel()
        await hub.disconnect(conn)
        log.info("ws.disconnected", extra={"user_id": str(user_id), "conn": conn.id})


async def _handle(conn: Connection, raw: str) -> None:
    ref = None
    try:
        if len(raw) > MAX_FRAME:
            raise WSError("frame_too_large", "Message too large")
        try:
            msg = json.loads(raw)
        except ValueError as exc:
            raise WSError("invalid_json", "Message must be JSON") from exc
        if not isinstance(msg, dict):
            raise WSError("invalid_message", "Message must be an object")
        ref = msg.get("id")
        kind = msg.get("type")

        if kind == "ping":
            await conn.send({"type": "pong", "ts": int(time.time() * 1000)})
        elif kind in ("pong", "auth"):
            pass
        elif kind in ("subscribe", "unsubscribe"):
            channel = str(msg.get("channel", ""))
            if channel in BROADCAST_ONLY:  # public, read-only notices for every signed-in user
                if kind == "unsubscribe":
                    await hub.unsubscribe(conn, channel)
                    await conn.send({"type": "unsubscribed", "channel": channel, "ref": ref})
                else:
                    await hub.subscribe(conn, channel)
                    await conn.send({"type": "subscribed", "channel": channel, "ref": ref})
                return
            match = _CHANNEL.match(channel)
            if not match:
                raise WSError("invalid_channel", "Unknown channel")
            prefix, ident = match.groups()
            target = conn.user_id if ident == "me" else uuid.UUID(ident)
            channel = f"{prefix}:{target}"
            if kind == "unsubscribe":
                await hub.unsubscribe(conn, channel)
                await conn.send({"type": "unsubscribed", "channel": channel, "ref": ref})
                return
            snapshot = await run_in_threadpool(_authorize, conn.user_id, prefix, target)
            await hub.subscribe(conn, channel)
            await conn.send({"type": "subscribed", "channel": channel, "ref": ref})
            if snapshot:
                await conn.send({"channel": channel, **snapshot})
        elif kind == "session.control":
            channel, state = await run_in_threadpool(_session_control, conn.user_id, msg)
            await hub.broadcast(channel, state)
            await conn.send({"type": "ack", "ref": ref})
        else:
            raise WSError("unknown_type", f"Unknown message type: {kind}")
    except WSError as exc:
        await conn.send({"type": "error", "code": exc.code, "message": exc.message, "ref": ref})


async def _close(ws: WebSocket, code: int, reason: str) -> None:
    try:
        await ws.close(code=code, reason=reason)
    except RuntimeError:
        pass
