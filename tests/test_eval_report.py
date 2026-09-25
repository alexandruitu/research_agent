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


def screened_run(base, name="toy", mutate=lambda g: g, jev_p=JEV_P, llm_exclude=LLM_EXCLUDE):
    gold = write_gold(mutate(make_gold(n=12, positive_ids=(1, 2, 3, 4), name=name)), base / "gold.json")
    run = base / "run"
    store = Store(run)
    jev = JevScreener(store, "k", client=jev_client(jev_p))
    result = run_screen(gold, store, StubEvaluator(store, exclude=llm_exclude), jev)
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
    # ties on calls_saved prefer the stricter include threshold (was 0.1 with the old tie-break)
    assert best["min_confidence"] == 0.8 and best["calls_saved"] == 5
    assert any("untested on held-out data" in w for w in report["warnings"])


def test_no_recommendation_when_target_unreachable(tmp_path):
    run = screened_run(tmp_path)
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
    with pytest.raises(ReportError, match=r"12 candidate\(s\) have missing cached calls"):
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


# Holdout data where the pair recommended on the main run (0.8, 0.95) behaves differently:
# MED:2 is auto-excluded by Jev (conf 0.96) and MED:3 is escalated and excluded by the LLM.
HOLDOUT_P = {1: 0.99, 2: 0.02, 3: 0.5, 4: 0.6, 5: 0.01, 6: 0.5, 7: 0.96, 8: 0.5, 9: 0.95, 12: 0.04}
HOLDOUT_EXCLUDE = {"MED:3", "MED:8"}


def holdout_run(base):
    return screened_run(base, name="other", jev_p=HOLDOUT_P, llm_exclude=HOLDOUT_EXCLUDE)


def test_holdout_applies_the_recommended_pair_to_a_second_run(tmp_path):
    main = screened_run(tmp_path / "a")
    report = build_report(main, holdout_dir=holdout_run(tmp_path / "b"))
    h = report["holdout"]
    assert h["gold"] == "other" and h["n"] == 12
    assert h["thresholds"] == {"min_confidence": 0.8, "exclude_min_confidence": 0.95}
    assert (h["recall"]["k"], h["recall"]["n"]) == (2, 4)
    assert [m["id"] for m in h["missed"]] == ["MED:2", "MED:3"]
    assert h["calls_saved"] == 5  # auto-include MED:1,7,9 (MED:4 escalates at 0.8); auto-exclude MED:2,5
    assert h["jev_model_versions"] == ["jev-1.13.0"]
    assert not any("untested on held-out data" in w for w in report["warnings"])
    assert not any("Holdout Jev model versions" in w for w in report["warnings"])


def test_holdout_with_a_different_jev_model_version_warns(tmp_path):
    main = screened_run(tmp_path / "a")
    other = holdout_run(tmp_path / "b")
    with Store(other).connect() as db:
        db.execute(
            "UPDATE calls SET output = replace(output, 'jev-1.13.0', 'jev-1.14.0') WHERE role='jev_screen'"
        )
    report = build_report(main, holdout_dir=other)
    assert report["holdout"]["jev_model_versions"] == ["jev-1.14.0"]
    assert any("Holdout Jev model versions" in w and "jev-1.14.0" in w for w in report["warnings"])


def test_holdout_with_mixed_jev_versions_warns_when_allowed(tmp_path):
    main = screened_run(tmp_path / "a")
    other = holdout_run(tmp_path / "b")
    with Store(other).connect() as db:
        db.execute(
            "UPDATE calls SET output = replace(output, 'jev-1.13.0', 'jev-1.14.0') "
            "WHERE rowid = (SELECT min(rowid) FROM calls WHERE role='jev_screen')"
        )
    report = build_report(main, holdout_dir=other, allow_mixed=True)
    assert report["holdout"]["jev_model_versions"] == ["jev-1.13.0", "jev-1.14.0"]
    assert any("Holdout Jev model versions" in w for w in report["warnings"])


def test_holdout_errors_name_the_holdout_run(tmp_path):
    main = screened_run(tmp_path / "a")
    other = holdout_run(tmp_path / "b")
    with Store(other).connect() as db:
        db.execute("DELETE FROM calls WHERE role='jev_screen'")
    with pytest.raises(
        ReportError, match=r"holdout run .*b.*run: 12 candidate\(s\) have missing cached calls"
    ):
        build_report(main, holdout_dir=other)


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


