"""Panel runs: review.json frozen at start, written by the worker with the uploads, imported, and shown."""

import json
import uuid

import sqlalchemy as sa

from research_agent.panel import DEFAULT_PANEL
from research_agent.schemas import Contract, ReviewSpec, read_review
from research_agent.web.db.models import Job, Paper, Run, RunReviewer
from research_agent.web.runner import RunSpec, build_command
from research_agent.web.worker import REVIEW_REQUEST, Worker

API = "/api/v1"
TOPIC = "retrieval augmented generation"
PDF = b"%PDF-1.4\n%%EOF\n"


class Done:
    returncode = 0

    def poll(self):
        return 0


def legacy_field(factory):
    from research_agent.web.importer.common import get_or_create_field

    with factory() as db:
        field_id = str(get_or_create_field(db, TOPIC).id)
        db.commit()
    return field_id


def start(sign_in, field_id, role="member"):
    client, csrf = sign_in(role)
    body = {"field_id": field_id, "max_papers": 3, "mode": "demo"}
    r = client.post(f"{API}/runs", json=body, headers=csrf)
    assert r.status_code == 202, r.text
    return r.json()


def capture_spawn(captured):
    def spawn(spec, env, log):
        captured.append(spec)
        return Done()

    return spawn


def test_start_freezes_the_current_settings_and_default_panel(world):
    _settings, factory, sign_in = world
    started = start(sign_in, legacy_field(factory))
    with factory() as db:
        run = db.get(Run, uuid.UUID(started["run_id"]))
        job = db.get(Job, uuid.UUID(started["job"]["id"]))
        review = run.manifest["review_request"]
        assert job.payload["review"] == review and run.settings_version_id is not None
        links = db.scalars(sa.select(RunReviewer).where(RunReviewer.run_id == run.id)).all()
        assert [link.position for link in links] == [0, 1, 2]
    spec = ReviewSpec.model_validate(review)  # the pipeline's own validation
    assert [(r.key, r.version) for r in spec.panel] == [(r["key"], 1) for r in DEFAULT_PANEL]
    assert review["fulltext"] == {"sources": ["pmc_oa", "upload"], "contact": None, "max_chars": 60000}
    assert review["screening"]["keep_min"] == 0.8 and review["schema"] == 1
    member, _ = sign_in("member")
    assert member.get(f"{API}/runs/{started['run_id']}").json()["settings_version"] == 1

    admin, csrf = sign_in("admin")
    reviewer = admin.get(f"{API}/reviewers/statistician").json()["current"]
    save = {k: reviewer[k] for k in ("name", "perspective", "model", "items")}
    save |= {"model": "openai:gpt-x", "base_version": 1, "note": "model"}
    assert admin.post(f"{API}/reviewers/statistician/versions", json=save, headers=csrf).status_code == 201
    settings = admin.get(f"{API}/settings/review").json()["current"]
    change = {k: settings[k] for k in ("models", "screening", "fulltext", "editor")}
    change |= {"default_panel": ["statistician"], "base_version": 1, "note": ""}
    assert admin.post(f"{API}/settings/review", json=change, headers=csrf).status_code == 201
    started = start(sign_in, legacy_field(factory))
    with factory() as db:
        review = db.get(Run, uuid.UUID(started["run_id"])).manifest["review_request"]
    assert [(r["key"], r["version"], r["model"]) for r in review["panel"]] == [
        ("statistician", 2, "openai:gpt-x")
    ]
    assert member.get(f"{API}/reviewers/statistician/versions/2").json()["run_count"] == 1
    assert member.get(f"{API}/settings/review").json()["current"]["run_count"] == 1


def test_the_worker_writes_review_json_and_the_uploads(world, monkeypatch):
    settings, factory, sign_in = world
    started = start(sign_in, legacy_field(factory))
    with factory() as db:
        paper = Paper(source_id="MED:7", title="t", abstract="a")
        db.add(paper)
        db.commit()
        paper_id = paper.id
    member, csrf = sign_in("member")
    r = member.post(f"{API}/papers/{paper_id}/files", files={"file": ("p.pdf", PDF)}, headers=csrf)
    assert r.status_code == 201, r.text
    captured = []
    monkeypatch.setattr("research_agent.web.worker.import_research_run", lambda *a, **k: None)
    Worker(settings, factory, spawn=capture_spawn(captured), sleep=lambda s: None).tick()
    [spec] = captured
    assert spec.resume is False and spec.review_file == spec.run_dir / REVIEW_REQUEST
    with factory() as db:
        request = db.get(Run, uuid.UUID(started["run_id"])).manifest["review_request"]
    assert json.loads(spec.review_file.read_text()) == request
    assert read_review(spec.review_file).panel[0].key == "methodologist"
    command = build_command(spec)
    assert command[command.index("--review") + 1] == str(spec.review_file)
    assert command[-2:] == ["--", TOPIC]
    assert (spec.run_dir / "uploads" / "MED_7.pdf").read_bytes() == PDF


def test_resume_carries_the_review_request(world):
    settings, factory, sign_in = world
    run_id = uuid.UUID(start(sign_in, legacy_field(factory))["run_id"])
    with factory() as db:
        run = db.get(Run, run_id)
        run.status = "failed"
        for job in db.scalars(sa.select(Job)):
            job.status = "failed"
        db.commit()
    member, csrf = sign_in("member")
    r = member.post(f"{API}/runs/{run_id}/resume", headers=csrf)
    with factory() as db:
        job = db.get(Job, uuid.UUID(r.json()["job"]["id"]))
        assert job.payload["review"] == db.get(Run, run_id).manifest["review_request"]
    captured = []
    Worker(settings, factory, spawn=capture_spawn(captured), sleep=lambda s: None).tick()
    assert captured[0].review_file.name == REVIEW_REQUEST  # no manifest yet: start again


def test_build_command_never_combines_review_with_resume(tmp_path):
    spec = RunSpec(
        topic=TOPIC,
        max_papers=3,
        mode="demo",
        jev=False,
        resume=True,
        run_dir=tmp_path,
        review_file=None,
    )
    assert "--review" not in build_command(spec)


def test_contract_accepts_the_web_review(world):
    _settings, factory, sign_in = world
    started = start(sign_in, legacy_field(factory))
    with factory() as db:
        review = db.get(Run, uuid.UUID(started["run_id"])).manifest["review_request"]
    Contract(topic=TOPIC, review=ReviewSpec.model_validate(review))
