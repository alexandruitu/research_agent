import json

import pytest
from test_eval_panel import run

from research_agent.eval.human import HumanRating, compare_human, consensus, inter_rater, load_ratings
from research_agent.eval.panel_eval import load_panel_eval


def rating(paper, reviewer, item, rater, answer, text=None, version=1):
    texts = {
        "shared": "The data split is described.",
        "m1": "methodologist item one.",
        "s1": "statistician item one.",
    }
    return HumanRating(
        paper_id=paper,
        reviewer=reviewer,
        reviewer_version=version,
        item=item,
        item_text=text or texts[item],
        rater=rater,
        answer=answer,
    )


@pytest.mark.parametrize(
    "answers, expected",
    [
        (["yes"], "yes"),
        (["yes", "yes", "no"], "yes"),
        (["yes", "no"], "unclear"),
        (["no", "not_reported", "no"], "no"),
    ],
)
def test_consensus_majority_ties_unclear(answers, expected):
    assert consensus(answers) == expected


def test_inter_rater_share_and_fleiss():
    units = {
        ("p", "r", "a"): {"x": "yes", "y": "yes"},
        ("p", "r", "b"): {"x": "yes", "y": "no"},
        ("p", "r", "c"): {"x": "no"},
    }
    out = inter_rater(units)
    assert out["share"]["k"] == 1 and out["share"]["n"] == 2 and out["fleiss"]["raters"] == 2
    assert inter_rater({("p", "r", "a"): {"x": "yes"}})["fleiss"] is None


def test_compare_human_accuracy_kappa_scores_and_stale(tmp_path):
    _data, eval_dir, _e = run(tmp_path, n=6)
    _manifest, review, panel = load_panel_eval(eval_dir)
    ids = sorted(panel["papers"])  # MED:1..3 included (model says yes), the others excluded (model says no)
    ratings = []
    for pid in ids:
        truth = "yes" if pid in ("MED:1", "MED:2") else "no"  # humans disagree with the model on MED:3
        ratings += [
            rating(pid, "methodologist", "m1", "h1", truth),
            rating(pid, "methodologist", "m1", "h2", truth),
        ]
        ratings += [rating(pid, "methodologist", "shared", "h1", truth)]
    ratings += [rating(ids[0], "methodologist", "m1", "h3", "yes", text="old wording")]  # stale
    ratings += [rating("MED:99", "methodologist", "m1", "h1", "yes")]  # not in the sample
    out = compare_human(review, panel, ratings)
    assert out["stale_or_unknown"] == 2 and out["raters"] == ["h1", "h2"] and out["papers"] == 6
    m1 = next(r for r in out["per_item"] if r["item"] == "m1")
    assert m1["n"] == 6 and m1["accuracy"]["k"] == 5
    assert out["per_reviewer"]["methodologist"]["accuracy"]["n"] == 12
    assert out["panel"]["accuracy"]["k"] == 10  # model yes on 6 of 12, humans on 4: kappa (10/12-.5)/.5
    assert out["panel"]["kappa"]["kappa"] == pytest.approx(2 / 3)
    assert out["inter_rater"]["share"]["value"] == 1.0
    scores = {s["paper_id"]: s for s in out["scores"]["papers"]}
    assert scores["MED:3"]["panel"] == 100.0 and scores["MED:3"]["human"] == 0.0
    assert out["scores"]["spearman"]["n"] == 6


def test_load_ratings_file(tmp_path):
    path = tmp_path / "human_ratings.json"
    path.write_text(json.dumps({"schema": 1, "ratings": [rating("p", "r", "m1", "h", "yes").model_dump()]}))
    assert load_ratings(path)[0].answer == "yes"
    path.write_text(json.dumps({"schema": 1, "ratings": [{"paper_id": "p"}]}))
    with pytest.raises(ValueError):
        load_ratings(path)
