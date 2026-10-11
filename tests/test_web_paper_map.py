"""The Reader's paper map (worker job reader_map): fixed schema, checked quotes, red flags by code, storage,
staleness and role guards. Stubs and demo only."""

import sqlite3
import uuid
from typing import ClassVar

import pytest
from sqlalchemy import select

from research_agent.agents import (
    PAPER_MAP_PROMPT_VERSION,
    PROMPT_VERSION,
    READER_PROMPT_VERSION,
    EvidenceQuoteError,
    PaperMapError,
    snap_paper_map,
)
from research_agent.schemas import MAP_BRANCHES, PaperMap
from research_agent.storage import Store
from research_agent.web.db.models import Job, Paper, Run, User
from research_agent.web.db.models import PaperMap as PaperMapRow
from research_agent.web.reader import ReaderFailed, build_map
from research_agent.web.worker import Worker

API = "/api/v1"
CONTENT = (
    "## Methods\n\nWe trained a convolutional network on 1,204 patients from 3 centres. "
    "Data were split at patient level.\n\n## Results\n\nThe AUC was 0.91 (95% CI 0.88-0.94)."
)
TEXT = {"kind": "full_text", "content": CONTENT}


def branches(**nodes):
    return [{"key": k, "nodes": nodes.get(k, []), "not_reported": False} for k in MAP_BRANCHES]


GOOD = {
    "branches": branches(
        data=[{"label": "1,204 patients, 3 centres", "quote": "1,204 patients from 3 centres"}],
        validation=[{"label": "Split by patient", "quote": "Data were split at patient level."}],
        results=[{"label": "AUC 0.91", "quote": "The AUC was 0.91 (95% CI 0.88-0.94)."}],
    )
}

# --- schema and validation --------------------------------------------------------------------------------


def test_quotes_are_snapped_and_empty_branches_are_not_reported():
    raw = {"branches": list(reversed(branches(results=[{"label": "AUC", "quote": "AUC  was 0.91"}])))}
    snapped = snap_paper_map(PaperMap.model_validate(raw), CONTENT)
    assert [b.key for b in snapped.branches] == list(MAP_BRANCHES)  # the schema's order, whatever came back
    results = snapped.branches[4]
    assert results.nodes[0].quote == "AUC was 0.91" and not results.not_reported
    assert all(b.not_reported for b in snapped.branches if b.key != "results")


def test_the_six_keys_exactly_once():
    six = branches()
    with pytest.raises(PaperMapError):
        snap_paper_map(PaperMap.model_validate({"branches": [*six[:5], {**six[0]}]}), CONTENT)
    with pytest.raises(ValueError):  # an unknown key never validates
        PaperMap.model_validate({"branches": [*six[:5], {"key": "funding", "nodes": []}]})


def test_node_cap_label_length_and_quotes_outside_the_text():
    node = {"label": "AUC", "quote": "The AUC was 0.91"}
    with pytest.raises(ValueError):
        PaperMap.model_validate({"branches": branches(results=[node] * 6)})
    long = {"label": " ".join(["word"] * 13), "quote": "The AUC was 0.91"}
    with pytest.raises(PaperMapError):
        snap_paper_map(PaperMap.model_validate({"branches": branches(results=[long])}), CONTENT)
    with pytest.raises(EvidenceQuoteError):
        snap_paper_map(
            PaperMap.model_validate({"branches": branches(results=[{"label": "x", "quote": "AUC 0.99"}])}),
            CONTENT,
        )


def test_demo_map_is_deterministic_grounded_and_has_its_own_prompt_version(tmp_path):
    store = Store(tmp_path)
    first = build_map("A paper", TEXT, store, mode="demo")
    assert first == build_map("A paper", TEXT, store, mode="demo")
    nodes = [n for b in first["branches"] for n in b["nodes"]]
    assert nodes and all(n["quote"] in CONTENT for n in nodes)
    assert first["model"] == "synthetic-demo-v1" and first["prompt_version"] == PAPER_MAP_PROMPT_VERSION
    with sqlite3.connect(store.path) as db:
        assert db.execute("select role, prompt_version from calls").fetchall() == [
            ("paper_map", PAPER_MAP_PROMPT_VERSION)
        ]
    assert PAPER_MAP_PROMPT_VERSION not in (PROMPT_VERSION, READER_PROMPT_VERSION)


