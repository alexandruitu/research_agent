"""Runs management: list filters, rename/note/pin, detail (frozen config, timeline, resume), re-run, resume."""

import json
import uuid
from pathlib import Path

import pytest
from sqlalchemy import select

from research_agent.agents import PROMPT_VERSION
from research_agent.web.db.models import Job, Run, RunReviewer


@pytest.fixture
def research(imported, db, users):
    run = db.get(Run, imported["research"])
    run.created_by = users["member"].id
    db.commit()
    return run


def failed_run(db, research, owner, prompt_version=PROMPT_VERSION, status="failed", folder=None):
    folder = Path(folder or Path(research.folder).parent / uuid.uuid4().hex)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "manifest.json").write_text(json.dumps({"prompt_version": prompt_version}))
    run = Run(
        field_id=research.field_id,
        kind="research",
        status=status,
        error="boom" if status == "failed" else None,
        folder=str(folder),
        created_by=owner,
        manifest={"contract": {"topic": "retrieval augmented generation", "max_papers": 3, "mode": "demo"}},
    )
    db.add(run)
    db.commit()
    return run


def test_list_shows_owner_name_note_pin_with_pinned_first(sign_in, research, db, users):
    member, csrf = sign_in("member")
    other = failed_run(db, research, users["admin"].id)
    r = member.patch(f"/api/v1/runs/{research.id}", json={"name": "Baseline", "pinned": True}, headers=csrf)
    assert r.status_code == 200 and r.json()["name"] == "Baseline" and r.json()["pinned"] is True
    rows = member.get("/api/v1/runs", params={"kind": "research"}).json()
    assert rows[0]["id"] == str(research.id) and rows[0]["created_by_name"] == "Member"
    assert rows[0]["topic"] == "retrieval augmented generation"
    assert {r["id"] for r in rows} == {str(research.id), str(other.id)}


@pytest.mark.parametrize(
    "params,expected",
    [
        ({"status": "failed"}, {"other"}),
        ({"status": "done"}, {"research"}),
        ({"mine": "true"}, {"research"}),
        ({"q": "baseline"}, {"research"}),
        ({"q": "retrieval"}, {"research", "other"}),
        ({"created_from": "2999-01-01"}, set()),
    ],
)
def test_list_filters(sign_in, research, db, users, params, expected):
    member, csrf = sign_in("member")
    other = failed_run(db, research, users["admin"].id)
    member.patch(f"/api/v1/runs/{research.id}", json={"name": "Baseline"}, headers=csrf)
    names = {str(research.id): "research", str(other.id): "other"}
    rows = member.get("/api/v1/runs", params={"kind": "research", **params}).json()
    assert {names[r["id"]] for r in rows} == expected


def test_list_sort_by_papers(sign_in, research, db, users):
    member, _ = sign_in("member")
    failed_run(db, research, users["admin"].id)
    rows = member.get(
        "/api/v1/runs", params={"kind": "research", "sort": "papers", "direction": "asc"}
    ).json()
    assert [r["paper_count"] for r in rows] == sorted(r["paper_count"] for r in rows)


def test_only_the_creator_or_an_admin_may_rename(sign_in, research, db, users):
    viewer, viewer_csrf = sign_in("viewer")
    assert (
        viewer.patch(f"/api/v1/runs/{research.id}", json={"note": "x"}, headers=viewer_csrf).status_code
        == 403
    )
    admin_run = failed_run(db, research, users["admin"].id)
    member, csrf = sign_in("member")
    r = member.patch(f"/api/v1/runs/{admin_run.id}", json={"note": "x"}, headers=csrf)
    assert r.status_code == 403 and r.json()["code"] == "forbidden"
    admin, admin_csrf = sign_in("admin")
    r = admin.patch(f"/api/v1/runs/{research.id}", json={"note": "checked", "name": "  "}, headers=admin_csrf)
    assert r.status_code == 200 and r.json()["note"] == "checked" and r.json()["name"] is None
    long = member.patch(f"/api/v1/runs/{research.id}", json={"name": "x" * 201}, headers=csrf)
    assert long.status_code == 422


