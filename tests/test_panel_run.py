import json

from pdf_helpers import PAPER_LINES, tiny_pdf

from research_agent.agents import Evaluator
from research_agent.connectors import DemoConnector
from research_agent.fulltext import FullText
from research_agent.graph import build_graph
from research_agent.panel import default_review
from research_agent.schemas import Contract, ReviewSpec
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
