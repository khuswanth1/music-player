"""Test setup: a real PostgreSQL database (TEST_DATABASE_URL), migrated with Alembic, truncated between tests."""

import io
import os
import tempfile
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

BACKEND = Path(__file__).resolve().parents[1]


def _dotenv_value(key: str) -> str | None:
    env_file = BACKEND / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            if line.startswith(f"{key}="):
                return line.split("=", 1)[1].strip()
    return None


TEST_DB = os.environ.get("TEST_DATABASE_URL") or _dotenv_value("TEST_DATABASE_URL")
if not TEST_DB:
    raise RuntimeError("Set TEST_DATABASE_URL (a dedicated, disposable database) to run the tests")

# Must be set before the app (and its cached settings / engine) are imported.
os.environ.update({
    "DATABASE_URL": TEST_DB,
    "ENVIRONMENT": "test",
    "MEDIA_ROOT": tempfile.mkdtemp(prefix="wavely-media-"),
    "WORKER_ENABLED": "false",
    "RATE_LIMIT_ENABLED": "false",
    "BILLING_PROVIDER": "dev",
    "STORAGE_BACKEND": "local",
    "EMAIL_BACKEND": "console",
    "STRIPE_WEBHOOK_SECRET": "whsec_test_secret",
    "JWT_SECRET": "test-secret-" + "x" * 40,
    "LOG_JSON": "false",
    "LOG_LEVEL": "WARNING",
    # Never use a developer's real OAuth app from backend/.env in tests.
    "GOOGLE_CLIENT_ID": "",
    "GOOGLE_CLIENT_SECRET": "",
    "JAMENDO_CLIENT_ID": "",
})

from alembic.config import Config  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import text  # noqa: E402

from alembic import command  # noqa: E402
from app.core.config import get_settings  # noqa: E402
from app.core.permissions import ROLE_IDS, RoleName  # noqa: E402
from app.core.rate_limit import limiter  # noqa: E402
from app.core.security import create_access_token, hash_password, utcnow  # noqa: E402
from app.db.session import SessionLocal, engine  # noqa: E402
from app.models import Plan, Subscription, SubscriptionStatus, User  # noqa: E402

PASSWORD = "correct-horse-42"
_PASSWORD_HASH = hash_password(PASSWORD)  # hashing is deliberately slow; do it once


@pytest.fixture(scope="session", autouse=True)
def migrated_db():
    cfg = Config(str(BACKEND / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND / "alembic"))
    cfg.cmd_opts = type("Opts", (), {"x": [f"url={TEST_DB}"]})()
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")
    yield


@pytest.fixture(autouse=True)
def clean_tables():
    yield
    with engine.begin() as conn:
        tables = [r[0] for r in conn.execute(text(
            "SELECT tablename FROM pg_tables WHERE schemaname='public' AND tablename NOT IN ('roles','languages','alembic_version')"))]
        conn.execute(text(f"TRUNCATE {', '.join(tables)} RESTART IDENTITY CASCADE"))
    limiter.reset()


@pytest.fixture(autouse=True)
def no_provider_network():
    """Provider HTTP never leaves the test process: unmocked requests get a 503 and fail the test."""
    import httpx

    from app.music import http as music_http
    from app.music.providers import reset_providers

    unexpected: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        unexpected.append(str(request.url))
        return httpx.Response(503)

    music_http.set_transport(httpx.MockTransport(handler))
    reset_providers()
    yield unexpected
    music_http.set_transport(None)
    reset_providers()
    assert not unexpected, f"Unexpected provider requests: {unexpected}"


@pytest.fixture
def settings():
    return get_settings()


@pytest.fixture
def client():
    from app.main import app

    with TestClient(app) as c:
        yield c


@pytest.fixture
def db():
    with SessionLocal() as session:
        yield session


class Factory:
    def __init__(self) -> None:
        self.n = 0

    def user(self, role: RoleName = RoleName.listener, *, premium: bool = False, email: str | None = None) -> User:
        self.n += 1
        with SessionLocal() as db:
            user = User(email=email or f"user{self.n}@example.com", display_name=f"User {self.n}",
                        password_hash=_PASSWORD_HASH, role_id=ROLE_IDS[role])
            db.add(user)
            db.flush()
            if premium:
                db.add(Subscription(user_id=user.id, plan=Plan.premium_monthly, status=SubscriptionStatus.active,
                                    provider="manual", current_period_end=utcnow().replace(year=utcnow().year + 1)))
            db.commit()
            db.refresh(user, ["role"])
            return user

    @staticmethod
    def headers(user: User) -> dict[str, str]:
        return {"Authorization": f"Bearer {create_access_token(user.id, user.role_name)}"}


@pytest.fixture
def factory():
    return Factory()


def make_ogg(seconds: float = 1.0, freq: float = 440.0) -> bytes:
    sr = 22050
    t = np.linspace(0, seconds, int(sr * seconds), endpoint=False)
    buf = io.BytesIO()
    sf.write(buf, (0.3 * np.sin(2 * np.pi * freq * t)).astype(np.float32), sr, format="OGG", subtype="VORBIS")
    return buf.getvalue()


PNG_1PX = bytes.fromhex(
    "89504e470d0a1a0a0000000d4948445200000001000000010806000000"
    "1f15c4890000000d49444154789c6360000002000154a24f5d0000000049454e44ae426082")


@pytest.fixture
def catalog(client, factory):
    """An editor plus a small catalog: genre, artist, album and three songs (one premium-only)."""
    editor = factory.user(RoleName.content_manager)
    h = factory.headers(editor)
    genre = client.post("/api/v1/genres", json={"name": "Synthwave", "color": "#ff00aa"}, headers=h).json()
    artist = client.post("/api/v1/artists", json={"name": "Neon Drift", "bio": "Test artist"}, headers=h).json()
    album = client.post("/api/v1/albums", json={"title": "Night Drive", "artist_id": artist["id"],
                                                "release_date": "2026-01-15", "is_featured": True}, headers=h).json()
    songs = []
    for i, (title, premium) in enumerate([("Midnight Run", False), ("Chrome Hearts", False), ("Afterglow", True)], 1):
        res = client.post("/api/v1/songs", headers=h,
                          data={"title": title, "artist_id": artist["id"], "album_id": album["id"],
                                "genre_id": str(genre["id"]), "track_number": str(i), "is_premium": str(premium).lower()},
                          files={"file": (f"{title}.ogg", make_ogg(1.0 + i * 0.25, 220 * i), "audio/ogg")})
        assert res.status_code == 201, res.text
        songs.append(res.json())
    return {"editor": editor, "headers": h, "genre": genre, "artist": artist, "album": album, "songs": songs}
