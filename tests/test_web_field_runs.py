"""Field runs: domain.json built at start, refusals, the worker's --domain request, resume, and import."""

import json
import uuid
from pathlib import Path

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from research_agent.runner import run_research
from research_agent.schemas import Contract, read_domain
from research_agent.web.api.app import create_app
from research_agent.web.auth import create_user
from research_agent.web.db.models import Job, Run, SourceRow
from research_agent.web.runner import RunSpec, build_command
from research_agent.web.settings import load_settings
from research_agent.web.worker import DOMAIN_REQUEST, Worker

API = "/api/v1"
PASSWORD = "correct horse battery"
DRAFT = {
    "name": "ML CT-FFR",
    "topic": "machine learning estimation of CT-derived fractional flow reserve",
    "include": [{"text": "The study uses machine learning."}],
    "exclude": [{"text": "The paper is a review without original results."}],
    "sources": ["europepmc", "openalex"],
    "years": {"from": 2018, "to": None},
}


class Done:
    """A finished child process."""

    returncode = 0

    def poll(self):
        return 0


@pytest.fixture
def world(fresh_db_url, tmp_path):
    settings = load_settings(
        {
            "RESEARCH_WEB_DATABASE_URL": fresh_db_url,
            "RESEARCH_RUNS_DIR": str(tmp_path / "runs"),
            "RESEARCH_EVALS_DIR": str(tmp_path / "evals"),
            "RESEARCH_GOLD_DIR": str(tmp_path / "gold"),
            "RESEARCH_WEB_COOKIE_SECURE": "false",
            "RESEARCH_WEB_ALLOW_DEMO": "true",
            "RESEARCH_WEB_WORKER_POLL_SECONDS": "0.01",
            "RESEARCH_WEB_PROGRESS_POLL_SECONDS": "0.01",
        }
    )
    engine = sa.create_engine(fresh_db_url)
    factory = sessionmaker(engine, expire_on_commit=False)
    with factory() as db:
        for role in ("member", "admin"):
            create_user(db, email=f"{role}@example.org", name=role.title(), role=role, password=PASSWORD)
        db.commit()
    app = create_app(settings, session_factory=factory)

    def sign_in(role):
        client = TestClient(app)
        r = client.post(f"{API}/auth/login", json={"email": f"{role}@example.org", "password": PASSWORD})
        return client, {"X-CSRF-Token": r.json()["csrf_token"]}

    yield settings, factory, sign_in
    engine.dispose()


def new_field(sign_in, **overrides):
    member, csrf = sign_in("member")
    r = member.post(f"{API}/fields", json={**DRAFT, **overrides}, headers=csrf)
    assert r.status_code == 201, r.text
    return r.json()["id"]


def start(sign_in, field_id, role="member", **overrides):
    client, csrf = sign_in(role)
    body = {"field_id": field_id, "max_papers": 3, "mode": "demo", **overrides}
    return client.post(f"{API}/runs", json=body, headers=csrf)


def test_start_builds_domain_json_from_the_current_version_and_enabled_sources(world):
    _settings, factory, sign_in = world
    field_id = new_field(sign_in)
    r = start(sign_in, field_id)
    assert r.status_code == 202, r.text
    with factory() as db:
        run = db.get(Run, uuid.UUID(r.json()["run_id"]))
        job = db.get(Job, uuid.UUID(r.json()["job"]["id"]))
        domain = run.manifest["domain_request"]
        assert job.payload["domain"] == domain and run.field_version_id is not None
    assert domain["field"] == {"id": field_id, "name": "ML CT-FFR", "version": 1}
    assert domain["sources"] == [
        {"name": "europepmc", "max_results": 100, "contact": None}
    ]  # OpenAlex is disabled
    assert domain["criteria"]["include"] == [{"key": "i1", "text": "The study uses machine learning."}]
    assert domain["years"] == {"from": 2018, "to": None} and domain["schema"] == 1
    assert domain["thresholds"]["keep_min"] == 0.8
    assert run.manifest["contract"] == {"topic": DRAFT["topic"], "max_papers": 3, "mode": "demo"}
    member, _ = sign_in("member")
    listed = {x["id"]: x for x in member.get(f"{API}/runs").json()}
    assert listed[r.json()["run_id"]]["field_version"] == 1

    admin, csrf = sign_in("admin")
    admin.patch(f"{API}/sources/openalex", json={"enabled": True, "max_results": 40}, headers=csrf)
    admin.patch(f"{API}/settings", json={"contact_email": "team@example.org"}, headers=csrf)
    r = start(sign_in, field_id, role="admin")
    with factory() as db:
        domain = db.get(Run, uuid.UUID(r.json()["run_id"])).manifest["domain_request"]
    assert domain["sources"] == [
        {"name": "europepmc", "max_results": 100, "contact": None},
        {"name": "openalex", "max_results": 40, "contact": "team@example.org"},
    ]


