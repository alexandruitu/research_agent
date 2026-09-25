import json

import langchain.chat_models
import pytest
from eval_helpers import StubEvaluator, jev_client, make_gold

from research_agent.agents import Evaluator
from research_agent.eval.agreement import run_agreement
from research_agent.eval.gold import StudyRef, UnmatchedStudy, load_gold, write_gold
from research_agent.eval.report import ReportError, build_report, render_markdown, write_report
from research_agent.eval.screen import run_screen, write_manifest
from research_agent.jev import JevScreener
from research_agent.schemas import Screen
from research_agent.storage import MissingCall, Store

JEV_P = {
    1: 0.97,
    2: 0.5,
    3: 0.03,
    4: 0.9,
    5: 0.01,
    6: 0.02,
    7: 0.5,
    8: 0.5,
    9: 0.95,
    10: 0.5,
    11: 0.5,
    12: 0.04,
}
LLM_EXCLUDE = {"MED:7", "MED:8"}


def screened_run(base, name="toy", mutate=lambda g: g):
    gold = write_gold(mutate(make_gold(n=12, positive_ids=(1, 2, 3, 4), name=name)), base / "gold.json")
    run = base / "run"
    store = Store(run)
    jev = JevScreener(store, "k", client=jev_client(JEV_P))
    result = run_screen(gold, store, StubEvaluator(store, exclude=LLM_EXCLUDE), jev)
    write_manifest(
        run,
        gold_path=base / "gold.json",
        gold=gold,
        mode="demo",
        models={},
        jev_model="jev-latest",
        screened=result,
    )
    return run


@pytest.fixture
def run_dir(tmp_path):
    return screened_run(tmp_path)


def test_strategies_at_default_thresholds(run_dir):
    report = build_report(run_dir)
    s = report["strategies"]
    assert s["llm_only"]["recall"]["k"] == 4 and s["llm_only"]["calls_saved"] == 0
    assert [m["id"] for m in s["cascade"]["missed"]] == ["MED:3"]  # p=0.03 auto-excluded at exclude>=0.9
    assert [m["id"] for m in s["jev_only"]["missed"]] == ["MED:3"]
    assert report["counts"]["screened"] == 12 and report["jev_model_versions"] == ["jev-1.13.0"]


def test_recommended_pair_needs_the_stricter_exclude_bar(run_dir):
    report = build_report(run_dir, target_recall=0.98)
    best = report["recommended"]
    assert best["recall"]["value"] == 1.0 and best["exclude_min_confidence"] >= 0.95
    assert any("untested on held-out data" in w for w in report["warnings"])


def test_no_recommendation_when_target_unreachable(tmp_path):
    run = screened_run(tmp_path, mutate=lambda g: g)
    # Positives MED:1..4 are all kept by the LLM, so an impossible target (>1) must yield None.
    report = build_report(run, target_recall=1.01)
    assert report["recommended"] is None
    assert any("No threshold pair reaches" in w for w in report["warnings"])


def test_retrieval_recall_counts_lookup_unresolved_and_ambiguous_as_misses(tmp_path):
    def mutate(g):
        g.candidates[3].via = "lookup"
        g.unresolved.append(UnmatchedStudy(reference=StudyRef(doi="10.1/zzz")))
        return g

    report = build_report(screened_run(tmp_path, mutate=mutate))
    r = report["retrieval_recall"]
    assert (r["k"], r["n"]) == (3, 5)


def test_positives_without_abstract_are_reported_separately(tmp_path):
    def mutate(g):
        g.candidates[0].abstract = ""
        g.candidates[0].flags = ["no_abstract"]
        return g

    report = build_report(screened_run(tmp_path, mutate=mutate))
    assert report["counts"]["positives_no_abstract"] == 1 and report["counts"]["positives_screened"] == 3


def test_missing_cached_calls_fail_with_a_count(run_dir):
    with Store(run_dir).connect() as db:
        db.execute("DELETE FROM calls WHERE role='jev_screen'")
    with pytest.raises(ReportError, match=r"12 cached call\(s\) missing"):
        build_report(run_dir)


def test_mixed_jev_versions_are_refused_unless_allowed(run_dir):
    with Store(run_dir).connect() as db:
        db.execute(
            "UPDATE calls SET output = replace(output, 'jev-1.13.0', 'jev-1.14.0') "
            "WHERE rowid = (SELECT min(rowid) FROM calls WHERE role='jev_screen')"
        )
    with pytest.raises(ReportError, match="model versions"):
        build_report(run_dir)
    report = build_report(run_dir, allow_mixed=True)
    assert any("model versions" in w for w in report["warnings"])


def test_edited_gold_file_is_rejected(run_dir, tmp_path):
    path = tmp_path / "gold.json"
    data = json.loads(path.read_text())
    data["candidates"][0]["label"] = "not_included"
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError):
        build_report(run_dir)


def test_holdout_applies_the_recommended_pair_to_a_second_run(tmp_path):
    main = screened_run(tmp_path / "a")
    other = screened_run(tmp_path / "b", name="other")
    report = build_report(main, holdout_dir=other)
    assert report["holdout"]["gold"] == "other" and report["holdout"]["recall"]["n"] == 4
    assert not any("untested on held-out data" in w for w in report["warnings"])


def test_agreement_and_screen_vs_gold_sections(run_dir, tmp_path):
    gold = load_gold(tmp_path / "gold.json")  # the gold file `screened_run` froze
    run_agreement(gold, run_dir, Evaluator(Store(run_dir)), limit=2)
    report = build_report(run_dir)
    ag = report["agreement"]
    assert ag["n"] == 6 and ag["adjudication_rate"]["value"] == 1.0
    assert ag["verdict"]["kappa"] is None  # both demo reviewers say 'include' everywhere: single class
    assert ag["same_family"] is None  # demo manifest has no provider prefixes
    assert report["screen_vs_gold"]["n"] == 12


def test_markdown_and_json_outputs(run_dir):
    report = build_report(run_dir)
    write_report(run_dir, report)
    text = (run_dir / "metrics.md").read_text()
    for needle in (
        "## Retrieval recall",
        "## Screening recall",
        "## Missed positives",
        "## Threshold sweep",
        "MED:3",
    ):
        assert needle in text
    assert json.loads((run_dir / "metrics.json").read_text())["gold"]["name"] == "toy"
    assert render_markdown(report) == text


def test_offline_live_evaluator_raises_missing_call_without_building_a_model(tmp_path, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("init_chat_model must not be called offline")

    monkeypatch.setattr(langchain.chat_models, "init_chat_model", forbidden)
    evaluator = Evaluator(Store(tmp_path), "live", {"screen": "x:y"}, offline=True)
    with pytest.raises(MissingCall):
        evaluator.ask("screen", Screen, {"topic": "t", "paper": {}})
