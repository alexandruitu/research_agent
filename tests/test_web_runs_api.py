import uuid
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from web_fixtures import make_demo_run

from research_agent.web.api.app import create_app
from research_agent.web.api.deps import get_db
from research_agent.web.auth import create_user
from research_agent.web.db.models import Field, Job, Run

BODY = {"max_papers": 3, "mode": "demo"}


@pytest.fixture
def field_id(imported, db):
    return str(db.scalar(select(Field.id).where(Field.topic == "retrieval augmented generation")))


def start(client, csrf, field, **overrides):
    return client.post("/api/v1/runs", json={"field_id": field, **BODY, **overrides}, headers=csrf)


def test_health_is_public_and_touches_nothing(client):
    r = client.get("/api/v1/health")
    assert r.status_code == 200 and r.json() == {"status": "ok"}


def test_member_starts_a_run_which_is_queued_not_executed(sign_in, field_id, db, settings):
    member, csrf = sign_in("member")
    r = start(member, csrf, field_id)
    assert r.status_code == 202
    body = r.json()
    assert (
        body["job"]["status"] == "queued"
        and body["job"]["kind"] == "research"
        and body["job"]["run_id"] == body["run_id"]
    )
    run = db.get(Run, uuid.UUID(body["run_id"]))
    assert (
        run.status == "queued"
        and run.kind == "research"
        and run.folder == str(settings.runs_dir / run.id.hex)
    )
    assert run.manifest["contract"] == {
        "topic": "retrieval augmented generation",
        "max_papers": 3,
        "mode": "demo",
    }
    job = db.get(Job, uuid.UUID(body["job"]["id"]))
    assert job.payload["topic"] == "retrieval augmented generation" and job.payload["resume"] is False
    listed = {r["id"]: r for r in member.get("/api/v1/runs").json()}
    assert listed[body["run_id"]]["status"] == "queued" and listed[body["run_id"]]["paper_count"] == 0


def test_only_members_may_start_runs_and_csrf_is_required(sign_in, client, field_id):
    viewer, viewer_csrf = sign_in("viewer")
    assert start(viewer, viewer_csrf, field_id).status_code == 403
    assert client.post("/api/v1/runs", json={"field_id": field_id, **BODY}).status_code == 401
    member, _ = sign_in("member")
    assert (
        member.post("/api/v1/runs", json={"field_id": field_id, **BODY}).status_code == 403
    )  # no CSRF header


@pytest.mark.parametrize(
    "overrides,status",
    [
        ({"max_papers": 0}, 422),
        ({"max_papers": 13}, 422),
        ({"mode": "nope"}, 422),
        ({"field_id": str(uuid.uuid4())}, 404),
    ],
)
def test_validation(sign_in, field_id, overrides, status):
    member, csrf = sign_in("member")
    assert start(member, csrf, field_id, **overrides).status_code == status


def test_demo_mode_is_refused_when_the_deployment_disables_it(app, settings, db, users, field_id):
    strict = create_app(replace(settings, allow_demo=False), session_factory=lambda: db)
    strict.dependency_overrides[get_db] = lambda: db
    client = TestClient(strict)
    login = client.post(
        "/api/v1/auth/login", json={"email": "member@example.org", "password": "correct horse battery"}
    )
    r = start(client, {"X-CSRF-Token": login.json()["csrf_token"]}, field_id)
    assert r.status_code == 422 and "demo" in r.json()["message"]


def test_the_same_idempotency_key_returns_the_same_job(sign_in, field_id, db):
    member, csrf = sign_in("member")
    first = member.post(
        "/api/v1/runs", json={"field_id": field_id, **BODY}, headers={**csrf, "Idempotency-Key": "k1"}
    )
    again = member.post(
        "/api/v1/runs", json={"field_id": field_id, **BODY}, headers={**csrf, "Idempotency-Key": "k1"}
    )
    assert first.status_code == 202 and again.status_code == 200
    assert (
        again.json()["job"]["id"] == first.json()["job"]["id"]
        and again.json()["run_id"] == first.json()["run_id"]
    )
    assert db.scalar(select(func.count()).select_from(Job).where(Job.kind == "research")) == 1
    assert db.scalar(select(func.count()).select_from(Run).where(Run.status == "queued")) == 1


def test_a_member_cannot_have_more_active_runs_than_the_cap(sign_in, field_id):
    member, csrf = sign_in("member")
    assert [start(member, csrf, field_id).status_code for _ in range(2)] == [202, 202]
    third = start(member, csrf, field_id)
    assert third.status_code == 429 and third.json()["code"] == "too_many_active_runs"


