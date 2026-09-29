import pytest

from research_agent.scoring import rank_panel, score_paper, score_reviewer

ITEMS = [
    {
        "key": "a",
        "text": "Split by patient.",
        "weight": 3,
        "source": "CLAIM 2020 #21",
        "pass_if": "yes",
        "red_flag_if": "no",
    },
    {
        "key": "b",
        "text": "Test set used for tuning.",
        "weight": 2,
        "source": None,
        "pass_if": "no",
        "red_flag_if": "yes",
    },
    {"key": "c", "text": "CIs reported.", "weight": 1, "source": None, "pass_if": "yes", "red_flag_if": None},
    {"key": "d", "text": "Calibration.", "weight": 2, "source": None, "pass_if": "yes", "red_flag_if": None},
]


def answers(**values):
    return {
        k: {"key": k, "answer": v, "quote": f"q{k}" if v in ("yes", "no") else "", "section": ""}
        for k, v in values.items()
    }


@pytest.mark.parametrize(
    ("values", "expected"),
    [
        ({"a": "yes", "b": "no", "c": "yes", "d": "yes"}, (100.0, 1.0)),
        ({"a": "no", "b": "yes", "c": "yes", "d": "unclear"}, (round(100 * 1 / 6, 2), 0.75)),
        ({"a": "yes", "b": "not_reported", "c": "no", "d": "not_reported"}, (75.0, 0.5)),
        ({"a": "unclear", "b": "not_reported", "c": "unclear", "d": "unclear"}, (None, 0.0)),
    ],
)
def test_reviewer_score_table(values, expected):
    result = score_reviewer(ITEMS, answers(**values))
    assert (result["score"], result["coverage"]) == expected


def panel(*keys):
    return [{"key": k, "name": k.title(), "items": ITEMS} for k in keys]


def test_paper_score_is_the_mean_and_red_flags_are_grouped():
    reviews = {
        "m": {"answers": list(answers(a="no", b="yes", c="yes", d="yes").values())},
        "s": {"answers": list(answers(a="no", b="no", c="unclear", d="unclear").values())},
        "x": {"answers": list(answers(a="unclear", b="unclear", c="unclear", d="unclear").values())},
    }
    result = score_paper(panel("m", "s", "x"), reviews)
    assert result["reviewers"]["x"]["score"] is None
    assert result["score"] == round((round(100 * 3 / 8, 2) + 40.0) / 2, 2)
    assert result["coverage"] == round(6 / 12, 4)
    assert result["red_flags"] == [
        {
            "text": "Split by patient.",
            "source": "CLAIM 2020 #21",
            "raised_by": [
                {"reviewer": "m", "item": "a", "answer": "no", "quote": "qa", "section": ""},
                {"reviewer": "s", "item": "a", "answer": "no", "quote": "qa", "section": ""},
            ],
        },
        {
            "text": "Test set used for tuning.",
            "source": None,
            "raised_by": [{"reviewer": "m", "item": "b", "answer": "yes", "quote": "qb", "section": ""}],
        },
    ]


def test_ranking_uses_score_then_editor_verdict_and_skips_excluded_and_unscored():
    review = {
        "p1": {"score": 50.0, "coverage": 0.5, "editor": {"verdict": "uncertain", "reason": "r1"}},
        "p2": {"score": 50.0, "coverage": 0.4, "editor": {"verdict": "include", "reason": "r2"}},
        "p3": {"score": 90.0, "coverage": 1.0, "editor": {"verdict": "exclude", "reason": "r3"}},
        "p4": {"score": None, "coverage": 0.0, "editor": {"verdict": "include", "reason": "r4"}},
        "p5": {"score": 70.0, "coverage": 0.9, "editor": {"verdict": "uncertain", "reason": "r5"}},
    }
    ranking = rank_panel(review)
    assert [r["paper_id"] for r in ranking] == ["p5", "p2", "p1"]
    assert ranking[1] == {
        "paper_id": "p2",
        "score": 50.0,
        "coverage": 0.4,
        "verdict": "include",
        "decision": {"verdict": "include", "reason": "r2"},
    }
    many = {
        f"q{i:02d}": {"score": float(i), "coverage": 1.0, "editor": {"verdict": "include", "reason": ""}}
        for i in range(15)
    }
    assert len(rank_panel(many)) == 10
