import pytest

from research_agent.criteria import criterion_keys, decide_jev, decide_llm, satisfied, screen_payload

CRITERIA = {
    "include": [{"key": "i1", "text": "Uses ML."}, {"key": "i2", "text": "Uses CT."}],
    "exclude": [{"key": "e1", "text": "Is a review."}],
}
T = {"keep_min": 0.8, "include_fail_max": 0.05, "exclude_hit_min": 0.95, "exclude_clear_max": 0.2}


@pytest.mark.parametrize(
    "p,expected",
    [
        ({"i1": 0.9, "i2": 0.85, "e1": 0.1}, ("include", None)),
        ({"i1": 0.8, "i2": 0.8, "e1": 0.2}, ("include", None)),  # bounds are inclusive
        ({"i1": 0.05, "i2": 0.9, "e1": 0.1}, ("exclude", "i1")),
        ({"i1": 0.9, "i2": 0.01, "e1": 0.99}, ("exclude", "i2")),  # inclusion checked first
        ({"i1": 0.9, "i2": 0.9, "e1": 0.95}, ("exclude", "e1")),
        ({"i1": 0.79, "i2": 0.9, "e1": 0.1}, ("escalate", None)),
        ({"i1": 0.9, "i2": 0.9, "e1": 0.21}, ("escalate", None)),
        ({"i1": 0.06, "i2": 0.9, "e1": 0.94}, ("escalate", None)),
    ],
)
def test_jev_decision_table(p, expected):
    assert decide_jev(p, CRITERIA, T) == expected


@pytest.mark.parametrize(
    "answers,expected",
    [
        ({"i1": "yes", "i2": "yes", "e1": "no"}, ("include", None)),
        ({"i1": "no", "i2": "yes", "e1": "yes"}, ("exclude", "i1")),
        ({"i1": "yes", "i2": "yes", "e1": "yes"}, ("exclude", "e1")),
        ({"i1": "unclear", "i2": "yes", "e1": "no"}, ("uncertain", None)),
        ({"i1": "yes", "i2": "yes", "e1": "unclear"}, ("uncertain", None)),
    ],
)
def test_llm_decision_table(answers, expected):
    assert decide_llm(answers, CRITERIA) == expected


def test_exclusion_only_and_inclusion_only_fields():
    only_exclude = {"include": [], "exclude": [{"key": "e1", "text": "Is a review."}]}
    assert decide_jev({"e1": 0.1}, only_exclude, T) == ("include", None)
    assert decide_llm({"e1": "no"}, only_exclude) == ("include", None)
    only_include = {"include": [{"key": "i1", "text": "Uses ML."}], "exclude": []}
    assert decide_jev({"i1": 0.5}, only_include, T) == ("escalate", None)


def test_keys_payload_and_satisfied():
    assert criterion_keys(CRITERIA) == ["i1", "i2", "e1"]
    domain = {"topic": "t", "criteria": CRITERIA, "sources": [], "thresholds": T}
    paper = {"id": "p", "title": "x", "abstract": "y"}
    assert screen_payload(domain, paper) == {"topic": "t", "criteria": CRITERIA, "paper": paper}
    assert satisfied({"i1": 0.9, "i2": 0.2, "e1": 0.3}, CRITERIA) == {"i1": 0.9, "i2": 0.2, "e1": 0.7}
