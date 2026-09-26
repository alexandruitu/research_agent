import pytest

from research_agent.eval.metrics import (
    INCLUDE_GRID,
    cascade_decision,
    cohen_kappa,
    evaluate,
    rate,
    recommend,
    sweep,
    weighted_kappa,
    wilson,
)
from research_agent.jev import JevThresholds


def test_wilson_known_values():
    low, high = wilson(40, 40)
    assert low == pytest.approx(0.912, abs=2e-3)
    assert high == pytest.approx(1.0, abs=1e-9)
    low, high = wilson(0, 10)
    assert low == pytest.approx(0.0, abs=1e-9)
    assert high == pytest.approx(0.277, abs=2e-3)


def test_wilson_interior_value():
    low, high = wilson(36, 40)
    assert low == pytest.approx(0.769, abs=2e-3)
    assert high == pytest.approx(0.960, abs=2e-3)


def test_wilson_zero_trials_is_none():
    assert wilson(0, 0) is None


def test_rate_carries_interval_and_handles_zero_denominator():
    r = rate(36, 40)
    assert r["value"] == pytest.approx(0.9) and (r["k"], r["n"]) == (36, 40)
    assert r["ci"][0] < 0.9 < r["ci"][1]
    empty = rate(0, 0)
    assert empty["value"] is None and empty["ci"] is None and "zero" in empty["reason"]


def test_cohen_kappa_textbook_example():
    a = ["yes"] * 25 + ["no"] * 25
    # 20 both yes, 5 A-yes/B-no, 10 A-no/B-yes, 15 both no
    b = ["yes"] * 20 + ["no"] * 5 + ["yes"] * 10 + ["no"] * 15
    r = cohen_kappa(a, b)
    assert r["agreement"] == pytest.approx(0.7)
    assert r["kappa"] == pytest.approx(0.4)
    assert r["prevalence"]["yes"] == pytest.approx(0.55)
    assert r["prevalence"]["no"] == pytest.approx(0.45)


def test_cohen_kappa_single_class_is_none_with_reason():
    r = cohen_kappa(["x", "x"], ["x", "x"])
    assert r["kappa"] is None and "single class" in r["reason"]
    assert r["agreement"] == 1.0


def test_cohen_kappa_rejects_bad_input():
    with pytest.raises(ValueError):
        cohen_kappa([], [])
    with pytest.raises(ValueError):
        cohen_kappa(["a"], ["a", "b"])


def test_weighted_kappa():
    assert weighted_kappa([0, 1, 2, 3, 4], [0, 1, 2, 3, 4])["kappa"] == pytest.approx(1.0)
    assert weighted_kappa([0, 4, 0, 4], [4, 0, 4, 0])["kappa"] == pytest.approx(-1.0)
    constant = weighted_kappa([2, 2, 2], [2, 2, 2])
    assert constant["kappa"] is None and "single class" in constant["reason"]
    # An off-by-one costs less than an off-by-three.
    near = weighted_kappa([0, 1, 2, 3, 4, 2], [1, 2, 2, 3, 3, 2])["kappa"]
    far = weighted_kappa([0, 1, 2, 3, 4, 2], [3, 4, 2, 0, 1, 2])["kappa"]
    assert near > far
    # Pins quadratic weighting: linear weights would give 0.5714 here.
    assert near == pytest.approx(0.7692, abs=1e-3)


def test_weighted_kappa_reports_raw_agreement_and_prevalence():
    result = weighted_kappa([0, 1, 2, 3, 4, 2], [1, 2, 2, 3, 3, 2])
    assert result["agreement"] == pytest.approx(0.5)
    assert result["prevalence"] == pytest.approx({0: 1 / 12, 1: 2 / 12, 2: 5 / 12, 3: 3 / 12, 4: 1 / 12})
    constant = weighted_kappa([2, 2, 2], [2, 2, 2])
    assert constant["agreement"] == 1.0 and constant["prevalence"] == {2: 1.0}


def test_weighted_kappa_rejects_bad_scores_and_levels():
    with pytest.raises(ValueError):
        weighted_kappa([0, 5], [0, 1])
    with pytest.raises(ValueError):
        weighted_kappa([0, 1], [0, 9])
    with pytest.raises(ValueError):
        weighted_kappa([1, 1], [1, 1], levels=[1])


