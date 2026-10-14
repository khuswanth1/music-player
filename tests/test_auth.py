from datetime import timedelta

from sqlalchemy import select, update

from app.core.security import utcnow
from app.models import RefreshToken
from tests.conftest import PASSWORD

REGISTER = {"email": "Ada@Example.com", "password": "harmony-123", "display_name": "Ada"}


def test_register_login_me(client):
    res = client.post("/api/v1/auth/register", json=REGISTER)
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["user"]["email"] == "ada@example.com"
    assert body["user"]["role"] == "listener" and body["user"]["is_premium"] is False
    cookie = res.headers["set-cookie"]
    assert "wavely_refresh=" in cookie and "HttpOnly" in cookie and "Path=/api/v1/auth" in cookie

    me = client.get("/api/v1/me", headers={"Authorization": f"Bearer {body['access_token']}"})
    assert me.status_code == 200 and me.json()["display_name"] == "Ada"

    login = client.post("/api/v1/auth/login", json={"email": "ADA@example.com", "password": "harmony-123"})
    assert login.status_code == 200


def test_register_validation_and_duplicates(client):
    assert client.post("/api/v1/auth/register", json=REGISTER).status_code == 201
    dup = client.post("/api/v1/auth/register", json={**REGISTER, "email": "ada@example.com"})
    assert dup.status_code == 409 and dup.json()["error"]["code"] == "email_taken"
    weak = client.post("/api/v1/auth/register", json={**REGISTER, "email": "b@example.com", "password": "short"})
    assert weak.status_code == 422
    assert weak.json()["error"]["details"][0]["field"] == "password"
    letters = client.post("/api/v1/auth/register", json={**REGISTER, "email": "c@example.com", "password": "onlyletters"})
    assert letters.status_code == 422


def test_login_failures_are_generic(client, factory):
    user = factory.user()
    wrong = client.post("/api/v1/auth/login", json={"email": user.email, "password": "nope-nope-1"})
    unknown = client.post("/api/v1/auth/login", json={"email": "ghost@example.com", "password": "nope-nope-1"})
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json()["error"]["message"] == unknown.json()["error"]["message"]


def test_protected_routes_require_auth(client):
    res = client.get("/api/v1/me")
    assert res.status_code == 401 and res.json()["error"]["code"] == "unauthorized"
    assert client.get("/api/v1/me", headers={"Authorization": "Bearer junk"}).status_code == 401


def test_refresh_rotation_and_reuse_detection(client, factory, db):
    user = factory.user()
    client.post("/api/v1/auth/login", json={"email": user.email, "password": PASSWORD})
    first = client.cookies.get("wavely_refresh")

    r1 = client.post("/api/v1/auth/refresh")
    assert r1.status_code == 200
    second = client.cookies.get("wavely_refresh")
    assert second and second != first

    # Replaying the first token within the grace window (two tabs racing) is tolerated...
    client.cookies.set("wavely_refresh", first, path="/api/v1/auth")
    assert client.post("/api/v1/auth/refresh").status_code == 200

    # ...but replaying it after the grace window is treated as theft: the whole family is revoked.
    db.execute(update(RefreshToken).where(RefreshToken.rotated_at.is_not(None))
               .values(rotated_at=utcnow() - timedelta(minutes=5)))
    db.commit()
    client.cookies.set("wavely_refresh", first, path="/api/v1/auth")
    reuse = client.post("/api/v1/auth/refresh")
    assert reuse.status_code == 401 and reuse.json()["error"]["code"] == "refresh_reused"
    client.cookies.set("wavely_refresh", second, path="/api/v1/auth")
    assert client.post("/api/v1/auth/refresh").status_code == 401
    assert all(t.revoked_at for t in db.scalars(select(RefreshToken)))


def test_logout_revokes_refresh(client, factory):
    user = factory.user()
    client.post("/api/v1/auth/login", json={"email": user.email, "password": PASSWORD})
    token = client.cookies.get("wavely_refresh")
    assert client.post("/api/v1/auth/logout").status_code == 200
    client.cookies.set("wavely_refresh", token, path="/api/v1/auth")
    assert client.post("/api/v1/auth/refresh").status_code == 401


