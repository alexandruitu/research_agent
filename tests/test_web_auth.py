from datetime import timedelta

import pytest
from conftest import PASSWORD

from research_agent.web.auth import (
    AuthError,
    authenticate_password,
    create_user,
    load_session,
    revoke_session,
    start_session,
    utcnow,
)


def test_create_user_validates_and_hashes(db, settings):
    user = create_user(db, email="  New@Example.ORG ", name=" Nia ", role="member", password=PASSWORD)
    assert user.email == "new@example.org" and user.name == "Nia" and user.password_hash != PASSWORD
    with pytest.raises(AuthError, match="at least 12"):
        create_user(db, email="a@b.c", name="x", role="member", password="short")
    with pytest.raises(AuthError, match="already"):
        create_user(db, email="new@example.org", name="x", role="member", password=PASSWORD)
    with pytest.raises(AuthError, match="role"):
        create_user(db, email="q@b.c", name="x", role="root", password=PASSWORD)


def test_authenticate_password(db, users):
    assert authenticate_password(db, "member@example.org", PASSWORD).role == "member"
    assert authenticate_password(db, "member@example.org", "nope") is None
    assert authenticate_password(db, "ghost@example.org", PASSWORD) is None
    users["member"].active = False
    assert authenticate_password(db, "member@example.org", PASSWORD) is None


def test_session_lifecycle_idle_absolute_and_revoked(db, users, settings):
    now = utcnow()
    token, _row = start_session(db, users["viewer"], settings, now=now)
    assert load_session(db, token, settings, now=now + timedelta(hours=1))[1].email == "viewer@example.org"
    assert (
        load_session(db, token, settings, now=now + timedelta(hours=10)) is None
    )  # idle > 8 h since the hour-1 touch
    token2, row2 = start_session(db, users["viewer"], settings, now=now)
    row2.last_seen_at = now + timedelta(days=7, hours=1)  # keep it "active" so only absolute expiry fails
    assert load_session(db, token2, settings, now=now + timedelta(days=7, hours=1)) is None
    token3, row3 = start_session(db, users["viewer"], settings, now=now)
    revoke_session(db, row3, now=now)
    assert load_session(db, token3, settings, now=now) is None


def test_login_me_logout_flow(client, users):
    r = client.post("/api/v1/auth/login", json={"email": "member@example.org", "password": PASSWORD})
    assert r.status_code == 200
    body = r.json()
    assert body["user"]["role"] == "member" and body["csrf_token"] and "password" not in r.text
    assert "ra_session" in r.headers["set-cookie"] and "HttpOnly" in r.headers["set-cookie"]
    me = client.get("/api/v1/auth/me")
    assert me.status_code == 200 and me.json()["user"]["email"] == "member@example.org"
    assert client.post("/api/v1/auth/logout").status_code == 403  # no CSRF header
    ok = client.post("/api/v1/auth/logout", headers={"X-CSRF-Token": body["csrf_token"]})
    assert ok.status_code == 204
    assert client.get("/api/v1/auth/me").status_code == 401  # the session was revoked server-side


def test_wrong_password_is_generic_and_sets_no_cookie(client, users):
    r = client.post("/api/v1/auth/login", json={"email": "member@example.org", "password": "wrong"})
    assert r.status_code == 401 and r.json()["code"] == "invalid_credentials"
    assert "set-cookie" not in r.headers and r.json()["request_id"]
    ghost = client.post("/api/v1/auth/login", json={"email": "ghost@example.org", "password": "wrong"})
    assert ghost.json()["message"] == r.json()["message"]  # no user enumeration


def test_login_is_rate_limited_per_account_and_address(client, users):
    for _ in range(5):
        assert (
            client.post(
                "/api/v1/auth/login", json={"email": "member@example.org", "password": "x"}
            ).status_code
            == 401
        )
    blocked = client.post("/api/v1/auth/login", json={"email": "member@example.org", "password": PASSWORD})
    assert blocked.status_code == 429 and blocked.json()["code"] == "rate_limited"


def test_me_requires_a_session(client):
    r = client.get("/api/v1/auth/me")
    assert r.status_code == 401 and r.json()["code"] == "unauthorized"


def test_unknown_route_uses_the_error_shape(client):
    r = client.get("/api/v1/nope")
    assert r.status_code == 404 and set(r.json()) >= {"code", "message", "request_id"}
    assert r.headers["x-request-id"] == r.json()["request_id"]


def test_docs_and_openapi_are_not_exposed(client):
    for path in ("/docs", "/redoc", "/openapi.json", "/api/docs", "/api/openapi.json"):
        assert client.get(path).status_code == 404
