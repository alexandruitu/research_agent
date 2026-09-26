import pytest
from conftest import PASSWORD
from fastapi.testclient import TestClient


@pytest.mark.parametrize("role,status", [("viewer", 403), ("member", 403), ("admin", 200)])
def test_list_users_is_admin_only(sign_in, role, status):
    client, _csrf = sign_in(role)
    r = client.get("/api/v1/users")
    assert r.status_code == status
    if status == 200:
        assert {u["email"] for u in r.json()} >= {
            "viewer@example.org",
            "member@example.org",
            "admin@example.org",
        }
        assert all("password" not in u for u in r.json())


def test_create_user_then_sign_in_as_them(sign_in, app):
    client, csrf = sign_in("admin")
    r = client.post(
        "/api/v1/users",
        json={"email": "Nia@Example.org", "name": "Nia", "role": "member", "password": PASSWORD},
        headers=csrf,
    )
    assert r.status_code == 201 and r.json()["email"] == "nia@example.org" and r.json()["role"] == "member"
    fresh = TestClient(app)
    assert (
        fresh.post("/api/v1/auth/login", json={"email": "nia@example.org", "password": PASSWORD}).status_code
        == 200
    )


def test_create_user_validation_and_duplicates(sign_in):
    client, csrf = sign_in("admin")
    body = {"email": "x@example.org", "name": "X", "role": "member", "password": PASSWORD}
    assert client.post("/api/v1/users", json=body, headers=csrf).status_code == 201
    dup = client.post("/api/v1/users", json=body, headers=csrf)
    assert dup.status_code == 409 and dup.json()["code"] == "conflict"
    short = client.post(
        "/api/v1/users", json={**body, "email": "y@example.org", "password": "short"}, headers=csrf
    )
    assert short.status_code == 422 and short.json()["code"] == "invalid_user"
    assert client.post("/api/v1/users", json=body).status_code == 403  # no CSRF header


def test_patch_role_and_deactivate_revokes_sessions(sign_in, users):
    admin, csrf = sign_in("admin")
    member, _ = sign_in("member")
    assert member.get("/api/v1/auth/me").status_code == 200
    r = admin.patch(f"/api/v1/users/{users['member'].id}", json={"active": False}, headers=csrf)
    assert r.status_code == 200 and r.json()["active"] is False
    assert member.get("/api/v1/auth/me").status_code == 401  # sessions revoked immediately
    up = admin.patch(f"/api/v1/users/{users['viewer'].id}", json={"role": "member"}, headers=csrf)
    assert up.json()["role"] == "member"


def test_the_last_active_admin_cannot_be_demoted_or_deactivated(sign_in, users):
    admin, csrf = sign_in("admin")
    for patch in ({"role": "viewer"}, {"active": False}):
        r = admin.patch(f"/api/v1/users/{users['admin'].id}", json=patch, headers=csrf)
        assert r.status_code == 409 and r.json()["code"] == "last_admin"


def test_patch_unknown_user_is_404(sign_in):
    admin, csrf = sign_in("admin")
    r = admin.patch(
        "/api/v1/users/00000000-0000-0000-0000-000000000000", json={"role": "viewer"}, headers=csrf
    )
    assert r.status_code == 404
