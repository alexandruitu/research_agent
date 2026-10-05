import json

import pytest
from eval_helpers import FakeFulltext, PanelStub, panel_gold, small_review

from research_agent.eval.gold import write_gold
from research_agent.eval.panel_eval import gold_source, load_panel_eval, run_panel_eval, sample_papers
from research_agent.schemas import read_review
from research_agent.storage import Store


def rows(labels):
    return [
        {"id": f"p{i:02d}", "label": label, "year": "2023" if i % 2 else "2024", "source": "query"}
        for i, label in enumerate(labels, 1)
    ]


def test_sample_takes_included_first_then_matched_excluded():
    papers = rows(["include", "include", "not_included", "not_included", "not_included", "not_included"])
    ids = sample_papers(papers, 4, seed=1)
    assert ids[:2] == ["p01", "p02"]
    by_id = {p["id"]: p for p in papers}
    assert [by_id[i]["year"] for i in ids[2:]] == ["2023", "2024"]  # matched on year, in order
    assert sample_papers(papers, 4, seed=1) == ids  # deterministic


def test_sample_caps_included_at_half_and_fills_with_excluded():
    papers = rows(["include"] * 5 + ["not_included"] * 5)
    ids = sample_papers(papers, 5, seed=3)
    labels = {p["id"]: p["label"] for p in papers}
    assert len(ids) == 5 and sum(labels[i] == "include" for i in ids) == 2
    assert len(sample_papers(papers, 50, seed=3)) == 10


def test_sample_unlabelled_is_seeded_sample_and_rejects_zero():
    papers = rows([None] * 6)
    assert sample_papers(papers, 3, seed=2) == sample_papers(papers, 3, seed=2)
    assert len(sample_papers(papers, 3, seed=2)) == 3
    with pytest.raises(ValueError):
        sample_papers(papers, 0, seed=1)


def run(tmp_path, n=4, evaluator=None, fulltext=None, eval_dir=None):
    gold = write_gold(panel_gold(), tmp_path / "gold.json")
    review_path = small_review(tmp_path / "review.json")
    review = read_review(review_path).model_dump()
    topic, papers, sample_rows = gold_source(gold)
    eval_dir = eval_dir or tmp_path / "eval"
    evaluator = evaluator or PanelStub(Store(eval_dir))
    data = run_panel_eval(
        eval_dir,
        topic=topic,
        papers=papers,
        rows=sample_rows,
        labels={r["id"]: r["label"] for r in sample_rows},
        source={"gold_path": str(tmp_path / "gold.json"), "gold_sha256": gold.content_sha256},
        review=review,
        review_path=review_path,
        evaluator=evaluator,
        fulltext=fulltext or FakeFulltext({"MED:1"}),
        n=n,
        seed=7,
        mode="demo",
    )
    return data, eval_dir, evaluator


def test_panel_eval_reviews_scores_and_freezes_config(tmp_path):
    data, eval_dir, evaluator = run(tmp_path)
    assert len(data["papers"]) == 4
    assert evaluator.calls == {"review:methodologist": 4, "review:statistician": 4, "editor": 4}
    p1 = data["papers"]["MED:1"]
    assert p1["label"] == "include" and p1["text_source"] == "pmc_oa"
    assert p1["reviews"]["methodologist"]["score"] == 100.0 and p1["editor"]["verdict"] == "include"
    manifest, review, panel = load_panel_eval(eval_dir)
    assert review["panel"][0]["key"] == "methodologist"
    assert manifest["kind"] == "panel" and manifest["sample"]["ids"] == list(data["papers"])
    assert manifest["sample"]["positives"] == 2 and manifest["prompt_version"]
    assert [r["key"] for r in manifest["panel"]] == ["methodologist", "statistician"]
    assert manifest["panel"][0]["model"] == "synthetic-demo-v1"
    assert len(manifest["review_sha256"]) == 64 and panel == data
    assert (eval_dir / "review.json").exists()


def test_panel_eval_resumes_from_cache_and_refuses_other_config(tmp_path):
    _data, eval_dir, _e = run(tmp_path)
    again = PanelStub(Store(eval_dir))
    run(tmp_path, evaluator=again)
    assert again.calls == {}  # everything came from research.sqlite
    with pytest.raises(ValueError, match="different evaluation"):
        run(tmp_path, n=6)


def test_load_refuses_edited_or_unfinished_panel(tmp_path):
    _data, eval_dir, _e = run(tmp_path)
    (eval_dir / "panel.json").write_text(json.dumps({"papers": {}}))
    with pytest.raises(ValueError, match="changed"):
        load_panel_eval(eval_dir)
    manifest = json.loads((eval_dir / "manifest.json").read_text())
    manifest["panel_sha256"] = None
    (eval_dir / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="did not finish"):
        load_panel_eval(eval_dir)
