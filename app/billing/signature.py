"""Stripe-compatible webhook signatures: header `t=<unix>,v1=<hex hmac-sha256("t.payload")>`."""

import hashlib
import hmac
import time

from app.core.errors import AppError


class InvalidSignature(AppError):
    status_code = 400
    code = "invalid_signature"


def compute_signature(payload: bytes, secret: str, timestamp: int) -> str:
    signed = f"{timestamp}.".encode() + payload
    return hmac.new(secret.encode(), signed, hashlib.sha256).hexdigest()


def sign_payload(payload: bytes, secret: str, timestamp: int | None = None) -> str:
    ts = int(time.time()) if timestamp is None else timestamp
    return f"t={ts},v1={compute_signature(payload, secret, ts)}"


def verify_signature(payload: bytes, header: str | None, secret: str, tolerance: int, now: float | None = None) -> None:
    if not header:
        raise InvalidSignature("Missing signature header")
    timestamp: int | None = None
    candidates: list[str] = []
    for part in header.split(","):
        key, _, value = part.strip().partition("=")
        if key == "t" and value.isdigit():
            timestamp = int(value)
        elif key == "v1":
            candidates.append(value)
    if timestamp is None or not candidates:
        raise InvalidSignature("Malformed signature header")
    # Reject stale timestamps so a captured request can't be replayed later.
    if abs((now if now is not None else time.time()) - timestamp) > tolerance:
        raise InvalidSignature("Signature timestamp outside tolerance")
    expected = compute_signature(payload, secret, timestamp)
    if not any(hmac.compare_digest(expected, c) for c in candidates):
        raise InvalidSignature("Signature mismatch")
