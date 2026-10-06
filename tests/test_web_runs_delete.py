"""Cancel and delete research runs: permissions, rows, library snapshots, eval references, the trash."""

import uuid
from pathlib import Path

import pytest
from sqlalchemy import func, select

from research_agent.web.db.models import EvalReport, Job, LibraryItem, Run, Screening

BODY = {"max_papers": 3, "mode": "demo"}


@pytest.fixture
def research(imported, db, users):
    run = db.get(Run, imported["research"])
    run.created_by = users["member"].id
    db.commit()
    return run


def start(member, csrf, field_id):
    r = member.post("/api/v1/runs", json={"field_id": str(field_id), **BODY}, headers=csrf)
    assert r.status_code == 202, r.text
    return uuid.UUID(r.json()["run_id"])


def test_cancel_a_queued_run(sign_in, research, db):
    member, csrf = sign_in("member")
    run_id = start(member, csrf, research.field_id)
    other, other_csrf = sign_in("admin")
    r = member.post(f"/api/v1/runs/{run_id}/cancel", headers=csrf)
    assert r.status_code == 200 and r.json() == {"status": "cancelled"}
    assert db.get(Run, run_id).status == "cancelled"
    assert db.scalar(select(Job.status).where(Job.payload["run_id"].astext == str(run_id))) == "cancelled"
    again = other.post(f"/api/v1/runs/{run_id}/cancel", headers=other_csrf)
    assert again.status_code == 409 and again.json()["code"] == "not_active"


def test_cancel_a_running_run_sets_the_flag(sign_in, research, db):
    member, csrf = sign_in("member")
    run_id = start(member, csrf, research.field_id)
    job = db.scalar(select(Job).where(Job.payload["run_id"].astext == str(run_id)))
    job.status, job.locked_by = "running", "w1"
    db.get(Run, run_id).status = "running"
    db.commit()
    r = member.post(f"/api/v1/runs/{run_id}/cancel", headers=csrf)
    assert r.status_code == 202 and r.json() == {"status": "cancelling"}
    db.refresh(job)
    assert job.cancel_requested is True and job.status == "running"


def test_only_the_creator_or_an_admin_cancels_or_deletes(sign_in, research, users, db):
    admin, admin_csrf = sign_in("admin")
    run_id = start(admin, admin_csrf, research.field_id)
    member, csrf = sign_in("member")
    assert member.post(f"/api/v1/runs/{run_id}/cancel", headers=csrf).status_code == 403
    viewer, viewer_csrf = sign_in("viewer")
    assert viewer.delete(f"/api/v1/runs/{research.id}", headers=viewer_csrf).status_code == 403


def test_delete_keeps_library_snapshots_and_moves_the_folder_to_the_trash(sign_in, research, db, settings):
    paper_id = db.scalar(select(Screening.paper_id).where(Screening.run_id == research.id).limit(1))
    item = LibraryItem(
        paper_id=paper_id, snapshot={"run": {"id": str(research.id)}, "score": 70}, run_id=research.id
    )
    db.add(item)
    db.commit()
    folder = Path(research.folder)
    member, csrf = sign_in("member")
    r = member.delete(f"/api/v1/runs/{research.id}", headers=csrf)
    assert r.status_code == 200, r.text
    assert r.json()["folder"] == "trashed"
    assert db.get(Run, research.id) is None
    assert db.scalar(select(func.count()).select_from(Screening).where(Screening.run_id == research.id)) == 0
    db.refresh(item)
    assert item.run_id is None and item.snapshot["score"] == 70
    assert not folder.exists()
    trashed = list((settings.runs_dir / ".trash").iterdir())
    assert (
        len(trashed) == 1
        and trashed[0].name.startswith(research.id.hex)
        and (trashed[0] / "report.json").exists()
    )


def test_delete_is_refused_while_queued_or_running(sign_in, research):
    member, csrf = sign_in("member")
    run_id = start(member, csrf, research.field_id)
    r = member.delete(f"/api/v1/runs/{run_id}", headers=csrf)
    assert r.status_code == 409 and r.json()["code"] == "run_active"


def test_delete_is_refused_when_an_eval_report_was_made_from_the_run(sign_in, research, db, imported):
    eval_run = db.get(Run, imported["eval"])
    eval_run.manifest = {**eval_run.manifest, "source": {"run_dir": research.folder}}
    db.commit()
    member, csrf = sign_in("member")
    r = member.delete(f"/api/v1/runs/{research.id}", headers=csrf)
    assert r.status_code == 409 and r.json()["code"] == "referenced_by_eval"
    assert "evaluation" in r.json()["message"]
    assert db.get(Run, research.id) is not None
    admin, admin_csrf = sign_in("admin")
    assert admin.delete(f"/api/v1/runs/{imported['eval']}", headers=admin_csrf).status_code == 409
    assert db.scalar(select(func.count()).select_from(EvalReport)) >= 1


def test_a_folder_outside_the_runs_root_is_never_moved(sign_in, research, db, tmp_path):
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    (outside / "keep.txt").write_text("x")
    research.folder = str(outside)
    db.commit()
    admin, csrf = sign_in("admin")
    r = admin.delete(f"/api/v1/runs/{research.id}", headers=csrf)
    assert r.status_code == 200 and r.json()["folder"] == "outside"
    assert (outside / "keep.txt").exists()


def test_bulk_delete_reports_each_run(sign_in, research, db):
    member, csrf = sign_in("member")
    queued = start(member, csrf, research.field_id)
    missing = uuid.uuid4()
    r = member.post(
        "/api/v1/runs/delete", json={"ids": [str(research.id), str(queued), str(missing)]}, headers=csrf
    )
    assert r.status_code == 200
    body = r.json()
    assert body["deleted"] == [str(research.id)]
    assert {x["id"]: x["code"] for x in body["refused"]} == {
        str(queued): "run_active",
        str(missing): "not_found",
    }
