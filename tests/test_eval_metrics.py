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


def test_llm_only_and_jev_only_baselines():
    llm = evaluate(RECORDS, "llm_only", JevThresholds())
    assert llm["recall"]["k"] == 4 and llm["calls_saved"] == 0
    jev = evaluate(RECORDS, "jev_only", JevThresholds())
    assert [m["id"] for m in jev["missed"]] == ["MED:3"]  # 'escalate' counts as kept
    assert jev["calls_saved"] == 8
    with pytest.raises(ValueError):
        evaluate(RECORDS, "nonsense", JevThresholds())


def test_sweep_respects_constraint_and_recall_is_monotone_in_exclude_threshold():
    rows = sweep(RECORDS)
    assert all(r["exclude_min_confidence"] >= r["min_confidence"] for r in rows)
    for include in INCLUDE_GRID:
        recalls = [r["recall"]["value"] for r in rows if r["min_confidence"] == include]
        assert recalls == sorted(recalls)  # rows are ordered by ascending exclude threshold


def test_recommend_picks_most_calls_saved_meeting_target():
    rows = sweep(RECORDS)
    best = recommend(rows, target=0.98)
    assert best["recall"]["value"] == 1.0
    assert best["exclude_min_confidence"] >= 0.95  # p=0.03 needs the stricter exclude bar
    assert all(r["calls_saved"] <= best["calls_saved"] for r in rows if r["recall"]["value"] >= 0.98)


def test_recommend_says_none_when_no_pair_meets_target():
    rows = sweep([rec(1, "include", 0.5, llm="exclude")])
    assert recommend(rows, target=0.98) is None
