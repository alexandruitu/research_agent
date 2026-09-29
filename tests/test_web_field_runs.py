"""Field runs: domain.json built at start, refusals, the worker's --domain request, resume, and import."""

import json
import uuid
from pathlib import Path

import pytest
import sqlalchemy as sa

from research_agent.runner import run_research
from research_agent.schemas import Contract, read_domain
from research_agent.web.db.models import Job, Run, SourceRow
from research_agent.web.runner import RunSpec, build_command
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


def criterion_rows(db, run_id):
    from research_agent.web.db.models import Criterion, CriterionScore, Screening

    return sorted(
        db.execute(
            sa.select(
                Screening.sources,
                Criterion.key,
                Criterion.kind,
                CriterionScore.probability,
                CriterionScore.llm_answer,
                CriterionScore.quote,
            )
            .join(CriterionScore, CriterionScore.screening_id == Screening.id)
            .join(Criterion, Criterion.id == CriterionScore.criterion_id)
            .where(Screening.run_id == run_id)
        ).all()
    )


def test_a_field_run_goes_through_the_worker_and_imports_linked_to_its_version(world):
    settings, factory, sign_in = world
    field_id = new_field(sign_in)
    r = start(sign_in, field_id)
    run_id = uuid.UUID(r.json()["run_id"])
    Worker(settings, factory, spawn=pipeline_spawn, sleep=lambda s: None).tick()
    with factory() as db:
        from research_agent.web.db.models import FieldVersion, Screening

        run = db.get(Run, run_id)
        assert run.status == "done", run.error
        version = db.get(FieldVersion, run.field_version_id)
        assert (str(version.field_id), version.version, version.note) == (field_id, 1, "")
        assert (Path(run.folder) / "domain.json").read_bytes() == (
            Path(run.folder) / DOMAIN_REQUEST
        ).read_bytes()
        screenings = db.scalars(sa.select(Screening).where(Screening.run_id == run_id)).all()
        assert len(screenings) == 3 and all(s.sources == ["europepmc"] for s in screenings)
        assert all(s.call_key for s in screenings)  # the screen_criteria calls are found
        rows = criterion_rows(db, run_id)
        assert {(key, kind, p, llm) for _, key, kind, p, llm, _ in rows} == {
            ("e1", "exclude", None, "no"),
            ("i1", "include", None, "yes"),
        }
    member, _ = sign_in("member")
    body = member.get(f"{API}/fields/{field_id}").json()
    assert body["current"]["run_count"] == 1 and body["last_run"]["field_version"] == 1


def test_an_unknown_snapshot_becomes_an_imported_version_and_is_reused(world, tmp_path):
    from research_agent.schemas import DomainSpec
    from research_agent.web.db.models import Field, FieldVersion
    from research_agent.web.importer.research import import_research_run

    settings, factory, _sign_in = world
    domain = DomainSpec.model_validate(
        {
            "schema": 1,
            "field": {"id": str(uuid.uuid4()), "name": "Imported field", "version": 7},
            "topic": "retrieval augmented generation",
            "criteria": {"include": [{"key": "i1", "text": "Uses retrieval."}]},
            "sources": [{"name": "arxiv"}],
        }
    )
    folders = []
    for name in ("a", "b"):
        folder = settings.runs_dir / name
        run_research(folder, contract=Contract(topic=domain.topic, domain=domain, mode="demo", max_papers=2))
        folders.append(folder)
    with factory() as db:
        first = import_research_run(db, folders[0])
        assert import_research_run(db, folders[0]).status == "unchanged"
        second = import_research_run(db, folders[1])
        db.commit()
        a, b = db.get(Run, first.run_id), db.get(Run, second.run_id)
        assert a.field_version_id == b.field_version_id  # same content: one version
        version = db.get(FieldVersion, a.field_version_id)
        field = db.get(Field, version.field_id)
        assert (version.note, version.version, field.name, field.current_version) == (
            "imported",
            1,
            "Imported field",
            1,
        )
        assert version.sources == {"names": ["arxiv"], "years": {"from": None, "to": None}}
        rows = criterion_rows(db, a.id)
        assert rows and all(sources == ["arxiv"] for sources, *_ in rows)


def test_old_legacy_reports_get_topic_match_as_the_decider_of_a_drop(world, tmp_path):
    from web_fixtures import make_demo_run

    from research_agent.web.db.models import Paper, Screening
    from research_agent.web.importer.research import import_research_run

    settings, factory, _ = world
    folder = make_demo_run(settings.runs_dir / "old")
    path = folder / "report.json"
    data = json.loads(path.read_text())
    for screen in data["state"]["screens"].values():  # as written before slice 2
        screen.pop("decided_by", None)
        screen.pop("criteria", None)
    first = next(iter(data["state"]["screens"]))
    data["state"]["screens"][first]["decision"] = "exclude"
    path.write_text(json.dumps(data))
    with factory() as db:
        run_id = import_research_run(db, folder).run_id
        rows = db.execute(
            sa.select(Paper.source_id, Screening.decided_by, Screening.sources)
            .join(Paper, Paper.id == Screening.paper_id)
            .where(Screening.run_id == run_id)
        ).all()
    decided = {pid: by for pid, by, _ in rows}
    assert decided.pop(first) == "topic_match" and set(decided.values()) == {None}
    assert {tuple(s) for _, _, s in rows} == {("demo",)}


