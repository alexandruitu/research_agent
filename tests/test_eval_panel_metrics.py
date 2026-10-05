import pytest

from research_agent.eval.metrics import (
    auc,
    compare_to_full,
    dispersion,
    fleiss_kappa,
    majority,
    pairwise_cohen,
    spearman,
    unit_agreement,
)

# Fleiss (1971) worked example as given on Wikipedia: 10 subjects, 14 raters, 5 categories, kappa 0.210.
COUNTS = [
    [0, 0, 0, 0, 14],
    [0, 2, 6, 4, 2],
    [0, 0, 3, 5, 6],
    [0, 3, 9, 2, 0],
    [2, 2, 8, 1, 1],
    [7, 7, 0, 0, 0],
    [3, 2, 6, 3, 0],
    [2, 5, 3, 2, 2],
    [6, 5, 2, 1, 0],
    [0, 2, 2, 3, 7],
]


def test_fleiss_known_value():
    units = [[c for c, k in enumerate(row) for _ in range(k)] for row in COUNTS]
    out = fleiss_kappa(units)
    assert out["kappa"] == pytest.approx(0.20993, abs=1e-4)
    assert out["agreement"] == pytest.approx(0.37802, abs=1e-4)
    assert out["prevalence"][0] == pytest.approx(0.143, abs=1e-3)
    assert out["n"] == 10 and out["raters"] == 14


@pytest.mark.parametrize(
    "units, kappa, reason",
    [
        ([["a", "a"], ["a", "a"]], None, "single class: kappa undefined"),
        ([["a", "a"], ["b", "b"]], 1.0, None),
        ([["a", "b"], ["b", "a"]], -1.0, None),
    ],
)
def test_fleiss_defined_and_undefined(units, kappa, reason):
    out = fleiss_kappa(units)
    assert out["kappa"] == (pytest.approx(kappa) if kappa is not None else None)
    assert out["reason"] == reason


@pytest.mark.parametrize("units", [[], [["a"]], [["a", "b"], ["a"]]])
def test_fleiss_rejects_bad_shapes(units):
    with pytest.raises(ValueError):
        fleiss_kappa(units)


def test_pairwise_cohen_matrix():
    out = pairwise_cohen({"c": ["y", "n"], "a": ["y", "n"], "b": ["y", "y"]})
    assert list(out) == ["a|b", "a|c", "b|c"]
    assert out["a|c"]["kappa"] == pytest.approx(1.0)
    assert out["a|b"]["agreement"] == pytest.approx(0.5)


def test_unit_agreement_two_raters_and_single_answerer():
    papers = [{"a": "yes", "b": "yes"}, {"a": "no", "b": "no"}, {"a": "yes", "b": "not_reported"}]
    out = unit_agreement(papers)
    assert out["share"]["k"] == 2 and out["share"]["n"] == 2
    assert out["kappa"]["kappa"] == pytest.approx(1.0)
    single = unit_agreement([{"a": "yes"}, {"a": "no"}])
    assert single["kappa"] is None and single["reason"] == "single answerer: agreement undefined"
    assert single["share"]["value"] is None


def test_unit_agreement_three_raters_uses_fleiss():
    papers = [{"a": "yes", "b": "yes", "c": "no"}, {"a": "no", "b": "no", "c": "no"}]
    out = unit_agreement(papers)
    assert out["kappa"]["raters"] == 3 and out["share"]["k"] == 1


def test_auc_known_value_and_hanley_mcneil_ci():
    out = auc([3, 4], [1, 2, 3])
    assert out["value"] == pytest.approx(5.5 / 6)
    se = 0.16089986
    assert out["ci"][0] == pytest.approx(5.5 / 6 - 1.959964 * se, abs=1e-6)
    assert out["ci"][1] == 1.0  # clamped
    assert out["method"] == "hanley-mcneil"
    assert auc([1], [])["value"] is None


def test_spearman_known_value_with_ties():
    assert spearman([1, 2, 3, 4, 5], [5, 6, 7, 8, 7])["rho"] == pytest.approx(8 / 95**0.5)
    assert spearman([1, 2], [1, 2])["rho"] is None
    assert spearman([1, 1, 1], [1, 2, 3])["reason"] == "constant ranks: correlation undefined"


def test_dispersion_and_majority():
    assert dispersion([50, None, 70]) == {"n": 2, "range": 20, "sd": pytest.approx(10.0)}
    assert dispersion([None])["range"] is None
    assert majority(["include", "include", "exclude"]) == "include"
    assert majority(["include", "exclude"]) == "uncertain"
    assert majority([]) == "uncertain"


def test_compare_to_full():
    full = {
        "p1": {
            "score": 80,
            "verdict": "include",
            "flags": {"x", "y"},
            "editor": "include",
            "cost": {"calls": 4, "chars": 400},
        },
        "p2": {
            "score": 40,
            "verdict": "exclude",
            "flags": set(),
            "editor": None,
            "cost": {"calls": 4, "chars": 400},
        },
    }
    sub = {
        "p1": {
            "score": 70,
            "verdict": "include",
            "flags": {"x"},
            "editor": "exclude",
            "cost": {"calls": 2, "chars": 200},
        },
        "p2": {
            "score": None,
            "verdict": "uncertain",
            "flags": set(),
            "editor": None,
            "cost": {"calls": 2, "chars": 200},
        },
    }
    out = compare_to_full(full, sub)
    assert out["verdict_changed"]["value"] == 0.5
    assert out["red_flags_missed"]["k"] == 1 and out["red_flags_missed"]["n"] == 2
    assert out["mean_abs_score_delta"] == 10 and out["scored_pairs"] == 1
    assert out["editor_verdict_changed"]["value"] == 1.0
    assert out["cost_delta"] == {"calls": -0.5, "chars": -0.5}
