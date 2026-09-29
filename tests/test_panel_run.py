import hashlib
import json
import sys

import pytest
from pdf_helpers import PAPER_LINES, tiny_pdf

from research_agent import cli
from research_agent.agents import Evaluator
from research_agent.connectors import DemoConnector
from research_agent.fulltext import FullText
from research_agent.graph import build_graph
from research_agent.panel import default_review
from research_agent.runner import run_research
from research_agent.schemas import Contract, ReviewSpec, read_review
from research_agent.storage import Store


def panel_contract(**changes):
    review = ReviewSpec.model_validate({**default_review(), **changes})
    return Contract(topic="retrieval augmented generation", max_papers=3, review=review)


def run_panel(tmp_path, contract):
    store = Store(tmp_path)
    fulltext = FullText(
        store, contract.review.fulltext.model_dump(), mode="demo", uploads=[tmp_path / "uploads"]
    )
    panel = contract.review.model_dump()["panel"]
    graph = build_graph(DemoConnector(store), Evaluator(store), fulltext=fulltext, panel=panel)
    return graph.invoke({"contract": contract.model_dump()}), store


def test_demo_panel_run_reviews_scores_and_ranks(tmp_path):
    (tmp_path / "uploads").mkdir()
    (tmp_path / "uploads" / "demo_2.pdf").write_bytes(tiny_pdf(PAPER_LINES))
    result, store = run_panel(tmp_path, panel_contract())
    review = result["review"]
    assert sorted(review) == ["demo:1", "demo:2", "demo:3"]
    assert review["demo:1"]["text_source"] == "abstract"
    assert review["demo:1"]["text_reason"] == "pmc_oa: no PMCID; upload: no uploaded PDF"
    assert review["demo:2"]["text_source"] == "upload" and review["demo:2"]["text_sections"] == [
        "",
        "Methods",
        "Results",
    ]
    first = review["demo:1"]
    assert set(first["reviews"]) == {"methodologist", "clinician", "statistician"}
    m = first["reviews"]["methodologist"]
    assert m["name"] == "Methodologist" and m["version"] == 1 and m["score"] == 50.0 and m["coverage"] == 0.2
    assert first["editor"]["verdict"] == "include" and first["score"] is not None
    assert first["red_flags"] == []  # demo answers the first two items; neither is a red-flag item
    assert [r["paper_id"] for r in result["ranking"]] == ["demo:1", "demo:2", "demo:3"]
    assert result["reviews_a"] == result["reviews_b"] == result["decisions"] == {}
    assert "content" not in result["texts"]["demo:1"] and result["texts"]["demo:1"]["sha256"]
    with store.connect() as db:
        roles = {r for (r,) in db.execute("SELECT DISTINCT role FROM calls")}
    assert roles == {
        "plan",
        "screen",
        "extract",
        "review:methodologist",
        "review:clinician",
        "review:statistician",
        "editor",
    }


def test_reviewers_receive_the_full_text_and_only_item_key_and_text(tmp_path):
    (tmp_path / "uploads").mkdir()
    (tmp_path / "uploads" / "demo_1.pdf").write_bytes(tiny_pdf(PAPER_LINES))
    run_panel(tmp_path, panel_contract())
    with Store(tmp_path).connect() as db:
        (raw,) = db.execute(
            "SELECT input FROM calls WHERE role='review:methodologist' AND input LIKE '%patient level%'"
        ).fetchone()
    payload = json.loads(raw)["payload"]
    assert payload["text"]["source"] == "upload" and "## Methods" in payload["text"]["content"]
    assert set(payload["items"][0]) == {"key", "text"} and "abstract" not in payload["paper"]


def test_review_screening_thresholds_replace_the_fields(tmp_path):
    from research_agent.graph import effective_domain

    domain = {"thresholds": {"keep_min": 0.8}, "criteria": {}}
    review = {"screening": {"keep_min": 0.7}}
    assert effective_domain(domain, review)["thresholds"] == {"keep_min": 0.7}
    assert effective_domain(domain, {"screening": None}) is domain and effective_domain(None, review) is None


