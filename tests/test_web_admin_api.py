"""Sources, settings and worker status: everyone reads, only admins write."""

from research_agent.web.db.models import WorkerStatus

API = "/api/v1"


def test_everyone_lists_the_three_sources(sign_in):
    viewer, _ = sign_in("viewer")
    rows = viewer.get(f"{API}/sources").json()
    assert [(r["name"], r["label"], r["enabled"], r["max_results"]) for r in rows] == [
        ("europepmc", "Europe PMC", True, 100),
        ("openalex", "OpenAlex", False, 100),
        ("arxiv", "arXiv", False, 100),
    ]
    assert rows[0]["last_check_at"] is None and rows[0]["last_check_ok"] is None


def test_only_admins_change_sources(sign_in):
    member, csrf = sign_in("member")
    admin, admin_csrf = sign_in("admin")
    assert member.patch(f"{API}/sources/arxiv", json={"enabled": True}, headers=csrf).status_code == 403
    assert admin.patch(f"{API}/sources/arxiv", json={"enabled": True}).status_code == 403  # no CSRF
    r = admin.patch(f"{API}/sources/arxiv", json={"enabled": True, "max_results": 50}, headers=admin_csrf)
    assert r.status_code == 200 and r.json()["enabled"] is True and r.json()["max_results"] == 50
    assert admin.patch(f"{API}/sources/arxiv", json={"max_results": 20}, headers=admin_csrf).json()["enabled"]
    for bad in ({"max_results": 0}, {"max_results": 201}, {"enabled": "maybe"}, {"other": 1}):
        assert admin.patch(f"{API}/sources/arxiv", json=bad, headers=admin_csrf).status_code == 422
    assert admin.patch(f"{API}/sources/pubmed", json={}, headers=admin_csrf).status_code == 404


def test_contact_email_setting(sign_in):
    viewer, _ = sign_in("viewer")
    admin, csrf = sign_in("admin")
    assert viewer.get(f"{API}/settings").json() == {"contact_email": None}
    assert viewer.patch(f"{API}/settings", json={"contact_email": "a@b.org"}).status_code == 403
    r = admin.patch(f"{API}/settings", json={"contact_email": "team@example.org"}, headers=csrf)
    assert r.status_code == 200 and r.json() == {"contact_email": "team@example.org"}
    assert admin.patch(f"{API}/settings", json={}, headers=csrf).json() == {
        "contact_email": "team@example.org"
    }
    assert (
        admin.patch(f"{API}/settings", json={"contact_email": "not an email"}, headers=csrf).status_code
        == 422
    )
    assert admin.patch(f"{API}/settings", json={"contact_email": None}, headers=csrf).json() == {
        "contact_email": None
    }


def test_worker_status_lists_rows_and_never_a_key(sign_in, db, monkeypatch):
    sentinel = "sk-ant-SENTINEL-status-1234567890"
    monkeypatch.setenv("ANTHROPIC_API_KEY", sentinel)
    viewer, _ = sign_in("viewer")
    assert viewer.get(f"{API}/workers/status").json() == []
    db.add(
        WorkerStatus(
            role="screen",
            provider="anthropic",
            model="anthropic:claude-x",
            key_present=True,
            key_accepted=False,
            detail="rejected (401)",
            worker_id="w1",
        )
    )
    db.commit()
    r = viewer.get(f"{API}/workers/status")
    [row] = r.json()
    assert row["role"] == "screen" and row["key_present"] is True and row["key_accepted"] is False
    assert row["detail"] == "rejected (401)" and row["checked_at"]
    assert sentinel not in r.text
