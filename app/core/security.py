import hashlib
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from app.core.config import get_settings
from app.core.errors import Unauthorized

_hasher = PasswordHasher()  # argon2id with library defaults (OWASP-compliant)

# Verified against when the user doesn't exist, so login timing doesn't reveal which emails are registered.
_DUMMY_HASH = _hasher.hash(secrets.token_urlsafe(16))


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str | None) -> bool:
    try:
        return _hasher.verify(password_hash or _DUMMY_HASH, password) and password_hash is not None
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def password_needs_rehash(password_hash: str) -> bool:
    return _hasher.check_needs_rehash(password_hash)


def utcnow() -> datetime:
    return datetime.now(UTC)


def encode_token(claims: dict[str, Any], ttl: timedelta) -> str:
    settings = get_settings()
    now = utcnow()
    payload = {**claims, "iat": now, "nbf": now, "exp": now + ttl, "jti": uuid.uuid4().hex}
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_token(token: str, expected_type: str) -> dict[str, Any]:
    settings = get_settings()
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm],
                             options={"require": ["exp", "sub", "typ"]})
    except jwt.ExpiredSignatureError as exc:
        raise Unauthorized("Token has expired", code="token_expired") from exc
    except jwt.PyJWTError as exc:
        raise Unauthorized("Invalid token", code="invalid_token") from exc
    if payload.get("typ") != expected_type:
        raise Unauthorized("Invalid token type", code="invalid_token")
    return payload


def create_access_token(user_id: uuid.UUID, role: str) -> str:
    ttl = timedelta(minutes=get_settings().access_token_ttl_minutes)
    return encode_token({"sub": str(user_id), "role": role, "typ": "access"}, ttl)


def create_stream_token(user_id: uuid.UUID, song_id: uuid.UUID) -> str:
    """Scoped to one song so a leaked stream URL can't be used to fetch the rest of the catalog."""
    ttl = timedelta(minutes=get_settings().stream_token_ttl_minutes)
    return encode_token({"sub": str(user_id), "song": str(song_id), "typ": "stream"}, ttl)


def create_oauth_state_token(nonce: str) -> str:
    return encode_token({"sub": "oauth", "nonce": nonce, "typ": "oauth_state"}, timedelta(minutes=10))


def generate_opaque_token(nbytes: int = 32) -> str:
    return secrets.token_urlsafe(nbytes)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def generate_invite_code() -> str:
    return secrets.token_urlsafe(9)
