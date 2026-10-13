"""In-process WebSocket pub/sub.

Channels: `playlist:<id>`, `session:<id>`, `user:<id>`, and `catalog` (catalog-wide notices, e.g. a track
became unavailable; no presence is broadcast there, so listeners never see each other). A single backend instance holds all
sockets; to run several replicas, fan `publish` out through Redis or Postgres LISTEN/NOTIFY.
"""

import asyncio
import logging
import uuid
from dataclasses import dataclass, field
from typing import Any

from fastapi import WebSocket

log = logging.getLogger(__name__)
BROADCAST_ONLY = frozenset({"catalog"})


@dataclass(eq=False)
class Connection:
    ws: WebSocket
    user_id: uuid.UUID
    display_name: str
    avatar_url: str | None
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    channels: set[str] = field(default_factory=set)

    async def send(self, message: dict[str, Any]) -> bool:
        try:
            await self.ws.send_json(message)
            return True
        except Exception:  # socket already closed; the reader loop will clean up
            return False


class Hub:
    def __init__(self) -> None:
        self.channels: dict[str, set[Connection]] = {}
        self.loop: asyncio.AbstractEventLoop | None = None

    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self.loop = loop

    async def subscribe(self, conn: Connection, channel: str) -> None:
        # No lock needed: hub state is only touched on the event loop, with no await in between.
        self.channels.setdefault(channel, set()).add(conn)
        conn.channels.add(channel)
        await self.broadcast_presence(channel)

    async def unsubscribe(self, conn: Connection, channel: str) -> None:
        members = self.channels.get(channel)
        if members:
            members.discard(conn)
            if not members:
                del self.channels[channel]
        conn.channels.discard(channel)
        await self.broadcast_presence(channel)

    async def disconnect(self, conn: Connection) -> None:
        for channel in list(conn.channels):
            await self.unsubscribe(conn, channel)

    def presence(self, channel: str) -> list[dict[str, Any]]:
        seen: dict[uuid.UUID, dict[str, Any]] = {}
        for conn in self.channels.get(channel, ()):
            seen.setdefault(conn.user_id, {"user_id": str(conn.user_id), "display_name": conn.display_name,
                                           "avatar_url": conn.avatar_url})
        return list(seen.values())

    async def broadcast_presence(self, channel: str) -> None:
        if channel in BROADCAST_ONLY:
            return
        await self.broadcast(channel, {"type": "presence", "channel": channel, "users": self.presence(channel)})

    async def broadcast(self, channel: str, message: dict[str, Any], exclude: Connection | None = None) -> int:
        targets = [c for c in self.channels.get(channel, ()) if c is not exclude]
        message = {"channel": channel, **message}
        results = await asyncio.gather(*(c.send(message) for c in targets))
        return sum(results)

    async def close_channel(self, channel: str, message: dict[str, Any]) -> None:
        await self.broadcast(channel, message)
        for conn in self.channels.pop(channel, set()):
            conn.channels.discard(channel)

    def publish(self, channel: str, message: dict[str, Any]) -> None:
        """Thread-safe, fire-and-forget. Called from sync endpoints running in the threadpool."""
        if self.loop is None or self.loop.is_closed():
            return
        try:
            running = asyncio.get_running_loop()
        except RuntimeError:
            running = None
        if running is self.loop:
            self.loop.create_task(self.broadcast(channel, message))
        else:
            asyncio.run_coroutine_threadsafe(self.broadcast(channel, message), self.loop)


hub = Hub()