def rec(i, label, p, llm="include"):
    return {
        "id": f"MED:{i}",
        "title": f"Paper {i}",
        "label": label,
        "probabilities": {"topic_match": p},
        "llm": llm,
    }


RECORDS = [
    rec(1, "include", 0.97),  # jev include
    rec(2, "include", 0.50),  # escalate -> llm include
    rec(3, "include", 0.03),  # jev exclude at default thresholds: the miss
    rec(4, "include", 0.90),
    rec(5, "not_included", 0.01),
    rec(6, "not_included", 0.50, llm="exclude"),
    rec(7, "not_included", 0.95),
    rec(8, "not_included", 0.50, llm="exclude"),
]


def test_cascade_uses_jev_when_confident_else_llm():
    t = JevThresholds()
    assert cascade_decision({"q": 0.97}, "exclude", t) == ("include", "jev")
    assert cascade_decision({"q": 0.5}, "exclude", t) == ("exclude", "llm")


def test_evaluate_cascade_counts_misses_and_workload():
    out = evaluate(RECORDS, "cascade", JevThresholds())
    assert (out["recall"]["k"], out["recall"]["n"]) == (3, 4)
    assert [m["id"] for m in out["missed"]] == ["MED:3"]
    assert out["missed"][0]["tier"] == "jev"
    assert (out["auto_include"], out["auto_exclude"], out["escalated"]) == (3, 2, 3)
    assert out["calls_saved"] == 5
    assert (out["kept"], out["kept_negatives"]) == (4, 1)  # kept: 1, 2, 4, 7; MED:7 is not SR-included


def test_llm_only_and_jev_only_baselines():
    llm = evaluate(RECORDS, "llm_only", JevThresholds())
    assert llm["recall"]["k"] == 4 and llm["calls_saved"] == 0
    assert (llm["kept"], llm["kept_negatives"]) == (6, 2)  # everything but the two LLM excludes
    jev = evaluate(RECORDS, "jev_only", JevThresholds())
    assert [m["id"] for m in jev["missed"]] == ["MED:3"]  # 'escalate' counts as kept
    assert jev["calls_saved"] == 8
    assert (jev["kept"], jev["kept_negatives"]) == (6, 3)  # undecided papers are kept
    with pytest.raises(ValueError):
        evaluate(RECORDS, "nonsense", JevThresholds())


def test_sweep_respects_constraint_and_recall_is_monotone_in_exclude_threshold():
    rows = sweep(RECORDS)
    assert len(rows) == 53
    assert all(r["exclude_min_confidence"] >= r["min_confidence"] for r in rows)
    assert all({"kept", "kept_negatives"} <= r.keys() and r["kept"] >= r["kept_negatives"] for r in rows)
    for include in INCLUDE_GRID:
        excludes = [r["exclude_min_confidence"] for r in rows if r["min_confidence"] == include]
        assert excludes == sorted(excludes)
        recalls = [r["recall"]["value"] for r in rows if r["min_confidence"] == include]
        assert recalls == sorted(recalls)  # rows are ordered by ascending exclude threshold


def test_evaluate_lists_positives_lost_versus_llm_only():
    cascade = evaluate(RECORDS, "cascade", JevThresholds())
    assert [m["id"] for m in cascade["lost_vs_llm"]] == ["MED:3"]  # excluded by Jev, kept by the LLM
    assert set(cascade["lost_vs_llm"][0]) == {"id", "title", "probabilities", "tier"}
    assert cascade["lost_vs_llm"][0]["tier"] == "jev"
    assert [m["id"] for m in evaluate(RECORDS, "jev_only", JevThresholds())["lost_vs_llm"]] == ["MED:3"]
    assert evaluate(RECORDS, "llm_only", JevThresholds())["lost_vs_llm"] == []


def test_a_positive_the_llm_also_excludes_is_not_lost():
    records = [rec(1, "include", 0.5, llm="exclude"), rec(2, "include", 0.02, llm="exclude")]
    out = evaluate(records, "cascade", JevThresholds())
    assert len(out["missed"]) == 2 and out["lost_vs_llm"] == []  # llm_only misses both as well


def test_sweep_rows_carry_lost_counts_and_ids():
    rows = sweep(RECORDS)
    by_pair = {(r["min_confidence"], r["exclude_min_confidence"]): r for r in rows}
    assert by_pair[(0.6, 0.9)]["lost_vs_llm"] == 1 and by_pair[(0.6, 0.9)]["lost_ids"] == ["MED:3"]
    assert by_pair[(0.6, 0.95)]["lost_vs_llm"] == 0 and by_pair[(0.6, 0.95)]["lost_ids"] == []
    assert all(r["lost_vs_llm"] == len(r["lost_ids"]) for r in rows)


