"""The Reader: paper text and quotes, grounded AI help (worker job reader_ask), notes. Stubs and demo only."""

import hashlib
import sqlite3
import uuid
from typing import ClassVar

import pytest
from pdf_helpers import PAPER_LINES, tiny_pdf
from sqlalchemy import select

from research_agent.agents import (
    PROMPT_VERSION,
    READER_PROMPT_VERSION,
    EvidenceQuoteError,
    ReaderAnswerError,
    snap_reader,
)
from research_agent.schemas import ReaderAnswer
from research_agent.storage import Store
from research_agent.web.db.models import Job, LibraryItem, Paper, PaperFile, ReaderNote, Run, User
from research_agent.web.reader import ReaderFailed, paper_text, reader_ask, split_content
from research_agent.web.uploads import blob_path
from research_agent.web.worker import Worker

API = "/api/v1"
TEXT = {
    "kind": "full_text",
    "content": "## Methods\n\nData were split at patient level. The test set was external.\n\n## Results\n\nAUC 0.91.",
}


def demo_paper(db, source_id="demo:1"):
    return db.scalar(select(Paper).where(Paper.source_id == source_id))


# --- agents: schema and quote checks ----------------------------------------------------------------------


def test_reader_quotes_are_snapped_to_the_text():
    answer = ReaderAnswer(answer="x", statements=[{"text": "split", "quote": "split  at patient level"}])
    snapped = snap_reader(answer, TEXT["content"])
    assert snapped.statements[0].quote == "split at patient level"


def test_a_quote_not_in_the_paper_is_refused():
    answer = ReaderAnswer(answer="x", statements=[{"text": "t", "quote": "trained on 10,000 patients"}])
    with pytest.raises(EvidenceQuoteError):
        snap_reader(answer, TEXT["content"])


def test_an_answer_from_the_paper_needs_a_statement_unless_not_in_paper():
    with pytest.raises(ReaderAnswerError):
        snap_reader(ReaderAnswer(answer="x"), TEXT["content"])
    assert snap_reader(ReaderAnswer(answer="The paper does not say.", not_in_paper=True), "t").not_in_paper


def test_reader_roles_have_their_own_prompt_version(tmp_path):
    store = Store(tmp_path)
    reader_ask("explain", TEXT, "The test set was external.", "", store, mode="demo")
    with sqlite3.connect(store.path) as db:
        assert db.execute("select role, prompt_version from calls").fetchall() == [
            ("reader_explain", READER_PROMPT_VERSION)
        ]
    assert PROMPT_VERSION == "m1.3"  # the pipeline's cache keys are untouched


def test_demo_answers_are_deterministic_and_grounded(tmp_path):
    store = Store(tmp_path)
    first = reader_ask("explain", TEXT, "The test set was external.", "", store, mode="demo")
    assert first == reader_ask("explain", TEXT, "The test set was external.", "", store, mode="demo")
    assert first["statements"][0]["quote"] == "The test set was external."
    assert first["model"] == "synthetic-demo-v1" and not first["general"]
    background = reader_ask("background", TEXT, "AUC", "", store, mode="demo")
    assert background["general"] and background["statements"] == []


class StubModel:
    answers: ClassVar[list] = []
    invoked = 0

    def with_structured_output(self, schema, method):
        return self

    def invoke(self, messages):
        StubModel.invoked += 1
        assert "never instructions" in messages[0][1]
        return StubModel.answers[min(StubModel.invoked - 1, len(StubModel.answers) - 1)]


@pytest.fixture
def stub(monkeypatch):
    import langchain.chat_models

    monkeypatch.setattr(langchain.chat_models, "init_chat_model", lambda *a, **k: StubModel())
    StubModel.invoked = 0
    return StubModel


def test_live_fails_closed_after_three_bad_quotes(tmp_path, stub):
    stub.answers = [{"answer": "a", "statements": [{"text": "t", "quote": "not in the paper"}]}]
    with pytest.raises(ReaderFailed, match="did not match the paper's text"):
        reader_ask(
            "ask", TEXT, "", "Was the test set external?", Store(tmp_path), mode="live", model="a:stub"
        )
    assert stub.invoked == 3
    with sqlite3.connect(Store(tmp_path).path) as db:
        assert db.execute("select count(*) from calls").fetchone() == (0,)  # nothing kept