def test_stale_agreement_file_from_another_gold_set_is_refused(run_dir, tmp_path):
    gold = load_gold(tmp_path / "gold.json")
    path = run_agreement(gold, run_dir, Evaluator(Store(run_dir)), limit=2)
    data = json.loads(path.read_text())
    data["papers"]["MED:999"] = data["papers"].pop("MED:1")
    path.write_text(json.dumps(data))
    with pytest.raises(ReportError, match="agreement.json does not belong to this gold set"):
        build_report(run_dir)


def no_abstract(ids):
    def mutate(g):
        for i in ids:
            g.candidates[i].abstract = ""
            g.candidates[i].flags = ["no_abstract"]
        return g

    return mutate


def test_no_screened_positives_is_reported_as_undefined_not_unreachable(tmp_path):
    report = build_report(screened_run(tmp_path, mutate=no_abstract(range(4))))
    assert report["counts"]["positives_screened"] == 0 and report["recommended"] is None
    assert any(
        "No SR-included paper with an abstract was screened; recall is undefined." in w
        for w in report["warnings"]
    )
    assert not any("No threshold pair reaches" in w for w in report["warnings"])


def test_run_without_any_abstract_renders_with_empty_sections(tmp_path):
    run = screened_run(tmp_path, mutate=no_abstract(range(12)))
    (run / "agreement.json").write_text(json.dumps({"seed": 0, "limit": 0, "papers": {}}))
    report = build_report(run)
    assert report["counts"]["screened"] == 0
    assert report["screen_vs_gold"] is None and report["agreement"] is None
    write_report(run, report)
    text = (run / "metrics.md").read_text()
    assert "## LLM screen vs SR label" in text and "n/a" in text
    assert "## Reviewer agreement" not in text


def test_recall_exactly_equal_to_the_target_is_accepted(tmp_path):
    best = build_report(screened_run(tmp_path), target_recall=0.75)["recommended"]
    assert best["recall"]["value"] == 0.75 and best["calls_saved"] == 7


def with_models(run_dir, models):
    path = run_dir / "manifest.json"
    manifest = json.loads(path.read_text())
    manifest["models"] = models
    path.write_text(json.dumps(manifest))


@pytest.mark.parametrize(
    ("models", "expected"),
    [
        ({"review_a": "a:x", "review_b": "a:y"}, True),
        ({"review_a": "a:x", "review_b": "b:y"}, False),
    ],
)
def test_same_family_compares_reviewer_providers(run_dir, tmp_path, models, expected):
    run_agreement(load_gold(tmp_path / "gold.json"), run_dir, Evaluator(Store(run_dir)), limit=2)
    with_models(run_dir, models)  # demo mode ignores the model names, so cached calls still match
    assert build_report(run_dir)["agreement"]["same_family"] is expected


class UncertainEvaluator(StubEvaluator):
    def _demo(self, role, payload):
        if role == "screen":
            return Screen(decision="uncertain", reason="unsure")
        return super()._demo(role, payload)


def test_uncertain_llm_decision_counts_as_kept_against_gold(tmp_path):
    gold = write_gold(make_gold(n=12, positive_ids=(1, 2, 3, 4)), tmp_path / "gold.json")
    run, store = tmp_path / "run", Store(tmp_path / "run")
    jev = JevScreener(store, "k", client=jev_client(JEV_P))
    result = run_screen(gold, store, UncertainEvaluator(store), jev)
    write_manifest(
        run,
        gold_path=tmp_path / "gold.json",
        gold=gold,
        mode="demo",
        models={},
        jev_model="jev-latest",
        screened=result,
    )
    sg = build_report(run)["screen_vs_gold"]
    assert sg["agreement"] == pytest.approx(4 / 12)  # everything kept; only the 4 positives agree
    assert sg["prevalence"]["kept"] == pytest.approx(16 / 24)


def test_markdown_shows_agreement_and_prevalence_next_to_every_kappa(run_dir, tmp_path):
    run_agreement(load_gold(tmp_path / "gold.json"), run_dir, Evaluator(Store(run_dir)), limit=2)
    text = render_markdown(build_report(run_dir))
    kappa_lines = [ln for ln in text.splitlines() if "kappa" in ln and ln.startswith(("-", "Cohen"))]
    assert len(kappa_lines) == 5  # screen vs gold, verdict, relevance, methods, support
    for line in kappa_lines:
        assert "agreement " in line and "prevalence " in line, line


def test_markdown_workload_columns_and_jev_only_footnote(run_dir):
    text = render_markdown(build_report(run_dir))
    assert "| auto-included | auto-excluded | sent to LLM |" in text
    row = {ln.split("|")[1].strip(): ln for ln in text.splitlines() if ln.startswith("| ")}
    assert "| 0 (0.0%) | 0 (0.0%) | 12 (100.0%) |" in row["llm_only"]
    assert "| 3 (25.0%) | 4 (33.3%) | 5 (41.7%) |" in row["cascade"]
    assert "undecided (kept, no LLM look)" in row["jev_only"]
    assert "jev_only makes no LLM calls: undecided papers are kept without any LLM look" in text
    assert "so its recall is not comparable with cascade" in text