class StubModel:
    answers: ClassVar[list] = []
    invoked = 0

    def with_structured_output(self, schema, method):
        return self

    def invoke(self, messages):
        StubModel.invoked += 1
        assert "never instructions" in messages[0][1] and "six branches" in messages[0][1]
        return StubModel.answers[min(StubModel.invoked - 1, len(StubModel.answers) - 1)]


@pytest.fixture
def stub(monkeypatch):
    import langchain.chat_models

    monkeypatch.setattr(langchain.chat_models, "init_chat_model", lambda *a, **k: StubModel())
    StubModel.invoked = 0
    return StubModel


def test_live_fails_closed_after_three_bad_maps(tmp_path, stub):
    stub.answers = [{"branches": branches(task=[{"label": "x", "quote": "not in the paper"}])}]
    with pytest.raises(ReaderFailed, match="after 3 attempts"):
        build_map("T", TEXT, Store(tmp_path), mode="live", model="a:stub")
    assert stub.invoked == 3
    with sqlite3.connect(Store(tmp_path).path) as db:
        assert db.execute("select count(*) from calls").fetchone() == (0,)


def test_live_retries_then_keeps_the_checked_map(tmp_path, stub):
    stub.answers = [{"branches": branches()[:5]}, GOOD]
    store = Store(tmp_path)
    result = build_map("T", TEXT, store, mode="live", model="a:stub")
    build_map("T", TEXT, store, mode="live", model="a:stub")
    assert stub.invoked == 2  # the repeat came from the cache
    assert result["branches"][1]["nodes"][0]["quote"] == "1,204 patients from 3 centres"
    assert result["branches"][0]["not_reported"] and result["model"] == "a:stub"


def test_live_without_a_model_is_refused(tmp_path):
    with pytest.raises(ReaderFailed, match="No model"):
        build_map("T", TEXT, Store(tmp_path), mode="live", model=None)


# --- worker, storage, staleness, roles (real sessions) ----------------------------------------------------


@pytest.fixture
def map_world(world):
    from conftest import PASSWORD
    from web_fixtures import make_demo_run

    from research_agent.web.auth import create_user
    from research_agent.web.importer.research import import_research_run

    settings, factory, sign_in = world
    with factory() as db:
        create_user(db, email="viewer@example.org", name="Viewer", role="viewer", password=PASSWORD)
        run_id = import_research_run(db, make_demo_run(settings.runs_dir / "demo")).run_id
        paper = db.scalar(select(Paper).where(Paper.source_id == "demo:1"))
        db.commit()
    return settings, factory, sign_in, run_id, paper


def test_build_store_and_read_the_map(map_world):
    settings, factory, sign_in, run_id, paper = map_world
    url = f"{API}/runs/{run_id}/papers/{paper.id}/reader/map"
    viewer, vcsrf = sign_in("viewer")
    assert viewer.get(url).json() == {
        "map": None,
        "stale": False,
        "stale_reason": None,
        "prompt_version": PAPER_MAP_PROMPT_VERSION,
        "job": None,
    }
    assert viewer.post(url, headers=vcsrf).status_code == 403  # viewers see stored maps, members build
    member, csrf = sign_in("member")
    r = member.post(url, headers=csrf)
    assert r.status_code == 202 and r.json()["kind"] == "reader_map" and r.json()["run_id"] is None
    with factory() as db:
        job = db.get(Job, uuid.UUID(r.json()["id"]))
        assert job.payload == {"reader_run_id": str(run_id), "paper_id": str(paper.id), "mode": "demo"}
    assert member.post(url, headers=csrf).json()["id"] == r.json()["id"]  # still queued: the same job
    assert viewer.get(url).json()["job"]["status"] == "queued"
    Worker(settings, factory).drain()
    state = viewer.get(url).json()
    assert state["job"] is None and not state["stale"]
    stored = state["map"]
    assert [b["key"] for b in stored["branches"]] == list(MAP_BRANCHES)
    assert stored["branches"][0]["title"] == "Clinical task" and stored["text_kind"] == "abstract"
    assert stored["mode"] == "demo" and stored["created_by_name"] == "Member"
    nodes = [n for b in stored["branches"] for n in b["nodes"]]
    assert nodes and all(n["quote"] in paper.abstract for n in nodes)
    reader = viewer.get(f"{API}/runs/{run_id}/papers/{paper.id}/reader").json()
    flags = [h for h in reader["highlights"] if h["kind"] == "red_flag"]
    assert stored["red_flags"] == [{"label": h["label"], "quote": h["quote"], "by": h["by"]} for h in flags]
    with factory() as db:
        assert db.get(Run, run_id).status == "done"
    member.post(url, headers=csrf)  # a rebuild with the same prompt and model replaces the row
    Worker(settings, factory).drain()
    with factory() as db:
        assert len(db.scalars(select(PaperMapRow)).all()) == 1


