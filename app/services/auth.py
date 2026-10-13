import hmac
import logging
import secrets
import uuid
from dataclasses import dataclass
from datetime import timedelta
from urllib.parse import urlencode

import httpx
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import AppError, Conflict, Forbidden, Unauthorized
from app.core.permissions import ROLE_IDS, RoleName
from app.core.security import (
    create_access_token,
    create_oauth_state_token,
    decode_token,
    generate_opaque_token,
    hash_password,
    hash_token,
    password_needs_rehash,
    utcnow,
    verify_password,
)
from app.models import LoginCode, PasswordResetToken, RefreshToken, User
from app.repositories import users as users_repo
from app.schemas.user import RegisterRequest

log = logging.getLogger(__name__)

# A rotated token presented again within this window is treated as a concurrent refresh
# (two tabs racing), not as theft.
ROTATION_GRACE = timedelta(seconds=20)


@dataclass
class Session_:
    user: User
    access_token: str
    refresh_token: str


def issue_session(db: Session, user: User, *, family_id: uuid.UUID | None = None,
           ip: str | None = None, user_agent: str | None = None) -> Session_:
    settings = get_settings()
    raw = generate_opaque_token()
    db.add(RefreshToken(
        user_id=user.id, family_id=family_id or uuid.uuid4(), token_hash=hash_token(raw),
        expires_at=utcnow() + timedelta(days=settings.refresh_token_ttl_days),
        ip=ip, user_agent=(user_agent or "")[:255] or None,
    ))
    return Session_(user, create_access_token(user.id, user.role_name), raw)


def register(db: Session, data: RegisterRequest, *, ip: str | None, user_agent: str | None) -> Session_:
    if users_repo.get_by_email(db, data.email):
        raise Conflict("An account with this email already exists", code="email_taken")
    user = User(email=data.email.lower(), display_name=data.display_name,
                password_hash=hash_password(data.password), role_id=ROLE_IDS[RoleName.listener],
                date_of_birth=data.date_of_birth, gender=data.gender, marketing_emails=data.marketing_emails,
                last_login_at=utcnow())
    db.add(user)
    db.flush()
    db.refresh(user, ["role"])
    session = issue_session(db, user, ip=ip, user_agent=user_agent)
    db.commit()
    log.info("auth.registered", extra={"user_id": str(user.id)})
    return session


def authenticate(db: Session, email: str, password: str, *, ip: str | None, user_agent: str | None) -> Session_:
    user = users_repo.get_by_email(db, email)
    # verify_password runs even for unknown emails so response timing doesn't leak which accounts exist.
    if not verify_password(password, user.password_hash if user else None) or user is None:
        log.info("auth.login_failed", extra={"ip": ip})
        raise Unauthorized("Invalid email or password", code="invalid_credentials")
    if not user.is_active:
        raise Forbidden("This account has been disabled", code="account_disabled")
    if password_needs_rehash(user.password_hash):
        user.password_hash = hash_password(password)
    user.last_login_at = utcnow()
    session = issue_session(db, user, ip=ip, user_agent=user_agent)
    db.commit()
    return session


# --- one-time email codes ------------------------------------------------------------------

def _code_hash(user_id: uuid.UUID, code: str) -> str:
    # Keyed and bound to the user, so a leaked table can't be brute-forced offline or replayed across users.
    key = get_settings().jwt_secret.encode()
    return hmac.new(key, f"{user_id}:{code}".encode(), "sha256").hexdigest()


def start_login_code(db: Session, email: str, *, ip: str | None) -> tuple[str, str] | None:
    """Returns (email, code) to send, or None. Callers respond identically either way."""
    settings = get_settings()
    user = users_repo.get_by_email(db, email)
    if user is None or not user.is_active:
        return None
    now = utcnow()
    recent = db.scalar(select(LoginCode.created_at).where(LoginCode.user_id == user.id)
                       .order_by(LoginCode.created_at.desc()).limit(1))
    if recent and (now - recent).total_seconds() < settings.login_code_resend_seconds:
        return None  # one email per cooldown, however often "Resend" is pressed
    db.execute(update(LoginCode).where(LoginCode.user_id == user.id, LoginCode.used_at.is_(None))
               .values(used_at=now))  # only the newest code works
    code = f"{secrets.randbelow(1_000_000):06d}"
    db.add(LoginCode(user_id=user.id, code_hash=_code_hash(user.id, code), requested_ip=ip,
                     expires_at=now + timedelta(minutes=settings.login_code_ttl_minutes)))
    db.commit()
    return user.email, code


