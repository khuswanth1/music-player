"""Pure ASGI middleware (BaseHTTPMiddleware buffers streaming responses, which breaks audio)."""

import logging
import re
import time
import uuid

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.logging import request_id_var

log = logging.getLogger("app.request")
_VALID_REQUEST_ID = re.compile(r"^[A-Za-z0-9\-_.]{8,64}$")
_DOCS_PATHS = ("/docs", "/redoc", "/openapi.json")


class RequestContextMiddleware:
    """Assigns a request id, adds security headers, and logs one line per request."""

    def __init__(self, app: ASGIApp, *, hsts: bool = False) -> None:
        self.app = app
        self.hsts = hsts

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return

        headers = dict(scope.get("headers") or [])
        incoming = headers.get(b"x-request-id", b"").decode("latin-1")
        request_id = incoming if _VALID_REQUEST_ID.match(incoming) else uuid.uuid4().hex
        token = request_id_var.set(request_id)

        if scope["type"] == "websocket":
            try:
                await self.app(scope, receive, send)
            finally:
                request_id_var.reset(token)
            return

        start = time.perf_counter()
        status_holder = {"status": 500}
        path: str = scope["path"]

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                status_holder["status"] = message["status"]
                extra = [
                    (b"x-request-id", request_id.encode()),
                    (b"x-content-type-options", b"nosniff"),
                    (b"x-frame-options", b"DENY"),
                    (b"referrer-policy", b"strict-origin-when-cross-origin"),
                    (b"cross-origin-opener-policy", b"same-origin"),
                    (b"permissions-policy", b"camera=(), microphone=(), geolocation=()"),
                ]
                if not path.startswith(_DOCS_PATHS):
                    # API responses never need to run scripts; this also neutralises uploaded SVG media.
                    extra.append((b"content-security-policy", b"default-src 'none'; frame-ancestors 'none'; sandbox"))
                if self.hsts:
                    extra.append((b"strict-transport-security", b"max-age=63072000; includeSubDomains"))
                message["headers"] = list(message.get("headers", [])) + extra
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            duration_ms = round((time.perf_counter() - start) * 1000, 1)
            status = status_holder["status"]
            if not path.startswith("/health"):
                level = logging.WARNING if status >= 500 else logging.INFO
                log.log(level, "request", extra={"method": scope["method"], "path": path,
                                                 "status": status, "duration_ms": duration_ms})
            request_id_var.reset(token)
