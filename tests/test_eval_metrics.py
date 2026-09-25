import pytest

from research_agent.eval.metrics import cohen_kappa, rate, weighted_kappa, wilson


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
