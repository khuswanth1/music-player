"""Unit tests: pure functions with no HTTP or database."""

import time
import uuid

import pytest

from app.billing.signature import InvalidSignature, sign_payload, verify_signature
from app.core.errors import Unauthorized
from app.core.permissions import Perm, has_permission
from app.core.rate_limit import SlidingWindowLimiter
from app.core.security import (
    create_access_token,
    create_stream_token,
    decode_token,
    hash_password,
    verify_password,
)
from app.services.catalog import slugify
from app.storage.backends import LocalStorage
from app.storage.ranges import RangeNotSatisfiable, parse_range


def test_password_hash_roundtrip():
    h = hash_password("s3cret-pass")
    assert h.startswith("$argon2id$")
    assert verify_password("s3cret-pass", h)
    assert not verify_password("wrong", h)
    assert not verify_password("anything", None)


def test_token_types_are_not_interchangeable():
    uid = uuid.uuid4()
    access = create_access_token(uid, "listener")
    assert decode_token(access, "access")["sub"] == str(uid)
    with pytest.raises(Unauthorized):
        decode_token(access, "stream")
    stream = create_stream_token(uid, uuid.uuid4())
    with pytest.raises(Unauthorized):
        decode_token(stream, "access")
    with pytest.raises(Unauthorized):
        decode_token(access + "x", "access")


@pytest.mark.parametrize(("header", "size", "expected"), [
    (None, 100, None),
    ("bytes=0-9", 100, (0, 9)),
    ("bytes=90-", 100, (90, 99)),
    ("bytes=-10", 100, (90, 99)),
    ("bytes=50-500", 100, (50, 99)),
    ("bytes=0-1,5-6", 100, None),  # multi-range → full response
    ("items=0-5", 100, None),
])
def test_parse_range(header, size, expected):
    assert parse_range(header, size) == expected


@pytest.mark.parametrize("header", ["bytes=100-", "bytes=10-5", "bytes=-0"])
def test_parse_range_unsatisfiable(header):
    with pytest.raises(RangeNotSatisfiable):
        parse_range(header, 100)


def test_signature_valid_and_tampered():
    payload, secret = b'{"id":"evt_1"}', "whsec_x"
    header = sign_payload(payload, secret)
    verify_signature(payload, header, secret, 300)
    with pytest.raises(InvalidSignature):
        verify_signature(payload + b" ", header, secret, 300)
    with pytest.raises(InvalidSignature):
        verify_signature(payload, header, "other-secret", 300)


def test_signature_replay_and_malformed():
    payload, secret = b"{}", "whsec_x"
    old = sign_payload(payload, secret, timestamp=int(time.time()) - 3600)
    with pytest.raises(InvalidSignature, match="tolerance"):
        verify_signature(payload, old, secret, 300)
    for bad in (None, "", "garbage", "t=abc,v1=00", "t=123"):
        with pytest.raises(InvalidSignature):
            verify_signature(payload, bad, secret, 300)


def test_rate_limiter_window():
    limiter = SlidingWindowLimiter()
    assert all(limiter.hit("k", 3, 60) is None for _ in range(3))
    assert limiter.hit("k", 3, 60) > 0
    assert limiter.hit("other", 3, 60) is None


def test_permissions():
    assert has_permission("admin", Perm.users_manage)
    assert has_permission("content_manager", Perm.catalog_write)
    assert not has_permission("content_manager", Perm.users_manage)
    assert not has_permission("listener", Perm.catalog_write)
    assert not has_permission("nonexistent", Perm.catalog_write)


def test_slugify():
    assert slugify("Beyoncé & Friends!") == "beyonce-friends"
    assert slugify("!!!") == "item"


def test_local_storage_rejects_traversal(tmp_path):
    storage = LocalStorage(tmp_path)
    for key in ("../escape.txt", "images/../../x", "/", ".."):
        with pytest.raises(ValueError):
            storage.path(key)


def test_local_storage_range_iteration(tmp_path):
    import io

    storage = LocalStorage(tmp_path)
    storage.save("audio/a.bin", io.BytesIO(bytes(range(256)) * 1000), "application/octet-stream")
    assert storage.size("audio/a.bin") == 256_000
    assert b"".join(storage.iter_range("audio/a.bin", 10, 19)) == bytes(range(10, 20))
