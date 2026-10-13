import json
import time

from app.billing.signature import sign_payload
from app.core.permissions import RoleName
from tests.conftest import PASSWORD


def test_rbac_on_admin_endpoints(client, factory):
    listener = factory.headers(factory.user())
    manager = factory.headers(factory.user(RoleName.content_manager))
    admin = factory.headers(factory.user(RoleName.admin))
    for path in ("/api/v1/admin/stats", "/api/v1/admin/users", "/api/v1/admin/webhooks", "/api/v1/admin/subscriptions"):
        assert client.get(path, headers=listener).status_code == 403
        assert client.get(path, headers=admin).status_code == 200
    # Content managers see analytics and moderate playlists, but can't manage users or billing.
    assert client.get("/api/v1/admin/stats", headers=manager).status_code == 200
    assert client.get("/api/v1/admin/playlists", headers=manager).status_code == 200
    assert client.get("/api/v1/admin/users", headers=manager).status_code == 403
    assert client.get("/api/v1/admin/subscriptions", headers=manager).status_code == 403


def test_user_management(client, factory):
    admin = factory.user(RoleName.admin)
    target = factory.user()
    h = factory.headers(admin)
    found = client.get("/api/v1/admin/users", params={"q": target.email[:6]}, headers=h).json()
    assert any(u["id"] == str(target.id) for u in found["items"])

    promoted = client.patch(f"/api/v1/admin/users/{target.id}", json={"role": "content_manager"}, headers=h).json()
    assert promoted["role"] == "content_manager"
    assert client.patch(f"/api/v1/admin/users/{admin.id}", json={"role": "listener"}, headers=h).status_code == 403
    assert client.patch(f"/api/v1/admin/users/{admin.id}", json={"is_active": False}, headers=h).status_code == 403

    client.patch(f"/api/v1/admin/users/{target.id}", json={"is_active": False}, headers=h)
    login = client.post("/api/v1/auth/login", json={"email": target.email, "password": PASSWORD})
    assert login.status_code == 403 and login.json()["error"]["code"] == "account_disabled"
    assert client.delete(f"/api/v1/admin/users/{target.id}", headers=h).status_code == 200
    assert client.delete(f"/api/v1/admin/users/{admin.id}", headers=h).status_code == 403


def test_grant_and_revoke_premium(client, factory):
    admin, user = factory.user(RoleName.admin), factory.user()
    h = factory.headers(admin)
    assert client.post(f"/api/v1/admin/users/{user.id}/grant-premium", json={"days": 7}, headers=h).status_code == 200
    assert client.get("/api/v1/me", headers=factory.headers(user)).json()["is_premium"] is True
    subs = client.get("/api/v1/admin/subscriptions", headers=h).json()["items"]
    assert subs[0]["provider"] == "manual" and subs[0]["user_email"] == user.email
    client.post(f"/api/v1/admin/subscriptions/{subs[0]['id']}/revoke", headers=h)
    assert client.get("/api/v1/me", headers=factory.headers(user)).json()["is_premium"] is False


def test_stats_and_analytics(client, catalog, factory):
    user = factory.user()
    for _ in range(3):
        client.post("/api/v1/me/history", json={"song_id": catalog["songs"][0]["id"], "ms_played": 60_000},
                    headers=factory.headers(user))
    admin_h = factory.headers(factory.user(RoleName.admin))
    stats = client.get("/api/v1/admin/stats", headers=admin_h).json()
    assert stats["songs"] == 3 and stats["plays_24h"] == 3 and stats["active_users_30d"] == 1
    data = client.get("/api/v1/admin/analytics", params={"days": 7}, headers=admin_h).json()
    assert len(data["plays"]) == 7 and data["plays"][-1]["value"] == 3
    assert data["top_songs"][0]["name"] == "Midnight Run" and data["top_songs"][0]["value"] == 3
    assert data["top_artists"][0]["name"] == "Neon Drift"


def test_webhook_log_and_manual_retry(client, factory, db):
    admin_h = factory.headers(factory.user(RoleName.admin))
    payload = json.dumps({"id": "evt_orphan", "type": "invoice.paid", "created": int(time.time()),
                          "data": {"object": {"id": "in_o", "customer": "cus_unknown", "amount_paid": 1}}}).encode()
    client.post("/api/v1/webhooks/stripe", content=payload,
                headers={"Stripe-Signature": sign_payload(payload, "whsec_test_secret")})
    failed = client.get("/api/v1/admin/webhooks", params={"status": "failed"}, headers=admin_h).json()
    assert failed["total"] == 1
    event = client.get(f"/api/v1/admin/webhooks/{failed['items'][0]['id']}", headers=admin_h).json()
    assert event["payload"]["id"] == "evt_orphan"

    user = factory.user()
    from app.models import User

    db.get(User, user.id).billing_customer_id = "cus_unknown"
    db.commit()
    retried = client.post(f"/api/v1/admin/webhooks/{event['id']}/retry", headers=admin_h).json()
    assert retried["status"] == "processed" and retried["attempts"] == 2
    assert client.get("/api/v1/admin/payments", headers=admin_h).json()["total"] == 1


def test_moderator_can_delete_any_playlist(client, factory):
    owner = factory.user()
    pl = client.post("/api/v1/playlists", json={"name": "Spam", "is_public": False}, headers=factory.headers(owner)).json()
    mod_h = factory.headers(factory.user(RoleName.content_manager))
    listed = client.get("/api/v1/admin/playlists", headers=mod_h).json()
    assert listed["items"][0]["id"] == pl["id"]
    assert client.delete(f"/api/v1/playlists/{pl['id']}", headers=mod_h).status_code == 200


def test_health(client):
    assert client.get("/health").json() == {"status": "ok"}
    assert client.get("/health/ready").json() == {"status": "ready"}
    spec = client.get("/openapi.json").json()
    assert spec["info"]["title"] == "Wavely API" and "/api/v1/search" in spec["paths"]
    assert client.get("/docs").status_code == 200
