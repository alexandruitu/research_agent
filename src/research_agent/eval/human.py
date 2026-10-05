"""Human reference ratings vs the panel. Input: human_ratings.json in a panel eval folder (written by the
web backend, or passed with `research-eval human --ratings`). Offline; scores use the panel's own code."""

import json
from pathlib import Path
from typing import Literal

from pydantic import Field

from ..schemas import ALIASED, Model
from ..scoring import score_paper
from .metrics import cohen_kappa, fleiss_kappa, rate, spearman

RATINGS_FILE = "human_ratings.json"
Answer = Literal["yes", "no", "unclear", "not_reported"]


class HumanRating(Model):
    paper_id: str
    reviewer: str  # reviewer profile key
    reviewer_version: int = Field(ge=1)
    item: str
    item_text: str  # the wording the rater answered; a reworded item does not reuse old ratings
    rater: str  # opaque rater id (e.g. a web user id)
    answer: Answer
    quote: str = ""


class HumanRatings(Model):
    schema_version: Literal[1] = Field(alias="schema")
    ratings: list[HumanRating]

    model_config = ALIASED


def load_ratings(path):
    return HumanRatings.model_validate(json.loads(Path(path).read_text())).ratings


def consensus(answers):
    """Majority of the raters' answers; a tie for first place gives 'unclear'."""
    counts = {a: answers.count(a) for a in answers}
    top = max(counts.values())
    winners = [a for a, c in counts.items() if c == top]
    return winners[0] if len(winners) == 1 else "unclear"


def _units(review, panel_data, ratings):
    """{(paper, reviewer, item): {rater: answer}} for current wording only; plus the stale-rating count."""
    current = {(r["key"], i["key"]): (r["version"], i["text"]) for r in review["panel"] for i in r["items"]}
    units, stale = {}, 0
    for r in ratings:
        if r.paper_id not in panel_data["papers"]:
            stale += 1
            continue
        if current.get((r.reviewer, r.item)) != (r.reviewer_version, r.item_text):
            stale += 1
            continue
        units.setdefault((r.paper_id, r.reviewer, r.item), {})[r.rater] = r.answer
    return units, stale


def inter_rater(units):
    """Share of multi-rater units where all raters agree, and Fleiss' kappa over the units that have the
    most common number (>= 2) of raters (Fleiss needs a constant count per unit)."""
    multi = [list(u.values()) for u in units.values() if len(u) >= 2]
    share = rate(sum(len(set(u)) == 1 for u in multi), len(multi))
    if not multi:
        return {"share": share, "fleiss": None, "reason": "no paper item has two or more raters"}
    sizes = [len(u) for u in multi]
    m = max(set(sizes), key=lambda s: (sizes.count(s), s))
    return {"share": share, "fleiss": fleiss_kappa([u for u in multi if len(u) == m]), "reason": None}


def _versus(pairs):
    """pairs: [(panel answer, human consensus)] -> accuracy + Cohen's kappa (None when empty)."""
    if not pairs:
        return {"accuracy": rate(0, 0), "kappa": None}
    return {
        "accuracy": rate(sum(a == b for a, b in pairs), len(pairs)),
        "kappa": cohen_kappa([a for a, _ in pairs], [b for _, b in pairs]),
    }


def compare_human(review, panel_data, ratings):
    units, stale = _units(review, panel_data, ratings)
    papers = panel_data["papers"]
    agreed = {key: consensus(list(u.values())) for key, u in units.items()}
    model = {
        key: {a["key"]: a["answer"] for a in papers[key[0]]["reviews"][key[1]]["answers"]}[key[2]]
        for key in agreed
    }
    texts = {(r["key"], i["key"]): i["text"] for r in review["panel"] for i in r["items"]}
    per_item = []
    for reviewer, item in sorted({(k[1], k[2]) for k in agreed}):
        pairs = [(model[k], agreed[k]) for k in agreed if (k[1], k[2]) == (reviewer, item)]
        per_item.append(
            {
                "reviewer": reviewer,
                "item": item,
                "text": texts[(reviewer, item)],
                "n": len(pairs),
                **_versus(pairs),
            }
        )
    per_reviewer = {
        reviewer: _versus([(model[k], agreed[k]) for k in agreed if k[1] == reviewer])
        for reviewer in sorted({k[1] for k in agreed})
    }
    # Per paper: the human score is the panel's scoring code over consensus answers (unrated items count
    # as not_reported), on the reviewers the humans rated for that paper; compared with the panel's score
    # on the same reviewers.
    scores = []
    for pid in sorted({k[0] for k in agreed}):
        rated = [r for r in review["panel"] if any(k[0] == pid and k[1] == r["key"] for k in agreed)]
        human_reviews = {
            r["key"]: {
                "answers": [
                    {
                        "key": i["key"],
                        "answer": agreed.get((pid, r["key"], i["key"]), "not_reported"),
                        "quote": "",
                        "section": "",
                    }
                    for i in r["items"]
                ]
            }
            for r in rated
        }
        human = score_paper(rated, human_reviews)["score"]
        panel = score_paper(rated, {r["key"]: papers[pid]["reviews"][r["key"]] for r in rated})["score"]
        scores.append(
            {"paper_id": pid, "human": human, "panel": panel, "reviewers": [r["key"] for r in rated]}
        )
    both = [s for s in scores if s["human"] is not None and s["panel"] is not None]
    return {
        "ratings": len(ratings),
        "stale_or_unknown": stale,
        "raters": sorted({r for u in units.values() for r in u}),
        "units": len(units),
        "papers": len({k[0] for k in units}),
        "inter_rater": inter_rater(units),
        "panel": _versus([(model[k], agreed[k]) for k in agreed]),
        "per_reviewer": per_reviewer,
        "per_item": per_item,
        "scores": {
            "papers": scores,
            "spearman": spearman([s["panel"] for s in both], [s["human"] for s in both]),
        },
    }