def verify_login_code(db: Session, email: str, code: str, *, ip: str | None, user_agent: str | None) -> Session_:
    settings = get_settings()
    invalid = Unauthorized("That code is wrong or has expired", code="invalid_login_code")
    user = users_repo.get_by_email(db, email)
    if user is None:
        raise invalid
    now = utcnow()
    login_code = db.scalar(select(LoginCode).where(LoginCode.user_id == user.id, LoginCode.used_at.is_(None),
                                                   LoginCode.expires_at > now)
                           .order_by(LoginCode.created_at.desc()).limit(1).with_for_update())
    if login_code is None:
        raise invalid
    login_code.attempts += 1
    if not hmac.compare_digest(login_code.code_hash, _code_hash(user.id, code)):
        if login_code.attempts >= settings.login_code_max_attempts:
            login_code.used_at = now  # too many guesses: this code is dead, request a new one
        db.commit()
        log.info("auth.login_code_failed", extra={"ip": ip})
        raise invalid
    if not user.is_active:
        raise Forbidden("This account has been disabled", code="account_disabled")
    login_code.used_at = now
    user.last_login_at = now
    session = issue_session(db, user, ip=ip, user_agent=user_agent)
    db.commit()
    return session


def refresh(db: Session, raw_token: str | None, *, ip: str | None, user_agent: str | None) -> Session_:
    if not raw_token:
        raise Unauthorized("No refresh token", code="refresh_missing")
    now = utcnow()
    token = users_repo.get_refresh_token(db, hash_token(raw_token), for_update=True)
    if token is None or token.revoked_at is not None or token.expires_at <= now:
        raise Unauthorized("Session expired, please sign in again", code="refresh_invalid")
    if token.rotated_at is not None and now - token.rotated_at > ROTATION_GRACE:
        # A long-rotated token being replayed means it was copied: end every session in its family.
        users_repo.revoke_family(db, token.family_id, now)
        db.commit()
        log.warning("auth.refresh_reuse_detected", extra={"user_id": str(token.user_id), "ip": ip})
        raise Unauthorized("Session expired, please sign in again", code="refresh_reused")
    user = db.get(User, token.user_id)
    if user is None or not user.is_active:
        raise Unauthorized("Account is unavailable", code="account_unavailable")
    token.rotated_at = token.rotated_at or now
    session = issue_session(db, user, family_id=token.family_id, ip=ip, user_agent=user_agent)
    db.commit()
    return session


def logout(db: Session, raw_token: str | None) -> None:
    if not raw_token:
        return
    token = users_repo.get_refresh_token(db, hash_token(raw_token))
    if token is not None:
        users_repo.revoke_family(db, token.family_id, utcnow())
        db.commit()


def start_password_reset(db: Session, email: str, *, ip: str | None) -> tuple[str, str] | None:
    """Returns (email, reset_link) to send, or None. Callers always respond identically."""
    user = users_repo.get_by_email(db, email)
    if user is None or not user.is_active:
        return None
    now = utcnow()
    users_repo.invalidate_reset_tokens(db, user.id, now)
    raw = generate_opaque_token()
    db.add(PasswordResetToken(
        user_id=user.id, token_hash=hash_token(raw), requested_ip=ip,
        expires_at=now + timedelta(minutes=get_settings().password_reset_ttl_minutes),
    ))
    db.commit()
    return user.email, f"{get_settings().frontend_url}/reset-password?token={raw}"