def test_archived_fields_and_fields_without_an_enabled_source_are_refused(world):
    _settings, factory, sign_in = world
    only_arxiv = new_field(sign_in, sources=["arxiv"])
    r = start(sign_in, only_arxiv)
    assert r.status_code == 422 and r.json()["code"] == "no_enabled_source"
    assert r.json()["message"] == "None of this field's sources is enabled"

    field_id = new_field(sign_in)
    admin, csrf = sign_in("admin")
    admin.post(f"{API}/fields/{field_id}/archive", headers=csrf)
    r = start(sign_in, field_id)
    assert r.status_code == 409 and r.json()["code"] == "archived"
    with factory() as db:
        assert db.scalar(sa.select(sa.func.count()).select_from(Run)) == 0


def test_a_legacy_field_needs_europe_pmc(world):
    _settings, factory, sign_in = world
    from research_agent.web.importer.common import get_or_create_field

    with factory() as db:
        field_id = str(get_or_create_field(db, "retrieval augmented generation").id)
        db.get(SourceRow, "europepmc").enabled = False
        db.commit()
    r = start(sign_in, field_id)
    assert r.status_code == 422 and r.json()["code"] == "no_enabled_source"
    with factory() as db:
        db.get(SourceRow, "europepmc").enabled = True
        db.commit()
    r = start(sign_in, field_id)
    assert r.status_code == 202
    with factory() as db:
        run = db.get(Run, uuid.UUID(r.json()["run_id"]))
        assert "domain_request" not in run.manifest and run.field_version_id is not None


def test_build_command_passes_the_domain_file_and_no_topic(tmp_path):
    spec = RunSpec("ignored", 3, "demo", False, False, tmp_path, domain_file=tmp_path / DOMAIN_REQUEST)
    command = build_command(spec)
    assert command[-2:] == ["--domain", str(tmp_path / DOMAIN_REQUEST)] and "--" not in command
    resume = RunSpec("", 3, "demo", False, True, tmp_path)
    assert build_command(resume)[-1] == "--resume"


def capture_spawn(captured):
    def spawn(spec, env, log):
        captured.append(spec)
        return Done()

    return spawn


def test_the_worker_writes_the_request_and_passes_domain(world, monkeypatch):
    settings, factory, sign_in = world
    r = start(sign_in, new_field(sign_in))
    captured = []
    monkeypatch.setattr("research_agent.web.worker.import_research_run", lambda *a, **k: None)
    Worker(settings, factory, spawn=capture_spawn(captured), sleep=lambda s: None).tick()
    [spec] = captured
    assert spec.resume is False and spec.domain_file == spec.run_dir / DOMAIN_REQUEST
    written = json.loads(spec.domain_file.read_text())
    with factory() as db:
        assert written == db.get(Run, uuid.UUID(r.json()["run_id"])).manifest["domain_request"]
    assert read_domain(spec.domain_file).topic == DRAFT["topic"]  # the pipeline accepts it


def fail_run(factory, run_id, with_manifest):
    with factory() as db:
        run = db.get(Run, run_id)
        run.status, run.error = "failed", "failed at stage 'discover': SourceUnavailable: openalex"
        for job in db.scalars(sa.select(Job)):
            job.status = "failed"
        db.commit()
        folder = Path(run.folder)
    folder.mkdir(parents=True, exist_ok=True)
    if with_manifest:
        (folder / "manifest.json").write_text("{}")


@pytest.mark.parametrize("with_manifest", [False, True])
def test_resume_of_a_field_run(world, with_manifest):
    settings, factory, sign_in = world
    run_id = uuid.UUID(start(sign_in, new_field(sign_in)).json()["run_id"])
    fail_run(factory, run_id, with_manifest)
    member, csrf = sign_in("member")
    r = member.post(f"{API}/runs/{run_id}/resume", headers=csrf)
    assert r.status_code == 202, r.text
    with factory() as db:
        job = db.get(Job, uuid.UUID(r.json()["job"]["id"]))
        assert job.payload["resume"] is True and job.payload["domain"]["topic"] == DRAFT["topic"]
    captured = []
    Worker(settings, factory, spawn=capture_spawn(captured), sleep=lambda s: None).tick()
    [spec] = captured
    if with_manifest:  # the pipeline resumes from its saved contract (which holds the domain)
        assert spec.resume is True and spec.domain_file is None
        assert build_command(spec)[-1] == "--resume"
    else:  # nothing saved yet: start again from the request
        assert spec.resume is False and spec.domain_file.name == DOMAIN_REQUEST


def pipeline_spawn(spec, env, log):
    """The real pipeline in demo mode, in-process (as the child would run it)."""
    domain = read_domain(spec.domain_file)
    contract = Contract(topic=domain.topic, domain=domain, mode=spec.mode, max_papers=spec.max_papers)
    run_research(spec.run_dir, contract=contract, domain_file=spec.domain_file)
    return Done()