def test_password_reset_flow(client, factory, monkeypatch):
    user = factory.user()
    sent = []
    monkeypatch.setattr("app.api.v1.auth.send_email", lambda to, subject, body: sent.append((to, body)))

    res = client.post("/api/v1/auth/forgot-password", json={"email": user.email})
    unknown = client.post("/api/v1/auth/forgot-password", json={"email": "nobody@example.com"})
    assert res.json() == unknown.json()  # no account enumeration
    assert len(sent) == 1 and sent[0][0] == user.email
    token = sent[0][1].split("token=")[1].split()[0]

    ok = client.post("/api/v1/auth/reset-password", json={"token": token, "new_password": "brand-new-99"})
    assert ok.status_code == 200
    again = client.post("/api/v1/auth/reset-password", json={"token": token, "new_password": "another-99x"})
    assert again.status_code == 400 and again.json()["error"]["code"] == "reset_token_invalid"
    assert client.post("/api/v1/auth/login", json={"email": user.email, "password": PASSWORD}).status_code == 401
    assert client.post("/api/v1/auth/login", json={"email": user.email, "password": "brand-new-99"}).status_code == 200


def test_profile_update_and_password_change(client, factory):
    user, other = factory.user(), factory.user()
    h = factory.headers(user)
    res = client.patch("/api/v1/me", json={"display_name": "  New Name "}, headers=h)
    assert res.json()["display_name"] == "New Name"
    taken = client.patch("/api/v1/me", json={"email": other.email}, headers=h)
    assert taken.status_code == 409
    bad = client.post("/api/v1/me/password", json={"current_password": "wrong", "new_password": "fresh-pass-1"}, headers=h)
    assert bad.status_code == 401
    good = client.post("/api/v1/me/password", json={"current_password": PASSWORD, "new_password": "fresh-pass-1"}, headers=h)
    assert good.status_code == 200 and good.json()["access_token"]


def test_avatar_upload_validates_content(client, factory):
    from tests.conftest import PNG_1PX

    h = factory.headers(factory.user())
    ok = client.post("/api/v1/me/avatar", headers=h, files={"file": ("a.png", PNG_1PX, "image/png")})
    assert ok.status_code == 200 and ok.json()["avatar_url"].startswith("/api/v1/media/images/avatars/")
    img = client.get(ok.json()["avatar_url"])
    assert img.status_code == 200 and img.content == PNG_1PX
    fake = client.post("/api/v1/me/avatar", headers=h, files={"file": ("evil.png", b"<script>x</script>", "image/png")})
    assert fake.status_code == 422


def test_rate_limit_on_login(client, factory, settings, monkeypatch):
    monkeypatch.setattr(settings, "rate_limit_enabled", True)
    monkeypatch.setattr(settings, "auth_rate_limit", 3)
    payload = {"email": "x@example.com", "password": "whatever-1"}
    codes = [client.post("/api/v1/auth/login", json=payload).status_code for _ in range(4)]
    assert codes == [401, 401, 401, 429]
    limited = client.post("/api/v1/auth/login", json=payload)
    assert limited.headers["retry-after"]


def test_security_headers_and_request_id(client):
    res = client.get("/api/v1/genres", headers={"X-Request-ID": "abc12345-test"})
    assert res.headers["x-request-id"] == "abc12345-test"
    assert res.headers["x-content-type-options"] == "nosniff"
    assert res.headers["x-frame-options"] == "DENY"
    assert "default-src 'none'" in res.headers["content-security-policy"]


def test_providers_and_google_disabled(client):
    assert client.get("/api/v1/auth/providers").json() == {"password": True, "google": False}
    assert client.get("/api/v1/auth/google/login", follow_redirects=False).status_code == 404


def test_disabled_user_cannot_use_token(client, factory, db):
    from app.models import User

    user = factory.user()
    h = factory.headers(user)
    db.get(User, user.id).is_active = False
    db.commit()
    assert client.get("/api/v1/me", headers=h).status_code == 401


def test_password_policy_matches_signup_form(client):
    base = {**REGISTER, "email": "p@example.com"}
    for bad, why in [("abc-12345", "10 characters"), ("abcdefghijk", "number or special"), ("1234567890!", "letter")]:
        res = client.post("/api/v1/auth/register", json={**base, "password": bad})
        assert res.status_code == 422, bad
        assert why in res.json()["error"]["details"][0]["message"]
    assert client.post("/api/v1/auth/register", json={**base, "password": "harmonyharmony?"}).status_code == 201