def test_detail_has_frozen_config_timeline_and_links(sign_in, research):
    viewer, _ = sign_in("viewer")
    body = viewer.get(f"/api/v1/runs/{research.id}").json()
    config = body["config"]
    assert (
        config["mode"] == "demo" and config["max_papers"] == 6 and config["prompt_version"] == PROMPT_VERSION
    )
    assert config["field_name"] and config["topic"] == "retrieval augmented generation"
    stages = body["timeline"]["stages"]
    assert stages and all(s["status"] == "completed" for s in stages)
    assert stages[0]["started_at"] and stages[0]["seconds"] is not None  # recorded since slice 7
    assert body["wall_seconds"] is not None and body["wall_seconds"] >= 0
    assert body["resume"] == {"allowed": False, "code": "not_resumable", "reason": body["resume"]["reason"]}
    assert body["links"]["papers"] == f"/?run={research.id}" and body["can_manage"] is False


def test_detail_says_why_resume_is_refused_when_the_prompt_version_changed(sign_in, research, db, users):
    member, csrf = sign_in("member")
    old = failed_run(db, research, users["member"].id, prompt_version="m0.9")
    body = member.get(f"/api/v1/runs/{old.id}").json()
    assert body["resume"]["allowed"] is False and body["resume"]["code"] == "prompt_version_changed"
    assert body["can_manage"] is True
    r = member.post(f"/api/v1/runs/{old.id}/resume", headers=csrf)
    assert r.status_code == 409 and r.json()["code"] == "prompt_version_changed"


def test_cancelled_runs_resume_but_only_for_their_creator_or_an_admin(sign_in, research, db, users):
    member, csrf = sign_in("member")
    mine = failed_run(db, research, users["member"].id, status="cancelled")
    assert member.get(f"/api/v1/runs/{mine.id}").json()["resume"]["allowed"] is True
    r = member.post(f"/api/v1/runs/{mine.id}/resume", headers=csrf)
    assert r.status_code == 202
    theirs = failed_run(db, research, users["admin"].id)
    assert member.post(f"/api/v1/runs/{theirs.id}/resume", headers=csrf).status_code == 403


def test_rerun_same_copies_the_frozen_requests(sign_in, research, db, users):
    member, csrf = sign_in("member")
    source = failed_run(db, research, users["admin"].id)
    source.manifest = {
        **source.manifest,
        "domain_request": {"topic": "frozen topic", "sources": [{"name": "europepmc", "max_results": 7}]},
        "review_request": {"schema": 1, "panel": []},
    }
    db.commit()
    headers = {**csrf, "Idempotency-Key": "rr-1"}
    r = member.post(f"/api/v1/runs/{source.id}/rerun", json={"config": "same"}, headers=headers)
    assert r.status_code == 202, r.text
    new = db.get(Run, uuid.UUID(r.json()["run_id"]))
    assert new.id != source.id and new.created_by == users["member"].id and new.status == "queued"
    assert new.manifest["domain_request"] == source.manifest["domain_request"]
    assert new.manifest["review_request"] == source.manifest["review_request"]
    assert new.manifest["contract"] == {"topic": "frozen topic", "max_papers": 3, "mode": "demo"}
    job = db.get(Job, uuid.UUID(r.json()["job"]["id"]))
    assert job.payload["domain"] == source.manifest["domain_request"] and job.payload["resume"] is False
    again = member.post(f"/api/v1/runs/{source.id}/rerun", json={"config": "same"}, headers=headers)
    assert again.status_code == 200 and again.json()["run_id"] == r.json()["run_id"]


def test_rerun_with_current_settings_uses_the_current_field_and_review(sign_in, research, db):
    member, csrf = sign_in("member")
    r = member.post(f"/api/v1/runs/{research.id}/rerun", json={"config": "current"}, headers=csrf)
    assert r.status_code == 202, r.text
    new = db.get(Run, uuid.UUID(r.json()["run_id"]))
    assert new.manifest["contract"]["max_papers"] == 6 and new.manifest["contract"]["mode"] == "demo"
    assert new.manifest["review_request"] and new.settings_version_id is not None
    assert db.scalars(select(RunReviewer).where(RunReviewer.run_id == new.id)).all()


def test_rerun_is_refused_for_eval_runs_and_viewers(sign_in, imported):
    viewer, viewer_csrf = sign_in("viewer")
    path = f"/api/v1/runs/{imported['research']}/rerun"
    assert viewer.post(path, json={"config": "same"}, headers=viewer_csrf).status_code == 403
    member, csrf = sign_in("member")
    r = member.post(f"/api/v1/runs/{imported['eval']}/rerun", json={"config": "same"}, headers=csrf)
    assert r.status_code == 409