@pytest.fixture
def screened(world):
    """An imported demo field run whose report was edited: demo:1 dropped by Jev on e1, demo:2 dropped by
    the LLM on i1 with a quote, demo:3 also found on arXiv."""
    from research_agent.schemas import DomainSpec
    from research_agent.web.importer.research import import_research_run

    settings, factory, sign_in = world
    domain = DomainSpec.model_validate(
        {
            "schema": 1,
            "topic": "retrieval augmented generation",
            "criteria": {
                "include": [{"key": "i1", "text": "Uses retrieval."}],
                "exclude": [{"key": "e1", "text": "Is a review."}],
            },
            "sources": [{"name": "europepmc"}, {"name": "arxiv"}],
        }
    )
    folder = settings.runs_dir / "field"
    run_research(folder, contract=Contract(topic=domain.topic, domain=domain, mode="demo", max_papers=4))
    path = folder / "report.json"
    data = json.loads(path.read_text())
    state = data["state"]
    papers = {p["id"]: p for p in state["papers"]}
    for pid, paper in papers.items():
        paper["sources"] = ["arxiv", "europepmc"] if pid == "demo:3" else ["europepmc"]
    for pid in ("demo:1", "demo:2"):
        state["evidence"].pop(pid, None)
    quote = papers["demo:2"]["abstract"][:30]
    state["screens"]["demo:1"] = {
        "decision": "exclude",
        "reason": "Jev: e1",
        "tier": "jev",
        "decided_by": "e1",
        "criteria": {
            "i1": {"jev_p": 0.9, "llm": None, "quote": None},
            "e1": {"jev_p": 0.97, "llm": None, "quote": None},
        },
        "jev": {
            "decision": "exclude",
            "decided_by": "e1",
            "probabilities": {"i1": 0.9, "e1": 0.97},
            "model_version": "jev-1.13.0",
            "thresholds": {},
            "cached": False,
        },
    }
    state["screens"]["demo:2"] = {
        "decision": "exclude",
        "reason": "LLM: i1 no",
        "tier": "llm",
        "decided_by": "i1",
        "criteria": {
            "i1": {"jev_p": 0.5, "llm": "no", "quote": quote},
            "e1": {"jev_p": 0.1, "llm": "no", "quote": None},
        },
        "jev": {
            "decision": "escalate",
            "decided_by": None,
            "probabilities": {"i1": 0.5, "e1": 0.1},
            "model_version": "jev-1.13.0",
            "thresholds": {},
            "cached": False,
        },
    }
    path.write_text(json.dumps(data))
    with factory() as db:
        run_id = import_research_run(db, folder).run_id
        db.commit()
    member, _ = sign_in("member")
    return member, run_id, quote


def paper_rows(viewer, run_id, **params):
    r = viewer.get(f"{API}/runs/{run_id}/papers", params=params)
    assert r.status_code == 200, r.text
    return {row["paper"]["source_id"]: row for row in r.json()["items"]}


def test_rows_carry_sources_and_per_criterion_cells(screened):
    viewer, run_id, quote = screened
    rows = paper_rows(viewer, run_id)
    assert rows["demo:3"]["sources"] == ["arxiv", "europepmc"] and rows["demo:4"]["sources"] == ["europepmc"]
    assert rows["demo:1"]["screen"]["decided_by"] == "e1"
    assert rows["demo:1"]["screen"]["criteria"] == {"i1": 0.9, "e1": 0.97}
    assert rows["demo:2"]["screen"]["cells"] == {
        "i1": {"kind": "include", "jev_p": 0.5, "llm": "no", "quote": quote},
        "e1": {"kind": "exclude", "jev_p": 0.1, "llm": "no", "quote": None},
    }
    assert (
        rows["demo:4"]["screen"]["criteria"] == {} and rows["demo:4"]["screen"]["cells"]["i1"]["llm"] == "yes"
    )


def test_decided_by_and_source_filters(screened):
    viewer, run_id, _ = screened
    assert set(paper_rows(viewer, run_id, decided_by="e1")) == {"demo:1"}
    assert set(paper_rows(viewer, run_id, decided_by="i1")) == {"demo:2"}
    assert paper_rows(viewer, run_id, decided_by="e2") == {}
    assert set(paper_rows(viewer, run_id, source="arxiv")) == {"demo:3"}
    assert len(paper_rows(viewer, run_id, source="europepmc")) == 4
    assert viewer.get(f"{API}/runs/{run_id}/papers", params={"source": "pubmed"}).status_code == 422
    assert viewer.get(f"{API}/runs/{run_id}/papers", params={"decided_by": "E1;--"}).status_code == 422
    assert set(paper_rows(viewer, run_id, sort="criterion:i1", direction="desc")) == {
        f"demo:{i}" for i in range(1, 5)
    }


def test_the_drawer_has_a_per_criterion_table(screened):
    viewer, run_id, quote = screened
    rows = paper_rows(viewer, run_id)
    drawer = viewer.get(f"{API}/runs/{run_id}/papers/{rows['demo:2']['paper']['id']}").json()
    screening = drawer["screening"]
    assert screening["decided_by"] == "i1" and drawer["sources"] == ["europepmc"]
    assert screening["criteria_table"] == [
        {
            "key": "i1",
            "kind": "include",
            "text": "Uses retrieval.",
            "jev_p": 0.5,
            "llm": "no",
            "quote": quote,
            "decided": True,
        },
        {
            "key": "e1",
            "kind": "exclude",
            "text": "Is a review.",
            "jev_p": 0.1,
            "llm": "no",
            "quote": None,
            "decided": False,
        },
    ]
    assert [c["key"] for c in screening["criteria"]] == ["i1", "e1"]  # Jev probabilities, as before
    kept = viewer.get(f"{API}/runs/{run_id}/papers/{rows['demo:4']['paper']['id']}").json()["screening"]
    assert kept["criteria"] == [] and [c["llm"] for c in kept["criteria_table"]] == ["yes", "no"]
