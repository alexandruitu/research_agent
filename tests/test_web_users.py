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


def _second_admin(db):
    from research_agent.web.auth import create_user

    other = create_user(db, email="ada2@example.org", name="Ada Two", role="admin", password=PASSWORD)
    db.commit()
    return other


def test_edit_name_and_email_is_validated_and_case_insensitive_unique(sign_in, users, app):
    admin, csrf = sign_in("admin")
    url = f"/api/v1/users/{users['member'].id}"
    r = admin.patch(url, json={"name": "  Mia M ", "email": " Mia.New@Example.ORG "}, headers=csrf)
    assert r.status_code == 200 and r.json()["name"] == "Mia M" and r.json()["email"] == "mia.new@example.org"
    login = TestClient(app).post(
        "/api/v1/auth/login", json={"email": "mia.new@example.org", "password": PASSWORD}
    )
    assert login.status_code == 200
    dup = admin.patch(url, json={"email": "ADMIN@example.org"}, headers=csrf)
    assert dup.status_code == 409 and dup.json()["code"] == "conflict"
    for bad in ({"email": "not-an-email"}, {"email": "a b@x.org"}, {"name": "   "}):
        r = admin.patch(url, json=bad, headers=csrf)
        assert r.status_code == 422 and r.json()["code"] == "invalid_user", bad
    assert (
        admin.patch(url, json={"email": "mia.new@example.org"}, headers=csrf).status_code == 200
    )  # own email


def test_reset_password_revokes_sessions_and_never_echoes(sign_in, users, app, caplog):
    admin, csrf = sign_in("admin")
    member, _ = sign_in("member")
    url = f"/api/v1/users/{users['member'].id}/password"
    short = admin.post(url, json={"password": "short"}, headers=csrf)
    assert short.status_code == 422 and short.json()["code"] == "invalid_user"
    assert member.get("/api/v1/auth/me").status_code == 200
    new = "a brand new password"
    with caplog.at_level("DEBUG"):
        r = admin.post(url, json={"password": new}, headers=csrf)
    assert r.status_code == 204 and r.content == b""
    assert new not in caplog.text
    assert member.get("/api/v1/auth/me").status_code == 401
    fresh = TestClient(app)
    assert (
        fresh.post(
            "/api/v1/auth/login", json={"email": "member@example.org", "password": PASSWORD}
        ).status_code
        == 401
    )
    assert (
        fresh.post("/api/v1/auth/login", json={"email": "member@example.org", "password": new}).status_code
        == 200
    )
    viewer, vcsrf = sign_in("viewer")
    assert viewer.post(url, json={"password": new}, headers=vcsrf).status_code == 403


def test_references_preview_and_hard_delete(sign_in, users, db):
    from research_agent.web.db.models import AuthSession, User

    admin, csrf = sign_in("admin")
    sign_in("viewer")
    vid = users["viewer"].id
    preview = admin.get(f"/api/v1/users/{vid}/references").json()
    assert preview == {"total": 0, "by_table": {}, "outcome": "delete"}
    r = admin.delete(f"/api/v1/users/{vid}", headers=csrf)
    assert r.status_code == 200 and r.json() == {"outcome": "deleted", "user": None}
    db.expire_all()
    assert db.get(User, vid) is None
    assert db.query(AuthSession).filter(AuthSession.user_id == vid).count() == 0
    assert admin.get(f"/api/v1/users/{vid}/references").status_code == 404


def test_referenced_user_is_anonymized_hidden_and_cannot_sign_in(sign_in, users, db, app):
    from research_agent.web.db.models import Collection

    admin, csrf = sign_in("admin")
    member, _ = sign_in("member")
    mid = users["member"].id
    db.add(Collection(name="Mia's picks", description="", created_by=mid))
    db.commit()
    preview = admin.get(f"/api/v1/users/{mid}/references").json()
    assert preview["outcome"] == "anonymize" and preview["by_table"] == {"collections.created_by": 1}
    r = admin.delete(f"/api/v1/users/{mid}", headers=csrf)
    body = r.json()
    assert r.status_code == 200 and body["outcome"] == "anonymized"
    assert body["user"]["name"] == "Deleted user" and body["user"]["active"] is False
    assert body["user"]["email"].startswith("deleted-") and body["user"]["email"].endswith("@invalid")
    assert body["user"]["deleted_at"]
    assert member.get("/api/v1/auth/me").status_code == 401
    fresh = TestClient(app)
    assert (
        fresh.post(
            "/api/v1/auth/login", json={"email": "member@example.org", "password": PASSWORD}
        ).status_code
        == 401
    )
    assert mid not in {u["id"] for u in admin.get("/api/v1/users").json()}
    shown = {u["id"]: u for u in admin.get("/api/v1/users", params={"include_deleted": True}).json()}
    assert shown[str(mid)]["name"] == "Deleted user"
    assert admin.patch(f"/api/v1/users/{mid}", json={"active": True}, headers=csrf).status_code == 404
    assert admin.delete(f"/api/v1/users/{mid}", headers=csrf).status_code == 404
    # the email is free again
    again = admin.post(
        "/api/v1/users",
        json={"email": "member@example.org", "name": "M", "role": "member", "password": PASSWORD},
        headers=csrf,
    )
    assert again.status_code == 201


def test_an_admin_cannot_delete_deactivate_or_demote_themselves(sign_in, users, db):
    _second_admin(db)
    admin, csrf = sign_in("admin")
    me = f"/api/v1/users/{users['admin'].id}"
    for call in (
        lambda: admin.patch(me, json={"role": "member"}, headers=csrf),
        lambda: admin.patch(me, json={"active": False}, headers=csrf),
        lambda: admin.delete(me, headers=csrf),
    ):
        r = call()
        assert r.status_code == 409 and r.json()["code"] == "self"
    assert admin.patch(me, json={"name": "Ada"}, headers=csrf).status_code == 200  # editing yourself is fine


def test_the_last_active_admin_cannot_be_deleted_and_other_admins_can(sign_in, users, db):
    other = _second_admin(db)
    admin, csrf = sign_in("admin")
    r = admin.delete(f"/api/v1/users/{other.id}", headers=csrf)
    assert r.status_code == 200 and r.json()["outcome"] == "deleted"
    r = admin.delete(f"/api/v1/users/{users['admin'].id}", headers=csrf)
    assert r.status_code == 409 and r.json()["code"] == "last_admin"


def test_user_admin_endpoints_need_admin_and_csrf(sign_in, users):
    member, mcsrf = sign_in("member")
    vid = users["viewer"].id
    assert member.get(f"/api/v1/users/{vid}/references").status_code == 403
    assert member.delete(f"/api/v1/users/{vid}", headers=mcsrf).status_code == 403
    admin, _ = sign_in("admin")
    assert admin.delete(f"/api/v1/users/{vid}").status_code == 403  # no CSRF header
    assert admin.post(f"/api/v1/users/{vid}/password", json={"password": "x" * 20}).status_code == 403