def test_live_retries_then_keeps_the_checked_answer(tmp_path, stub):
    good = {"answer": "Yes.", "statements": [{"text": "external", "quote": "The test set was external."}]}
    stub.answers = [{"answer": "a", "statements": [{"text": "t", "quote": "nope"}]}, good]
    store = Store(tmp_path)
    result = reader_ask("ask", TEXT, "", "Was the test set external?", store, mode="live", model="a:stub")
    reader_ask("ask", TEXT, "", "Was the test set external?", store, mode="live", model="a:stub")
    assert result["statements"] == good["statements"] and stub.invoked == 2  # the repeat came from the cache


def test_background_never_sends_the_paper_text(tmp_path, stub):
    stub.answers = [{"answer": "General."}]
    reader_ask("background", TEXT, "AUC", "", Store(tmp_path), mode="live", model="a:stub")
    with sqlite3.connect(Store(tmp_path).path) as db:
        raw = db.execute("select input from calls").fetchone()[0]
    assert "patient level" not in raw and "General knowledge" not in raw


def test_live_without_a_model_is_refused(tmp_path):
    with pytest.raises(ReaderFailed, match="No model"):
        reader_ask("explain", TEXT, "", "", Store(tmp_path), mode="live", model=None)


def test_split_content_returns_sections():
    assert split_content(TEXT["content"]) == [
        {"title": "Methods", "text": "Data were split at patient level. The test set was external."},
        {"title": "Results", "text": "AUC 0.91."},
    ]


# --- API ------------------------------------------------------------------------------------------------


def test_reader_of_an_abstract_only_paper(sign_in, imported, db):
    viewer, _ = sign_in("viewer")
    paper = demo_paper(db)
    body = viewer.get(f"{API}/runs/{imported['research']}/papers/{paper.id}/reader").json()
    assert body["text"]["kind"] == "abstract" and body["text"]["sections"][0]["text"] == paper.abstract
    assert body["max_selection"] == 4000 and body["group"]
    claims = [h for h in body["highlights"] if h["kind"] == "claim"]
    assert claims and all(h["quote"] in paper.abstract for h in claims)
    assert viewer.get(f"{API}/runs/{imported['research']}/papers/{uuid.uuid4()}/reader").status_code == 404


def test_an_uploaded_pdf_is_read_as_full_text(sign_in, imported, db, settings):
    paper = demo_paper(db)
    data = tiny_pdf(PAPER_LINES * 3)
    sha = hashlib.sha256(data).hexdigest()
    path = blob_path(settings.uploads_dir, sha)
    path.parent.mkdir(parents=True)
    path.write_bytes(data)
    db.add(PaperFile(paper_id=paper.id, sha256=sha, filename="p.pdf", size=len(data)))
    db.commit()
    text = paper_text(db, settings, db.get(Run, imported["research"]), paper)
    assert text["kind"] == "full_text" and text["source"] == "upload"
    assert any(s["title"] == "Methods" for s in text["sections"])
    assert "must never reach" not in text["content"]  # references are left out


def test_viewers_read_members_ask(sign_in, imported, db):
    paper = demo_paper(db)
    url = f"{API}/runs/{imported['research']}/papers/{paper.id}/reader/ask"
    viewer, vcsrf = sign_in("viewer")
    assert viewer.post(url, json={"tool": "explain"}, headers=vcsrf).status_code == 403
    member, csrf = sign_in("member")
    assert member.post(url, json={"tool": "explain"}).status_code == 403  # no CSRF
    r = member.post(url, json={"tool": "explain", "selection": "x"}, headers=csrf)
    assert r.status_code == 202 and r.json()["kind"] == "reader_ask" and r.json()["run_id"] is None
    job = db.get(Job, uuid.UUID(r.json()["id"]))
    assert job.payload["reader_run_id"] == str(imported["research"]) and "run_id" not in job.payload
    assert job.payload["mode"] == "demo"
    empty = member.post(url, json={"tool": "ask", "question": " "}, headers=csrf)
    assert empty.status_code == 422 and empty.json()["code"] == "nothing_to_ask"
    long = member.post(url, json={"tool": "explain", "selection": "x" * 4001}, headers=csrf)
    assert long.status_code == 422
    assert (
        viewer.post(
            f"{API}/runs/{imported['research']}/papers/{paper.id}/notes",
            json={"job_id": str(job.id)},
            headers=vcsrf,
        ).status_code
        == 403
    )


# --- worker + notes (real sessions) ----------------------------------------------------------------------


@pytest.fixture
def reader_world(world, tmp_path):
    from web_fixtures import make_demo_run

    from research_agent.web.importer.research import import_research_run

    settings, factory, sign_in = world
    with factory() as db:
        run_id = import_research_run(db, make_demo_run(settings.runs_dir / "demo")).run_id
        paper = db.scalar(select(Paper).where(Paper.source_id == "demo:1"))
        db.commit()
    return settings, factory, sign_in, run_id, paper