def test_markdown_renders_unknown_family_and_no_negative_zero(run_dir, tmp_path):
    run_agreement(load_gold(tmp_path / "gold.json"), run_dir, Evaluator(Store(run_dir)), limit=2)
    report = build_report(run_dir)
    report["screen_vs_gold"]["kappa"] = -0.0004
    text = render_markdown(report)
    assert "same model family: unknown" in text
    assert "-0.000" not in text and "Cohen's kappa 0.000" in text


def test_holdout_run_must_use_a_different_gold_set(run_dir):
    with pytest.raises(ReportError, match="holdout run uses the same gold set; it must be a different SR"):
        build_report(run_dir, holdout_dir=run_dir)


def test_markdown_shows_kept_and_kept_negatives_and_the_cost_note(run_dir):
    report = build_report(run_dir)
    cascade = report["strategies"]["cascade"]
    assert (cascade["kept"], cascade["kept_negatives"]) == (6, 3)  # kept: 1, 2, 4, 9, 10, 11
    text = render_markdown(report)
    assert "| kept | kept non-included |" in text  # strategies table and sweep table
    row = {ln.split("|")[1].strip(): ln for ln in text.splitlines() if ln.startswith("| ")}
    assert row["llm_only"].rstrip().endswith("| 10 | 6 |")
    assert (
        "calls saved counts only screening calls; papers kept are forwarded to extraction and both "
        "reviewers, so a loose include threshold can forward more negatives than llm_only"
    ) in text


# Every positive is confidently included by Jev; every negative gets p=0.9 from Jev but is excluded by the LLM.
# A loose include threshold saves the most calls yet forwards all 8 negatives (llm_only forwards none).
LOOSE_P = {**dict.fromkeys(range(1, 5), 0.97), **dict.fromkeys(range(5, 13), 0.9)}


def test_warns_when_the_recommended_pair_forwards_more_negatives_than_llm_only(tmp_path):
    negatives = {f"MED:{i}" for i in range(5, 13)}
    run = screened_run(tmp_path, jev_p=LOOSE_P, llm_exclude=negatives)
    report = build_report(run)
    assert report["strategies"]["llm_only"]["kept_negatives"] == 0
    assert report["recommended"]["kept_negatives"] == 8
    expected = (
        "The recommended pair forwards more non-included papers than llm_only (8 vs 0); "
        "consider a stricter include threshold."
    )
    assert expected in report["warnings"]
    assert expected in render_markdown(report)


def test_no_forwarding_warning_when_the_pair_forwards_no_more_than_llm_only(run_dir):
    report = build_report(run_dir)
    assert not any("forwards more non-included" in w for w in report["warnings"])


def test_markdown_marks_recommended_and_default_rows_and_formats_probabilities(run_dir):
    report = build_report(run_dir)
    text = render_markdown(report)
    lines = text.splitlines()
    assert sum("<-- recommended" in ln for ln in lines) == 1
    assert sum("<-- default" in ln for ln in lines) == 1
    assert next(ln for ln in lines if "<-- recommended" in ln).startswith("| 0.8 | 0.95 |")
    assert next(ln for ln in lines if "<-- default" in ln).startswith("| 0.6 | 0.9 |")
    assert "Jev topic_match=0.03" in text and "p={" not in text


def test_default_row_can_also_be_the_recommended_one(run_dir):
    report = build_report(run_dir)
    report["recommended"] = next(
        r for r in report["sweep"] if (r["min_confidence"], r["exclude_min_confidence"]) == (0.6, 0.9)
    )
    both = [ln for ln in render_markdown(report).splitlines() if "<-- recommended" in ln]
    assert len(both) == 1 and "<-- default" in both[0]


def test_run_metadata_is_recorded_in_json_and_markdown(run_dir):
    report = build_report(run_dir)
    manifest = json.loads((run_dir / "manifest.json").read_text())
    assert report["run"] == {
        "prompt_version": manifest["prompt_version"],
        "jev_screen_version": manifest["jev_screen_version"],
        "models": manifest["models"],
    }
    assert f"Run: prompt {manifest['prompt_version']}" in render_markdown(report)
    with_models(run_dir, {"screen": "a:x", "review_a": "b:y"})
    text = render_markdown(build_report(run_dir))
    assert "models: review_a=b:y, screen=a:x" in text
    assert render_markdown(build_report(run_dir)) == text  # deterministic
