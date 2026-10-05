import json

import langchain.chat_models
import pytest
from eval_helpers import FakeFulltext, PanelStub, panel_gold, small_review

from research_agent.eval.ablation import build_ablation_metrics, load_ablation, reviewer_subsets, run_ablation
from research_agent.eval.gold import write_gold
from research_agent.eval.panel_eval import gold_source, run_panel_eval
from research_agent.schemas import read_review
from research_agent.storage import Store

KEYS = ("methodologist", "clinician", "statistician")


def panel_dir(tmp_path, n=4):
    gold = write_gold(panel_gold(), tmp_path / "gold.json")
    review_path = small_review(tmp_path / "review.json", KEYS)
    topic, papers, rows = gold_source(gold)
    eval_dir = tmp_path / "panel"
    run_panel_eval(
        eval_dir,
        topic=topic,
        papers=papers,
        rows=rows,
        labels={r["id"]: r["label"] for r in rows},
        source={"gold_sha256": gold.content_sha256},
        review=read_review(review_path).model_dump(),
        review_path=review_path,
        evaluator=PanelStub(Store(eval_dir)),
        fulltext=FakeFulltext(),
        n=n,
        seed=1,
        mode="demo",
    )
    return eval_dir


def test_reviewer_subsets_cover_every_size():
    assert reviewer_subsets(["a", "b", "c"]) == [
        ("a",),
        ("b",),
        ("c",),
        ("a", "b"),
        ("a", "c"),
        ("b", "c"),
        ("a", "b", "c"),
    ]


def test_offline_ablation_scores_every_subset_without_calls(tmp_path, monkeypatch):
    source = panel_dir(tmp_path)
    monkeypatch.setattr(langchain.chat_models, "init_chat_model", lambda *a, **k: pytest.fail("no calls"))
    data = run_ablation(source, tmp_path / "abl")
    assert len(data["subsets"]) == 7 and data["full"] == "+".join(KEYS)
    single = data["subsets"]["statistician"]["papers"]["MED:1"]
    # The contrarian stub reviewer excludes included papers and answers its own item 'not_reported'.
    assert single["verdict"] == "exclude" and single["flags"] == [] and single["editor"] is None
    full = data["subsets"][data["full"]]["papers"]["MED:7"]
    assert full["flags"] == ["clinician item one.", "methodologist item one."]
    assert full["cost"]["calls"] == 4 and full["cost"]["chars"] > 0 and not full["cost"]["editor_estimated"]
    manifest, again = load_ablation(tmp_path / "abl")
    assert manifest["kind"] == "ablation" and manifest["rerun_editor"] is False and again == data
    assert not (tmp_path / "abl" / "research.sqlite").exists()


def test_ablation_metrics_compare_subsets_with_full_panel(tmp_path):
    run_ablation(panel_dir(tmp_path), tmp_path / "abl")
    m = build_ablation_metrics(*load_ablation(tmp_path / "abl"))
    by = {r["subset"]: r for r in m["subsets"]}
    assert by["methodologist+clinician+statistician"]["verdict_changed"]["value"] == 0
    assert by["statistician"]["verdict_changed"]["value"] == 1.0  # contrarian alone flips every verdict
    assert by["statistician"]["red_flags_missed"]["value"] == 1.0
    assert by["methodologist"]["red_flags_missed"]["value"] == 0.5
    assert by["methodologist"]["cost_delta"]["calls"] == pytest.approx(-0.5)
    assert m["sizes"]["1"]["subsets"] == 3 and m["sizes"]["3"]["verdict_changed"] == 0
    assert m["summary"]["from_size"] == 2 and "Going from 2 to 3 reviewers" in m["summary"]["sentence"]
    assert m["token_usage"] is None and m["cost_basis"] == "chars"


def test_rerun_editor_asks_per_proper_subset_and_caches(tmp_path):
    source = panel_dir(tmp_path, n=2)
    stub = PanelStub(Store(tmp_path / "abl"))
    data = run_ablation(source, tmp_path / "abl", rerun_editor=True, evaluator=stub, mode="demo")
    assert stub.calls == {"editor": 6 * 2}  # 6 proper subsets x 2 papers; the full panel reuses its editor
    assert data["subsets"]["clinician"]["papers"]["MED:1"]["editor"] == "include"
    again = PanelStub(Store(tmp_path / "abl"))
    run_ablation(source, tmp_path / "abl", rerun_editor=True, evaluator=again, mode="demo")
    assert again.calls == {}
    assert json.loads((tmp_path / "abl" / "manifest.json").read_text())["editor_model"] == "synthetic-demo-v1"
    with pytest.raises(ValueError, match="needs an evaluator"):
        run_ablation(source, tmp_path / "x", rerun_editor=True)
