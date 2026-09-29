"""Review settings (versioned, admins write, always runnable) and the available models."""

from research_agent.panel import DEFAULT_EDITOR
from research_agent.schemas import Thresholds
from research_agent.web.db.models import WorkerStatus

API = "/api/v1"


def content(current, **changes):
    keys = ("models", "screening", "fulltext", "default_panel", "editor")
    return {k: current[k] for k in keys} | {"base_version": current["version"], "note": "n"} | changes


def test_everyone_reads_the_current_settings_and_defaults(sign_in):
    viewer, _ = sign_in("viewer")
    data = viewer.get(f"{API}/settings/review").json()
    current = data["current"]
    assert current["version"] == 1 and current["note"] == "default" and current["imported"] is False
    assert current["models"] == {"plan": None, "screen": None, "screen_criteria": None, "extract": None}
    assert current["screening"] == Thresholds().model_dump()
    assert current["fulltext"] == {
        "sources": ["pmc_oa", "upload"],
        "contact": None,
        "max_chars": 60000,
        "upload_max_mb": 30,
    }
    assert current["default_panel"] == ["methodologist", "clinician", "statistician"]
    assert current["editor"] == DEFAULT_EDITOR and current["run_count"] == 0
    assert [v["version"] for v in data["versions"]] == [1]
    assert data["defaults"]["default_panel"] == current["default_panel"]


def test_admin_saves_a_new_version_and_stale_saves_fail(sign_in):
    admin, csrf = sign_in("admin")
    member, member_csrf = sign_in("member")
    current = admin.get(f"{API}/settings/review").json()["current"]
    change = content(
        current,
        models={**current["models"], "screen": "anthropic:claude-x"},
        fulltext={
            "sources": ["unpaywall", "pmc_oa"],
            "contact": "team@example.org",
            "max_chars": 30000,
            "upload_max_mb": 10,
        },
        default_panel=["statistician", "methodologist"],
        screening={**current["screening"], "keep_min": 0.7},
    )
    assert member.post(f"{API}/settings/review", json=change, headers=member_csrf).status_code == 403
    assert admin.post(f"{API}/settings/review", json=change).status_code == 403  # no CSRF
    r = admin.post(f"{API}/settings/review", json=change, headers=csrf)
    assert r.status_code == 201, r.text
    saved = r.json()["current"]
    assert saved["version"] == 2 and saved["models"]["screen"] == "anthropic:claude-x"
    assert saved["fulltext"]["upload_max_mb"] == 10 and saved["default_panel"] == [
        "statistician",
        "methodologist",
    ]
    assert saved["created_by_name"] == "Admin"
    assert [v["version"] for v in r.json()["versions"]] == [2, 1]
    stale = admin.post(f"{API}/settings/review", json=change, headers=csrf)
    assert stale.status_code == 409 and stale.json()["code"] == "stale_version"
    assert stale.json()["message"] == "The review settings changed since you opened them (now v2)"
    # clinician left the default panel: it can now be archived
    assert admin.post(f"{API}/reviewers/clinician/archive", headers=csrf).status_code == 200


def test_settings_are_validated_as_a_runnable_review(sign_in):
    admin, csrf = sign_in("admin")
    current = admin.get(f"{API}/settings/review").json()["current"]
    unpaywall = content(current, fulltext={**current["fulltext"], "sources": ["unpaywall"]})
    r = admin.post(f"{API}/settings/review", json=unpaywall, headers=csrf)
    assert r.status_code == 422 and r.json()["code"] == "invalid_settings"
    assert "contact" in r.json()["message"]
    bands = content(current, screening={**current["screening"], "include_fail_max": 0.9})
    assert admin.post(f"{API}/settings/review", json=bands, headers=csrf).json()["code"] == "invalid_settings"
    unknown = content(current, default_panel=["nobody"])
    r = admin.post(f"{API}/settings/review", json=unknown, headers=csrf)
    assert r.status_code == 422 and r.json()["message"] == "Reviewer 'nobody' does not exist or is archived"
    for bad in (
        content(current, default_panel=[]),
        content(current, default_panel=["methodologist"] * 2),
        content(current, default_panel=["a1", "b1", "c1", "d1", "e1", "f1"]),
        content(current, fulltext={**current["fulltext"], "upload_max_mb": 31}),
        content(current, fulltext={**current["fulltext"], "max_chars": 100}),
        content(current, fulltext={**current["fulltext"], "sources": ["web"]}),
        content(current, fulltext={**current["fulltext"], "contact": "not an email"}),
        content(current, models={**current["models"], "other": "x"}),
    ):
        assert admin.post(f"{API}/settings/review", json=bad, headers=csrf).status_code == 422, bad
    assert admin.get(f"{API}/settings/review").json()["current"]["version"] == 1


def test_available_models_come_from_the_worker_check_and_the_settings(sign_in, db, monkeypatch):
    sentinel = "sk-ant-SENTINEL-models-1234567890"
    monkeypatch.setenv("ANTHROPIC_API_KEY", sentinel)
    viewer, _ = sign_in("viewer")
    assert viewer.get(f"{API}/models/available").json() == {"models": [], "providers": []}
    for role, provider, model, accepted in (
        ("screen", "anthropic", "anthropic:claude-a", True),
        ("extract", "anthropic", "anthropic:claude-a", True),
        ("review_b", "openai", "openai:gpt-x", False),
        ("jev", "typesafe", None, None),
    ):
        db.add(
            WorkerStatus(
                role=role,
                provider=provider,
                model=model,
                key_present=True,
                key_accepted=accepted,
                detail="",
                worker_id="w",
            )
        )
    db.commit()
    admin, csrf = sign_in("admin")
    current = admin.get(f"{API}/settings/review").json()["current"]
    change = content(current, editor={**current["editor"], "model": "anthropic:claude-editor"})
    assert admin.post(f"{API}/settings/review", json=change, headers=csrf).status_code == 201
    r = viewer.get(f"{API}/models/available")
    assert sentinel not in r.text
    data = r.json()
    assert data["providers"] == [
        {"provider": "anthropic", "key_present": True, "key_accepted": True},
        {"provider": "openai", "key_present": True, "key_accepted": False},
        {"provider": "typesafe", "key_present": True, "key_accepted": None},
    ]
    assert data["models"] == [
        {
            "id": "anthropic:claude-a",
            "provider": "anthropic",
            "available": True,
            "roles": ["extract", "screen"],
            "in_settings": False,
        },
        {
            "id": "anthropic:claude-editor",
            "provider": "anthropic",
            "available": True,
            "roles": [],
            "in_settings": True,
        },
        {
            "id": "openai:gpt-x",
            "provider": "openai",
            "available": False,
            "roles": ["review_b"],
            "in_settings": False,
        },
    ]