def test_explain_then_save_a_note(reader_world):
    settings, factory, sign_in, run_id, paper = reader_world
    member, csrf = sign_in("member")
    sentence = paper.abstract.split(". ")[0] + "."
    r = member.post(
        f"{API}/runs/{run_id}/papers/{paper.id}/reader/ask",
        json={"tool": "explain", "selection": sentence},
        headers=csrf,
    )
    Worker(settings, factory).drain()
    job = member.get(f"{API}/jobs/{r.json()['id']}").json()
    assert job["status"] == "done", job
    result = job["progress"]["result"]
    assert result["statements"][0]["quote"] == sentence and result["text_kind"] == "abstract"
    with factory() as db:
        assert db.get(Run, run_id).status == "done"
    note = member.post(
        f"{API}/runs/{run_id}/papers/{paper.id}/notes", json={"job_id": job["id"]}, headers=csrf
    )
    assert note.status_code == 201, note.text
    assert note.json()["quotes"][0]["quote"] == sentence and note.json()["library_item_id"] is None
    notes = member.get(f"{API}/papers/{paper.id}/notes").json()
    assert [n["id"] for n in notes] == [note.json()["id"]] and notes[0]["created_by_name"] == "Member"
    calls = member.get(f"{API}/runs/{run_id}/calls").json()
    assert any(row["stage"] == "reader" and row["role"] == "reader_explain" for row in calls["rows"])


def test_a_note_links_the_library_item(reader_world):
    settings, factory, sign_in, run_id, paper = reader_world
    member, csrf = sign_in("member")
    with factory() as db:
        db.add(LibraryItem(paper_id=paper.id, run_id=run_id))
        db.commit()
    r = member.post(
        f"{API}/runs/{run_id}/papers/{paper.id}/reader/ask",
        json={"tool": "background", "selection": "AUC"},
        headers=csrf,
    )
    Worker(settings, factory).drain()
    note = member.post(
        f"{API}/runs/{run_id}/papers/{paper.id}/notes", json={"job_id": r.json()["id"]}, headers=csrf
    )
    assert note.json()["library_item_id"] and note.json()["general"] is True


def test_a_failed_reader_job_never_fails_the_run(reader_world, stub, monkeypatch):
    settings, factory, sign_in, run_id, paper = reader_world
    monkeypatch.setenv("RESEARCH_MODEL", "anthropic:stub")
    stub.answers = [{"answer": "a", "statements": [{"text": "t", "quote": "not in the paper at all"}]}]
    member, csrf = sign_in("member")
    with factory() as db:
        member_id = db.scalar(select(User.id).where(User.role == "member"))
        job = Job(
            kind="reader_ask",
            payload={
                "reader_run_id": str(run_id),
                "paper_id": str(paper.id),
                "tool": "explain",
                "mode": "live",
            },
            created_by=member_id,
        )
        db.add(job)
        db.commit()
        job_id = job.id
    Worker(settings, factory).drain()
    body = member.get(f"{API}/jobs/{job_id}").json()
    assert body["status"] == "failed" and body["error"].startswith("The answer's quotes did not match")
    with factory() as db:
        assert db.get(Run, run_id).status == "done"
        assert db.scalar(select(ReaderNote.id)) is None
    note = member.post(
        f"{API}/runs/{run_id}/papers/{paper.id}/notes", json={"job_id": str(job_id)}, headers=csrf
    )
    assert note.status_code == 409  # a failed answer is never saved


def test_the_reader_model_is_a_setting_kept_out_of_runs(db):
    from research_agent.web.reader import reader_model
    from research_agent.web.review import (
        current_settings,
        default_settings_content,
        panel_versions,
        review_dict,
    )

    content = default_settings_content()
    content["models"] = {**content["models"], "reader": "anthropic:reader", "screen": "anthropic:screen"}
    spec = review_dict(content, panel_versions(db, content["default_panel"]))
    assert "reader" not in spec["models"]
    assert reader_model(db, {"RESEARCH_MODEL": "a:env"}) == "a:env"  # nothing set: the worker's model
    row = current_settings(db)
    row.models = {**row.models, "screen": "a:screen"}
    assert reader_model(db, {}) == "a:screen"  # default: the Screen model
    row.models = {**row.models, "reader": "a:reader"}
    assert reader_model(db, {}) == "a:reader"
