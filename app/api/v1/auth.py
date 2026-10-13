from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, Request, Response
from fastapi.responses import RedirectResponse
from fastapi.security import OAuth2PasswordRequestForm

from app.api.deps import DB
from app.core.config import get_settings
from app.core.errors import AppError, NotFound
from app.core.rate_limit import client_ip, rate_limit
from app.email.sender import send_email
from app.schemas.common import Message
from app.schemas.user import (
    AuthProviders,
    ForgotPasswordRequest,
    LoginCodeRequest,
    LoginCodeVerify,
    LoginRequest,
    RegisterRequest,
    ResetPasswordRequest,
    TokenResponse,
)
from app.services import auth as auth_service
from app.services.users import to_me

router = APIRouter(prefix="/auth", tags=["auth"])

REFRESH_PATH = "/"
OAUTH_NONCE_COOKIE = "wavely_oauth_nonce"


def _set_refresh_cookie(response: Response, token: str) -> None:
    settings = get_settings()
    response.set_cookie(
        settings.refresh_cookie_name, token, max_age=settings.refresh_token_ttl_days * 86400,
        httponly=True, secure=settings.cookie_secure, samesite="lax", path=REFRESH_PATH,
    )


def clear_refresh_cookie(response: Response) -> None:
    settings = get_settings()
    response.delete_cookie(settings.refresh_cookie_name, path=REFRESH_PATH,
                           secure=settings.cookie_secure, httponly=True, samesite="lax")


def token_response(db, response: Response, session: auth_service.Session_) -> TokenResponse:
    _set_refresh_cookie(response, session.refresh_token)
    return TokenResponse(access_token=session.access_token,
                         expires_in=get_settings().access_token_ttl_minutes * 60,
                         user=to_me(db, session.user))


def _ua(request: Request) -> str | None:
    return request.headers.get("user-agent")


@router.get("/providers", response_model=AuthProviders)
def providers() -> AuthProviders:
    return AuthProviders(google=get_settings().google_enabled)


@router.post("/register", response_model=TokenResponse, status_code=201,
             dependencies=[Depends(rate_limit("register"))])
def register(data: RegisterRequest, request: Request, response: Response, db: DB):
    session = auth_service.register(db, data, ip=client_ip(request), user_agent=_ua(request))
    return token_response(db, response, session)


@router.post("/login", response_model=TokenResponse, dependencies=[Depends(rate_limit("login"))])
def login(data: LoginRequest, request: Request, response: Response, db: DB):
    session = auth_service.authenticate(db, data.email, data.password, ip=client_ip(request), user_agent=_ua(request))
    return token_response(db, response, session)


@router.post("/login-code", response_model=Message, dependencies=[Depends(rate_limit("login-code", 5, 900))],
             summary="Email a one-time 6-digit sign-in code (same response whether or not the account exists)")
def request_login_code(data: LoginCodeRequest, request: Request, background: BackgroundTasks, db: DB):
    result = auth_service.start_login_code(db, data.email, ip=client_ip(request))
    if result:
        email, code = result
        ttl = get_settings().login_code_ttl_minutes
        background.add_task(send_email, email, f"{code} is your {get_settings().app_name} code",
                            f"Your sign-in code is {code}\n\nIt expires in {ttl} minutes and works once.\n\n"
                            "If you didn't try to sign in, you can ignore this email.")
    return Message(message="If an account exists for that email, we sent it a code")


@router.post("/login-code/verify", response_model=TokenResponse,
             dependencies=[Depends(rate_limit("login-code-verify", 10, 300))])
def verify_login_code(data: LoginCodeVerify, request: Request, response: Response, db: DB):
    session = auth_service.verify_login_code(db, data.email, data.code, ip=client_ip(request), user_agent=_ua(request))
    return token_response(db, response, session)


@router.post("/token", response_model=TokenResponse, dependencies=[Depends(rate_limit("login"))],
             summary="OAuth2 password flow (used by Swagger UI's Authorize button)")