def test_resume_only_for_failed_research_runs(sign_in, field_id, db, imported):
    member, csrf = sign_in("member")
    failed = Run(
        field_id=uuid.UUID(field_id),
        kind="research",
        status="failed",
        error="boom",
        folder="/x",
        manifest={"contract": {"topic": "retrieval augmented generation", "max_papers": 3, "mode": "demo"}},
    )
    db.add(failed)
    db.commit()
    r = member.post(f"/api/v1/runs/{failed.id}/resume", headers=csrf)
    assert r.status_code == 202 and r.json()["run_id"] == str(failed.id)
    db.refresh(failed)
    assert failed.status == "queued" and failed.error is None
    assert db.get(Job, uuid.UUID(r.json()["job"]["id"])).payload["resume"] is True
    again = member.post(f"/api/v1/runs/{failed.id}/resume", headers=csrf)  # now queued, not failed
    assert again.status_code == 409 and again.json()["code"] == "conflict"
    assert (
        member.post(f"/api/v1/runs/{imported['eval']}/resume", headers=csrf).status_code == 409
    )  # an eval run
    assert member.post(f"/api/v1/runs/{uuid.uuid4()}/resume", headers=csrf).status_code == 404


def test_jobs_are_visible_to_their_creator_and_admins_only(sign_in, app, users, db, field_id):
    member, csrf = sign_in("member")
    job_id = start(member, csrf, field_id).json()["job"]["id"]
    assert member.get(f"/api/v1/jobs/{job_id}").json()["id"] == job_id
    other = create_user(
        db, email="other@example.org", name="O", role="member", password="correct horse battery"
    )
    db.commit()
    stranger = TestClient(app)
    stranger.post(
        "/api/v1/auth/login", json={"email": "other@example.org", "password": "correct horse battery"}
    )
    assert stranger.get(f"/api/v1/jobs/{job_id}").status_code == 404
    admin, _ = sign_in("admin")
    assert admin.get(f"/api/v1/jobs/{job_id}").status_code == 200
    assert admin.get(f"/api/v1/jobs/{uuid.uuid4()}").status_code == 404
    assert other.role == "member"


def test_import_endpoint_queues_a_job_for_a_named_folder(sign_in, settings):
    make_demo_run(settings.runs_dir / "demo")
    admin, csrf = sign_in("admin")
    ok = admin.post("/api/v1/imports", json={"kind": "research", "name": "demo"}, headers=csrf)
    assert ok.status_code == 202 and ok.json()["kind"] == "import" and ok.json()["status"] == "queued"
    assert (
        admin.post("/api/v1/imports", json={"kind": "research", "name": "missing"}, headers=csrf).status_code
        == 404
    )
    for bad in ("../evals", "a/b", ".hidden", ""):
        assert (
            admin.post("/api/v1/imports", json={"kind": "research", "name": bad}, headers=csrf).status_code
            == 422
        )
    member, member_csrf = sign_in("member")
    assert (
        member.post(
            "/api/v1/imports", json={"kind": "research", "name": "demo"}, headers=member_csrf
        ).status_code
        == 403
    )


def test_import_endpoint_refuses_a_symlink_that_leaves_the_root(sign_in, settings, tmp_path):
    outside = make_demo_run(tmp_path / "elsewhere" / "run")
    settings.runs_dir.mkdir(parents=True, exist_ok=True)
    (settings.runs_dir / "escape").symlink_to(outside, target_is_directory=True)
    admin, csrf = sign_in("admin")
    r = admin.post("/api/v1/imports", json={"kind": "research", "name": "escape"}, headers=csrf)
    assert r.status_code == 404


def failed_run(db, field_id):
    run = Run(
        field_id=uuid.UUID(field_id),
        kind="research",
        status="failed",
        error="boom",
        folder=f"/x/{uuid.uuid4().hex}",
        manifest={"contract": {"topic": "retrieval augmented generation", "max_papers": 3, "mode": "demo"}},
    )
    db.add(run)
    db.commit()
    return run


def test_a_resume_that_loses_the_race_is_refused(sign_in, field_id, db):
    """Two resumes read `failed` at once; only the one whose UPDATE flips the row may enqueue."""
    from sqlalchemy import update

    member, csrf = sign_in("member")
    run = failed_run(db, field_id)
    # a concurrent resume already moved the row on; this session still holds the old `failed` copy
    db.execute(
        update(Run)
        .where(Run.id == run.id)
        .values(status="queued")
        .execution_options(synchronize_session=False)
    )
    db.commit()
    assert run.status == "failed"
    r = member.post(f"/api/v1/runs/{run.id}/resume", headers=csrf)
    assert r.status_code == 409 and r.json()["code"] == "conflict"
    assert db.scalar(select(func.count()).select_from(Job)) == 0


def test_a_run_whose_job_is_still_active_cannot_be_resumed(sign_in, field_id, db, users):
    from research_agent.web.jobs import enqueue

    member, csrf = sign_in("member")
    run = failed_run(db, field_id)
    enqueue(db, "research", {"run_id": str(run.id), "resume": True}, users["admin"].id)
    db.commit()
    r = member.post(f"/api/v1/runs/{run.id}/resume", headers=csrf)
    assert r.status_code == 409 and r.json()["code"] == "conflict"
    db.refresh(run)
    assert run.status == "failed" and run.error == "boom"
