import logging

import pytest
from fastapi.routing import APIRoute

try:  # FastAPI >= 0.14x wraps included routers; this yields the effective (prefixed) routes.
    from fastapi.routing import iter_route_contexts
except ImportError:  # older FastAPI: app.routes is already flat
    iter_route_contexts = None
from fastapi.testclient import TestClient

from research_agent.web.api.app import API_PREFIX, create_app
from research_agent.web.api.deps import get_db

PUBLIC = {("POST", f"{API_PREFIX}/auth/login"), ("GET", f"{API_PREFIX}/health")}
ROLES = ["viewer", "member", "admin"]
RANK = {"viewer": 0, "member": 1, "admin": 2}


def guards(dependant):
    found = []
    for dep in dependant.dependencies:
        if getattr(dep.call, "role", None):
            found.append(dep.call.role)
        found += guards(dep)
    return found


def api_routes(app):
    """(methods, path, dependant) for every API route, looking through included routers."""
    if iter_route_contexts is None:
        return [(r.methods, r.path, r.dependant) for r in app.routes if isinstance(r, APIRoute)]
    return [
        (c.methods, c.path, c.dependant)
        for c in iter_route_contexts(app.routes)
        if isinstance(c.original_route, APIRoute)
    ]


def test_every_route_declares_a_role_or_is_explicitly_public(app):
    unguarded, seen = set(), set()
    for methods, path, dependant in api_routes(app):
        for method in methods:
            seen.add((method, path))
            if not guards(dependant):
                unguarded.add((method, path))
    # The enumeration must actually see the routes, or the check below is vacuous.
    assert PUBLIC | {("GET", f"{API_PREFIX}/runs/{{run_id}}/calls/{{call_key}}")} <= seen, seen
    assert unguarded == PUBLIC, f"routes without a role guard: {unguarded - PUBLIC}"


def matrix(imported, paper_id):
    run, eval_run = imported["research"], imported["eval"]
    return [
        ("GET", "/auth/me", "viewer"),
        ("GET", "/users", "admin"),
        ("GET", "/fields", "viewer"),
        ("GET", "/runs", "viewer"),
        ("GET", f"/runs/{run}", "viewer"),
        ("GET", f"/runs/{eval_run}/papers", "viewer"),
        ("GET", f"/runs/{eval_run}/papers/{paper_id}", "viewer"),
        ("GET", f"/runs/{eval_run}/calls/{'0' * 64}", "member"),
        ("GET", "/stages", "viewer"),
        ("GET", "/evals", "viewer"),
        ("POST", "/users", "admin"),
        ("POST", "/runs", "member"),
        ("POST", f"/runs/{run}/resume", "member"),
        ("GET", f"/jobs/{'00000000-0000-0000-0000-000000000000'}", "member"),
        ("POST", "/imports", "admin"),
    ]


@pytest.mark.parametrize("role", ROLES)
def test_role_matrix(app, users, imported, db, role):
    from sqlalchemy import select

    from research_agent.web.db.models import Paper

    paper_id = db.scalar(select(Paper.id).where(Paper.source_id == "MED:1"))
    signed = TestClient(app)
    login = signed.post(
        "/api/v1/auth/login", json={"email": f"{role}@example.org", "password": "correct horse battery"}
    )
    csrf = {"X-CSRF-Token": login.json()["csrf_token"]}
    anonymous = TestClient(app)
    for method, path, minimum in matrix(imported, paper_id):
        url = f"{API_PREFIX}{path}"
        kwargs = {"json": {}} if method == "POST" else {}
        assert anonymous.request(method, url, **kwargs).status_code == 401, (method, path)
        allowed = RANK[role] >= RANK[minimum]
        status = signed.request(method, url, headers=csrf, **kwargs).status_code
        if allowed:
            assert status not in (401, 403), (role, method, path, status)
        else:
            assert status == 403, (role, method, path, status)
        if allowed and method == "POST":
            assert signed.request(method, url, **kwargs).status_code == 403, (
                "state change without CSRF must fail"
            )


def test_security_headers_are_on_every_response(client, sign_in):
    for response in (client.get("/api/v1/auth/me"), client.get("/api/v1/nope")):
        assert response.headers["x-content-type-options"] == "nosniff"
        assert response.headers["cache-control"] == "no-store"
        assert "frame-ancestors 'none'" in response.headers["content-security-policy"]
        assert response.headers["referrer-policy"] == "no-referrer"


def test_secrets_never_appear_in_responses_logs_or_error_bodies(
    settings, db, users, imported, monkeypatch, caplog
):
    sentinel = "sk-ant-SENTINEL-1234567890abcdef"
    monkeypatch.setenv("ANTHROPIC_API_KEY", sentinel)
    monkeypatch.setenv("TYPESAFE_API_KEY", sentinel)
    application = create_app(settings, session_factory=lambda: db)
    application.dependency_overrides[get_db] = lambda: db

    @application.get("/api/v1/boom")
    def boom():
        raise RuntimeError(f"provider said no, key {sentinel}")

    client = TestClient(application, raise_server_exceptions=False)
    login = client.post(
        "/api/v1/auth/login", json={"email": "member@example.org", "password": "correct horse battery"}
    )
    seen = [login.text, str(login.headers)]
    for path in ("/auth/me", "/fields", "/runs", "/stages", "/evals", "/nope"):
        r = client.get(f"/api/v1{path}")
        seen += [r.text, str(r.headers)]
    with caplog.at_level(logging.DEBUG):
        crash = client.get("/api/v1/boom")
    assert crash.status_code == 500 and crash.json()["code"] == "internal_error"
    assert crash.json()["message"] == "Unexpected error" and "provider" not in crash.text
    seen.append(crash.text)
    assert not any(sentinel in text for text in seen)
    # The server log records the failure for operators; the response never carries it.
    assert any("unhandled error" in record.getMessage() for record in caplog.records)


@pytest.mark.parametrize(
    "sent,echoed",
    [("abc-123_X.y", True), ("x" * 64, True), ("x" * 65, False), ("a b", False), ("<script>", False)],
)
def test_client_request_ids_are_echoed_only_when_short_and_plain(client, sent, echoed):
    rid = client.get("/api/v1/auth/me", headers={"X-Request-ID": sent}).headers["x-request-id"]
    if echoed:
        assert rid == sent
    else:
        assert rid != sent and 1 <= len(rid) <= 64 and rid.isalnum()
