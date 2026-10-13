import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from sqlalchemy import text

from app.api.v1 import admin, auth, billing, catalog, discovery, library, music, playlists, sessions, streaming, users
from app.core.config import get_settings
from app.core.errors import register_error_handlers
from app.core.logging import configure_logging
from app.core.middleware import RequestContextMiddleware
from app.db.session import engine
from app.realtime import ws
from app.realtime.hub import hub
from app.worker import run_worker

settings = get_settings()
configure_logging(settings.log_level, settings.log_json)
log = logging.getLogger("app")


@asynccontextmanager
async def lifespan(_: FastAPI):
    hub.bind_loop(asyncio.get_running_loop())
    stop = asyncio.Event()
    worker = asyncio.create_task(run_worker(stop)) if settings.worker_enabled else None
    log.info("startup", extra={"environment": settings.environment, "billing": settings.billing_provider,
                               "storage": settings.storage_backend})
    yield
    stop.set()
    if worker:
        await worker
    engine.dispose()


def create_app() -> FastAPI:
    app = FastAPI(
        title=f"{settings.app_name} API",
        version="1.0.0",
        description="Music streaming API. Authenticate with **Authorize** (email + password), "
                    "or send `Authorization: Bearer <access_token>`.",
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
        swagger_ui_parameters={"persistAuthorization": True},
    )
    register_error_handlers(app)

    # Order: the last added runs first. Request context wraps everything so every response has an id.
    app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_credentials=True,
                       allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
                       allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
                       expose_headers=["X-Request-ID", "Content-Range", "Accept-Ranges"])
    if settings.trusted_hosts != ["*"]:
        app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.trusted_hosts)
    app.add_middleware(RequestContextMiddleware, hsts=settings.environment == "production")

    api = APIRouter(prefix="/api/v1")
    for module in (auth, users, catalog, streaming, playlists, library, discovery, music, billing, sessions, admin):
        api.include_router(module.router)
    api.include_router(ws.router)
    app.include_router(api)

    @app.get("/health", tags=["health"], summary="Liveness")
    def health():
        return {"status": "ok"}

    @app.get("/health/ready", tags=["health"], summary="Readiness (checks the database)")
    def ready():
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return {"status": "ready"}

    return app


app = create_app()