def test_recommend_picks_the_most_calls_saved_among_pairs_that_lose_nothing():
    rows = sweep(RECORDS)
    best = recommend(rows)
    assert (
        best["lost_vs_llm"] == 0 and best["exclude_min_confidence"] >= 0.95
    )  # p=0.03 needs the stricter bar
    assert all(r["calls_saved"] <= best["calls_saved"] for r in rows if r["lost_vs_llm"] == 0)


def test_recommend_says_none_when_every_pair_loses_something():
    # p=0.5 everywhere except the positive, which Jev excludes at every bar and the LLM keeps.
    rows = sweep([rec(1, "include", 0.0), rec(2, "not_included", 0.5)], excludes=[0.5])
    assert all(r["lost_vs_llm"] == 1 for r in rows)
    assert recommend(rows) is None


def row(recall, missed, calls_saved, include, exclude, lost=0):
    return {
        "recall": {"value": recall},
        "missed": missed,
        "calls_saved": calls_saved,
        "min_confidence": include,
        "exclude_min_confidence": exclude,
        "lost_vs_llm": lost,
    }


def test_recommend_never_picks_a_row_that_loses_something_even_if_it_saves_most():
    greedy, safe = row(1.0, 0, 9, 0.1, 0.5, lost=1), row(1.0, 0, 1, 0.6, 0.9)
    assert recommend([greedy, safe]) is safe
    assert recommend([greedy]) is None


def test_other_rows_veto_a_pair_that_loses_something_there():
    main = [row(1.0, 0, 9, 0.1, 0.5), row(1.0, 0, 3, 0.6, 0.95)]
    other = [row(1.0, 0, 9, 0.1, 0.5, lost=1), row(1.0, 0, 2, 0.6, 0.95)]
    assert recommend(main) is main[0]
    assert recommend(main, other_rows=other) is main[1]
    assert recommend(main, other_rows=[row(1.0, 0, 2, 0.6, 0.95, lost=1), other[0]]) is None
    assert recommend(main, other_rows=[]) is None  # a pair absent from the holdout is not admissible


def test_other_rows_add_their_calls_saved_to_the_ranking():
    main = [row(1.0, 0, 5, 0.6, 0.9), row(1.0, 0, 4, 0.6, 0.95)]
    other = [row(1.0, 0, 1, 0.6, 0.9), row(1.0, 0, 3, 0.6, 0.95)]
    assert recommend(main, other_rows=other) is main[1]  # 4 + 3 beats 5 + 1


def test_target_is_an_extra_constraint_when_given():
    low, high = row(0.8, 0, 9, 0.6, 0.9), row(1.0, 0, 1, 0.6, 0.95)
    assert recommend([low, high]) is low
    assert recommend([low, high], target=0.9) is high
    assert recommend([low, high], target=1.01) is None
    assert recommend([low], target=0.8) is low  # equal to the target is accepted


def test_recommend_tie_breaks():
    # (a) equal calls_saved: fewer missed wins
    fewer, more = row(1.0, 0, 5, 0.6, 0.9), row(1.0, 1, 5, 0.6, 0.99)
    assert recommend([more, fewer], target=0.9) is fewer
    # (b) tied on calls_saved and missed: stricter (higher) exclude threshold wins
    strict, lax = row(1.0, 0, 5, 0.6, 0.99), row(1.0, 0, 5, 0.6, 0.9)
    assert recommend([lax, strict], target=0.9) is strict
    # (b2) tied on calls_saved and missed: the stricter (higher) INCLUDE threshold wins, whatever the exclude one
    loose, tight = row(1.0, 0, 5, 0.2, 0.99), row(1.0, 0, 5, 0.6, 0.9)
    assert recommend([loose, tight], target=0.9) is tight
    assert recommend([tight, loose], target=0.9) is tight
    # (c) with a target, a row with undefined recall is never chosen, even if it saves the most calls
    undefined, ok = row(None, 0, 9, 0.6, 0.99), row(1.0, 0, 1, 0.6, 0.9)
    assert recommend([undefined, ok], target=0.9) is ok
    assert recommend([undefined], target=0.9) is None