def complete_password_reset(db: Session, raw_token: str, new_password: str) -> None:
    now = utcnow()
    token = users_repo.get_reset_token(db, hash_token(raw_token))
    if token is None or token.used_at is not None or token.expires_at <= now:
        raise AppError("This reset link is invalid or has expired", code="reset_token_invalid")
    user = db.get(User, token.user_id)
    if user is None or not user.is_active:
        raise AppError("This reset link is invalid or has expired", code="reset_token_invalid")
    user.password_hash = hash_password(new_password)
    token.used_at = now
    users_repo.revoke_all_for_user(db, user.id, now)  # sign out everywhere after a reset
    db.commit()
    log.info("auth.password_reset", extra={"user_id": str(user.id)})


# --- Google OAuth (authorization code flow) -------------------------------------------------

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://openidconnect.googleapis.com/v1/userinfo"


def google_redirect_uri() -> str:
    return f"{get_settings().backend_public_url}/api/v1/auth/google/callback"


def google_authorization_url() -> tuple[str, str]:
    """Returns (url, nonce). The nonce goes in a cookie so the callback is bound to this browser."""
    settings = get_settings()
    nonce = generate_opaque_token(16)
    params = {
        "client_id": settings.google_client_id, "redirect_uri": google_redirect_uri(),
        "response_type": "code", "scope": "openid email profile",
        "state": create_oauth_state_token(nonce), "prompt": "select_account",
    }
    return f"{GOOGLE_AUTH_URL}?{urlencode(params)}", nonce


def _fetch_google_profile(code: str) -> dict:
    settings = get_settings()
    with httpx.Client(timeout=10) as client:
        token_res = client.post(GOOGLE_TOKEN_URL, data={
            "code": code, "client_id": settings.google_client_id,
            "client_secret": settings.google_client_secret,
            "redirect_uri": google_redirect_uri(), "grant_type": "authorization_code",
        })
        if token_res.status_code != 200:
            try:
                reason = token_res.json().get("error") or ""
            except ValueError:
                reason = ""
            log.warning("auth.google_token_exchange_failed", extra={"status": token_res.status_code, "reason": reason})
            if reason in ("invalid_client", "unauthorized_client", "redirect_uri_mismatch"):
                # Server configuration, not the user's fault: GOOGLE_CLIENT_ID/SECRET or the redirect URI.
                raise Unauthorized("Google sign-in is misconfigured on this server", code="oauth_misconfigured")
            raise Unauthorized("Google sign-in failed", code="oauth_failed")
        access_token = token_res.json().get("access_token")
        info = client.get(GOOGLE_USERINFO_URL, headers={"Authorization": f"Bearer {access_token}"})
        if info.status_code != 200:
            raise Unauthorized("Google sign-in failed", code="oauth_failed")
        return info.json()


def google_login(db: Session, *, code: str, state: str, cookie_nonce: str | None,
                 ip: str | None, user_agent: str | None) -> Session_:
    payload = decode_token(state, "oauth_state")
    if cookie_nonce and payload.get("nonce") != cookie_nonce:
        raise Unauthorized("OAuth state mismatch", code="oauth_state_invalid")
    profile = _fetch_google_profile(code)
    sub, email = profile.get("sub"), (profile.get("email") or "").lower()
    if not sub or not email or not profile.get("email_verified"):
        raise Unauthorized("Your Google account email is not verified", code="oauth_email_unverified")

    user = users_repo.get_by_google_sub(db, sub)
    if user is None:
        user = users_repo.get_by_email(db, email)
        if user is not None:
            user.google_sub = sub  # link: Google has verified ownership of this email
        else:
            user = User(email=email, display_name=(profile.get("name") or email.split("@")[0])[:80],
                        google_sub=sub, avatar_url=profile.get("picture"),
                        role_id=ROLE_IDS[RoleName.listener])
            db.add(user)
            db.flush()
            db.refresh(user, ["role"])
    if not user.is_active:
        raise Forbidden("This account has been disabled", code="account_disabled")
    user.last_login_at = utcnow()
    session = issue_session(db, user, ip=ip, user_agent=user_agent)
    db.commit()
    return session