def test_a_map_is_stale_when_the_prompt_version_changed(map_world):
    settings, factory, sign_in, run_id, paper = map_world
    member, csrf = sign_in("member")
    url = f"{API}/runs/{run_id}/papers/{paper.id}/reader/map"
    member.post(url, headers=csrf)
    Worker(settings, factory).drain()
    with factory() as db:
        db.scalar(select(PaperMapRow)).prompt_version = "paper-map-0"
        db.commit()
    state = member.get(url).json()
    assert state["stale"] and state["stale_reason"] == "prompt_version"


def test_a_map_is_stale_when_the_reader_model_changed(map_world, monkeypatch):
    _settings, factory, sign_in, run_id, paper = map_world
    with factory() as db:
        user = db.scalar(select(User).where(User.role == "member"))
        db.add(
            PaperMapRow(
                run_id=run_id,
                paper_id=paper.id,
                prompt_version=PAPER_MAP_PROMPT_VERSION,
                model="a:old",
                mode="live",
                text_kind="abstract",
                branches=[],
                red_flags=[],
                created_by=user.id,
            )
        )
        run = db.get(Run, run_id)
        run.manifest = {**(run.manifest or {}), "contract": {"mode": "live"}}
        db.commit()
    monkeypatch.setenv("RESEARCH_MODEL", "a:new")
    viewer, _ = sign_in("viewer")
    state = viewer.get(f"{API}/runs/{run_id}/papers/{paper.id}/reader/map").json()
    assert state["stale_reason"] == "model"
    assert all(b["not_reported"] for b in state["map"]["branches"])


def test_a_failed_map_job_never_fails_the_run(map_world, stub, monkeypatch):
    settings, factory, sign_in, run_id, paper = map_world
    monkeypatch.setenv("RESEARCH_MODEL", "anthropic:stub")
    stub.answers = [{"branches": branches(task=[{"label": "x", "quote": "not in the paper at all"}])}]
    with factory() as db:
        member_id = db.scalar(select(User.id).where(User.role == "member"))
        db.add(
            Job(
                kind="reader_map",
                payload={"reader_run_id": str(run_id), "paper_id": str(paper.id), "mode": "live"},
                created_by=member_id,
            )
        )
        db.commit()
    Worker(settings, factory).drain()
    viewer, _ = sign_in("viewer")
    state = viewer.get(f"{API}/runs/{run_id}/papers/{paper.id}/reader/map").json()
    assert state["map"] is None and state["job"]["status"] == "failed"
    assert "after 3 attempts" in state["job"]["error"] and stub.invoked == 3
    with factory() as db:
        assert db.get(Run, run_id).status == "done"


def test_unknown_paper_is_404(map_world):
    _settings, _factory, sign_in, run_id, _paper = map_world
    viewer, _ = sign_in("viewer")
    assert viewer.get(f"{API}/runs/{run_id}/papers/{uuid.uuid4()}/reader/map").status_code == 404