def token(form: Annotated[OAuth2PasswordRequestForm, Depends()], request: Request, response: Response, db: DB):
    session = auth_service.authenticate(db, form.username, form.password, ip=client_ip(request), user_agent=_ua(request))
    return token_response(db, response, session)


@router.post("/refresh", response_model=TokenResponse, dependencies=[Depends(rate_limit("refresh", 60, 60))])
def refresh(request: Request, response: Response, db: DB):
    raw = (
        request.cookies.get(get_settings().refresh_cookie_name)
        or request.headers.get("x-refresh-token")
        or request.query_params.get("refresh_token")
    )
    try:
        session = auth_service.refresh(db, raw, ip=client_ip(request), user_agent=_ua(request))
    except AppError:
        clear_refresh_cookie(response)
        raise
    return token_response(db, response, session)


@router.post("/logout", response_model=Message)
def logout(request: Request, response: Response, db: DB):
    auth_service.logout(db, request.cookies.get(get_settings().refresh_cookie_name))
    clear_refresh_cookie(response)
    return Message(message="Signed out")


@router.post("/forgot-password", response_model=Message, dependencies=[Depends(rate_limit("forgot", 5, 900))])
def forgot_password(data: ForgotPasswordRequest, request: Request, background: BackgroundTasks, db: DB):
    result = auth_service.start_password_reset(db, data.email, ip=client_ip(request))
    if result:
        email, link = result
        ttl = get_settings().password_reset_ttl_minutes
        background.add_task(send_email, email, "Reset your Wavely password",
                            f"Someone asked to reset your Wavely password.\n\nReset it here (valid for {ttl} minutes):\n{link}\n\n"
                            "If this wasn't you, you can ignore this email.")
    # Same response either way, so this endpoint can't be used to discover accounts.
    return Message(message="If an account exists for that email, a reset link has been sent")


@router.post("/reset-password", response_model=Message, dependencies=[Depends(rate_limit("reset"))])
def reset_password(data: ResetPasswordRequest, response: Response, db: DB):
    auth_service.complete_password_reset(db, data.token, data.new_password)
    clear_refresh_cookie(response)
    return Message(message="Password updated. Please sign in with your new password")


@router.get("/google/login", summary="Start Google sign-in (browser redirect)")
def google_login():
    if not get_settings().google_enabled:
        raise NotFound("Google sign-in is not configured")
    url, nonce = auth_service.google_authorization_url()
    response = RedirectResponse(url, status_code=302)
    response.set_cookie(OAUTH_NONCE_COOKIE, nonce, max_age=600, httponly=True,
                        secure=get_settings().cookie_secure, samesite="lax", path=f"{REFRESH_PATH}/google")
    return response


@router.get("/google/callback", include_in_schema=False)
def google_callback(request: Request, db: DB, code: str | None = None, state: str | None = None,
                    error: str | None = None):
    settings = get_settings()
    if not settings.google_enabled:
        raise NotFound("Google sign-in is not configured")
    target = f"{settings.frontend_url}/auth/callback"
    if error or not code or not state:
        return RedirectResponse(f"{target}?error=oauth_cancelled", status_code=302)
    try:
        session = auth_service.google_login(
            db, code=code, state=state, cookie_nonce=request.cookies.get(OAUTH_NONCE_COOKIE),
            ip=client_ip(request), user_agent=_ua(request))
    except AppError as exc:
        return RedirectResponse(f"{target}?error={exc.code}", status_code=302)
    # The SPA receives tokens in URL for cross-port dev resilience, plus httpOnly cookie
    callback_url = f"{target}?token={session.access_token}&refresh_token={session.refresh_token}"
    response = RedirectResponse(callback_url, status_code=302)
    _set_refresh_cookie(response, session.refresh_token)
    response.delete_cookie(OAUTH_NONCE_COOKIE, path=f"{REFRESH_PATH}/google")
    return response