def write_review(tmp_path, data=None):
    path = tmp_path / "review.src.json"
    path.write_text(json.dumps(data or default_review(), indent=1))
    return path


def test_a_panel_run_copies_review_json_and_records_it(tmp_path):
    source = write_review(tmp_path)
    run = tmp_path / "run"
    contract = Contract(topic="retrieval augmented generation", max_papers=2, review=read_review(source))
    result = run_research(run, contract, review_file=source, uploads=[tmp_path / "shared"])
    assert (run / "review.json").read_bytes() == source.read_bytes()
    manifest = json.loads((run / "manifest.json").read_text())
    assert manifest["review"] == {
        "file": "review.json",
        "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "panel": [
            {"key": "methodologist", "name": "Methodologist", "version": 1},
            {"key": "clinician", "name": "Clinician", "version": 1},
            {"key": "statistician", "name": "Statistician", "version": 1},
        ],
        "uploads": [str(tmp_path / "shared")],
    }
    assert manifest["score_version"] == "panel-1" and manifest["fulltext_version"] == "ft-1"
    assert manifest["prompt_version"] == "m1.3"
    report = json.loads((run / "report.json").read_text())
    for key in ("papers", "screens", "evidence", "reviews_a", "reviews_b", "decisions", "ranking", "review"):
        assert key in report["state"]
    paper = report["state"]["review"]["demo:1"]
    assert set(paper) >= {"text_source", "reviews", "editor", "score", "coverage", "red_flags"}
    progress = json.loads((run / "progress.json").read_text())
    assert (
        progress["stages"]["review_clinician"] == "completed" and progress["stages"]["score"] == "completed"
    )
    md = (run / "report.md").read_text()
    assert "Peer review" in md and "Methodologist" in md and "Text: abstract" in md
    assert len(result["ranking"]) == 2


def test_a_panel_run_resumes_with_its_saved_review(tmp_path):
    run = tmp_path / "run"
    contract = Contract(
        topic="retrieval augmented generation",
        max_papers=2,
        review=ReviewSpec.model_validate(default_review()),
    )
    assert run_research(run, contract, stop_after="extract") is None
    assert (run / "review.json").exists()
    result = run_research(run, resume=True)
    assert set(result["review"]) == {"demo:1", "demo:2"}


def test_legacy_runs_have_no_review(tmp_path):
    run_research(tmp_path / "run", Contract(topic="retrieval augmented generation", max_papers=1))
    manifest = json.loads((tmp_path / "run" / "manifest.json").read_text())
    assert manifest["review"] is None and manifest["score_version"] == "m1.1"
    state = json.loads((tmp_path / "run" / "report.json").read_text())["state"]
    assert "review" not in state and state["contract"]["review"] is None


def test_cli_review_flag(tmp_path, monkeypatch):
    source = write_review(tmp_path)
    run = tmp_path / "run"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "research-agent",
            "retrieval augmented generation",
            "--review",
            str(source),
            "--run-dir",
            str(run),
            "--max-papers",
            "1",
        ],
    )
    cli.main()
    assert (run / "review.json").exists()


@pytest.mark.parametrize(
    ("extra", "message"),
    [(["--resume"], "--resume reads the saved run; do not pass --review"), ([], "review.json is invalid")],
)
def test_cli_refuses_bad_review_use(tmp_path, monkeypatch, capsys, extra, message):
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"schema": 1, "panel": []}))
    args = ["research-agent", "t" * 5, "--review", str(bad), "--run-dir", str(tmp_path / "r"), *extra]
    monkeypatch.setattr(sys, "argv", args)
    with pytest.raises(SystemExit):
        cli.main()
    assert message in capsys.readouterr().err
