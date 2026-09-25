import pytest

from research_agent.eval.metrics import rate, wilson


def test_wilson_known_values():
    low, high = wilson(40, 40)
    assert low == pytest.approx(0.912, abs=2e-3)
    assert high == pytest.approx(1.0, abs=1e-9)
    low, high = wilson(0, 10)
    assert low == pytest.approx(0.0, abs=1e-9)
    assert high == pytest.approx(0.277, abs=2e-3)


def test_wilson_zero_trials_is_none():
    assert wilson(0, 0) is None


def test_rate_carries_interval_and_handles_zero_denominator():
    r = rate(36, 40)
    assert r["value"] == 0.9 and (r["k"], r["n"]) == (36, 40)
    assert r["ci"][0] < 0.9 < r["ci"][1]
    empty = rate(0, 0)
    assert empty["value"] is None and empty["ci"] is None and "zero" in empty["reason"]