def test_register_with_profile_details(client):
    res = client.post("/api/v1/auth/register", json={**REGISTER, "date_of_birth": "2003-06-06", "gender": "man",
                                                     "marketing_emails": False})
    me = res.json()["user"]
    assert (me["date_of_birth"], me["gender"], me["marketing_emails"]) == ("2003-06-06", "man", False)
    young = client.post("/api/v1/auth/register", json={**REGISTER, "email": "kid@example.com", "date_of_birth": "2020-01-01"})
    assert young.status_code == 422 and "at least 13" in young.json()["error"]["details"][0]["message"]
    odd = client.post("/api/v1/auth/register", json={**REGISTER, "email": "o@example.com", "gender": "robot"})
    assert odd.status_code == 422


def _code_sender(monkeypatch):
    sent = []
    monkeypatch.setattr("app.api.v1.auth.send_email", lambda to, subject, body: sent.append((to, subject, body)))
    return sent


def test_login_with_email_code(client, factory, monkeypatch):
    user = factory.user()
    sent = _code_sender(monkeypatch)
    res = client.post("/api/v1/auth/login-code", json={"email": user.email.upper()})
    unknown = client.post("/api/v1/auth/login-code", json={"email": "nobody@example.com"})
    assert res.json() == unknown.json()  # no account enumeration
    assert len(sent) == 1 and sent[0][0] == user.email
    code = sent[0][1].split()[0]
    assert len(code) == 6 and code.isdigit() and code in sent[0][2]

    wrong = "000000" if code != "000000" else "111111"
    bad = client.post("/api/v1/auth/login-code/verify", json={"email": user.email, "code": wrong})
    assert bad.status_code == 401 and bad.json()["error"]["code"] == "invalid_login_code"
    ok = client.post("/api/v1/auth/login-code/verify", json={"email": user.email, "code": code})
    assert ok.status_code == 200 and ok.json()["user"]["email"] == user.email
    assert client.post("/api/v1/auth/refresh").status_code == 200  # a normal session, refresh cookie included
    reused = client.post("/api/v1/auth/login-code/verify", json={"email": user.email, "code": code})
    assert reused.status_code == 401  # one use only


def test_login_code_guessing_and_resend_limits(client, factory, monkeypatch, settings):
    user = factory.user()
    sent = _code_sender(monkeypatch)
    client.post("/api/v1/auth/login-code", json={"email": user.email})
    client.post("/api/v1/auth/login-code", json={"email": user.email})
    assert len(sent) == 1  # resend cooldown
    code = sent[0][1].split()[0]
    wrong = "000000" if code != "000000" else "111111"
    for _ in range(settings.login_code_max_attempts):
        client.post("/api/v1/auth/login-code/verify", json={"email": user.email, "code": wrong})
    burned = client.post("/api/v1/auth/login-code/verify", json={"email": user.email, "code": code})
    assert burned.status_code == 401  # the right code no longer works after too many guesses
    malformed = client.post("/api/v1/auth/login-code/verify", json={"email": user.email, "code": "12ab56"})
    assert malformed.status_code == 422


def test_refresh_cookie_is_scoped_and_the_old_root_cookie_is_expired(client, factory):
    user = factory.user()
    res = client.post("/api/v1/auth/login", json={"email": user.email, "password": PASSWORD})
    cookies = res.headers.get_list("set-cookie")
    scoped = [c for c in cookies if "wavely_refresh=" in c and "Path=/api/v1/auth" in c and "HttpOnly" in c]
    legacy = [c for c in cookies if "wavely_refresh=" in c and "Path=/;" in c]
    assert len(scoped) == 1 and not scoped[0].startswith('wavely_refresh="";')
    assert len(legacy) == 1 and "Max-Age=0" in legacy[0]


def test_refresh_token_is_never_accepted_from_the_url(client, factory):
    user = factory.user()
    client.post("/api/v1/auth/login", json={"email": user.email, "password": PASSWORD})
    token = client.cookies.get("wavely_refresh")
    client.cookies.clear()
    assert client.post("/api/v1/auth/refresh", params={"refresh_token": token}).status_code == 401
    assert client.post("/api/v1/auth/refresh", headers={"X-Refresh-Token": token}).status_code == 200
