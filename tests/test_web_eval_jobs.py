"""Worker `eval_run` and `gold_build` jobs. research-eval runs in-process in demo mode; HTTP is mocked."""

import json

from eval_helpers import europepmc, panel_gold, row
from eval_job_helpers import forbid_models, in_process, review_dict

from research_agent.eval.gold import write_gold
from research_agent.web.db.models import EvalReport, GoldSet, Job, User
from research_agent.web.jobs import enqueue
from research_agent.web.worker import Worker


def member_id(db):
    from sqlalchemy import select

    return db.scalar(select(User.id).where(User.email == "member@example.org"))


def run_job(settings, factory, kind, payload, calls=None, http_client=None):
    with factory() as db:
        job, _ = enqueue(db, kind, payload, member_id(db))
        db.commit()
        job_id = job.id
    worker = Worker(
        settings, factory, sleep=lambda s: None, spawn_eval=in_process(calls), http_client=http_client
    )
    assert worker.tick() is True
    with factory() as db:
        return db.get(Job, job_id)


def panel_payload(settings, folder="panel-1"):
    gold = write_gold(panel_gold(), settings.gold_dir / "panel-toy.json")
    assert gold.candidates
    return {
        "kind": "panel",
        "folder": folder,
        "mode": "demo",
        "gold_path": str(settings.gold_dir / "panel-toy.json"),
        "review": review_dict(),
        "sample": 4,
        "seed": 1,
    }


def test_a_panel_job_runs_panel_then_report_and_imports_a_report(world, monkeypatch):
    settings, factory, _ = world
    forbid_models(monkeypatch)
    calls = []
    job = run_job(settings, factory, "eval_run", panel_payload(settings), calls)
    assert job.status == "done", job.error
    assert [argv[0] for argv in calls] == ["panel", "report"]
    assert job.progress["steps"] == ["panel", "report"] and job.progress["done"] == 2
    result = job.progress["result"]
    assert result["folder"] == "panel-1"
    with factory() as db:
        report = db.get(EvalReport, result["eval_id"])
        assert report.kind == "panel" and report.metrics["panel"]["n"] == 4
        assert report.created_by == member_id(db)
        panel_id = report.id

    abl = {
        "kind": "ablation",
        "folder": "abl-1",
        "mode": "demo",
        "panel_dir": str(settings.evals_dir / "panel-1"),
    }
    job = run_job(settings, factory, "eval_run", abl | {"parent_id": str(panel_id), "rerun_editor": True})
    assert job.status == "done", job.error
    with factory() as db:
        report = db.get(EvalReport, job.progress["result"]["eval_id"])
        assert report.kind == "ablation" and report.parent_id == panel_id
        assert report.metrics["ablation"]["rerun_editor"] is True


def test_a_failing_step_fails_the_job_with_a_redacted_message(world, monkeypatch):
    settings, factory, _ = world
    sentinel = "AIza-SENTINEL-evaljob-1234567890"
    monkeypatch.setenv("GOOGLE_API_KEY", sentinel)
    payload = panel_payload(settings, "panel-bad")
    payload["review"]["panel"][0]["items"] = []  # research-eval refuses the review.json
    job = run_job(settings, factory, "eval_run", payload)
    assert job.status == "failed" and job.error.startswith("step 'panel' failed: ")
    assert sentinel not in job.error


def test_paths_outside_the_roots_are_refused(world):
    settings, factory, _ = world
    payload = panel_payload(settings, "panel-out") | {"gold_path": "/etc/hosts"}
    job = run_job(settings, factory, "eval_run", payload)
    assert job.status == "failed" and "outside the configured directories" in job.error
    escape = run_job(settings, factory, "eval_run", panel_payload(settings) | {"folder": "../x"})
    assert escape.status == "failed"


SPEC = {
    "name": "toy-sr",
    "citation": "Test et al. 2026",
    "topic": "deep learning CT-FFR",
    "query": "ctffr",
    "included": [{"doi": "10.1000/p1"}, {"doi": "10.1000/p2"}, {"doi": "10.1000/missing"}],
}


def test_a_gold_build_job_freezes_a_gold_file_and_a_gold_set(world):
    settings, factory, _ = world
    client = europepmc({"*": [row(i) for i in range(1, 7)]})
    job = run_job(settings, factory, "gold_build", {"spec": SPEC, "max_candidates": 50}, http_client=client)
    assert job.status == "done", job.error
    result = job.progress["result"]
    assert result["positives"] == 2 and result["candidates"] == 6 and result["unresolved"] == 1
    path = settings.gold_dir / "toy-sr.json"
    assert json.loads(path.read_text())["name"] == "toy-sr"
    with factory() as db:
        gold = db.get(GoldSet, result["gold_set_id"])
        assert gold.path == str(path) and gold.positives == 2 and gold.source["name"] == "toy-sr"
    again = run_job(settings, factory, "gold_build", {"spec": SPEC}, http_client=client)
    assert again.status == "failed" and "already exists" in again.error
