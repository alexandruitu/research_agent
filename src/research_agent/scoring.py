"""Panel scoring, in code: models answer checklist items, code computes score, coverage and red flags."""

SCORE_VERSION = "panel-1"
VERDICT_ORDER = {"include": 0, "uncertain": 1, "exclude": 2}


def score_reviewer(items, answers):
    """answers: {item key: answer dict}. Score over yes/no answers only (weights), None if none answered;
    coverage = answered / items."""
    passed = weighed = answered = 0
    for item in items:
        answer = answers[item["key"]]["answer"]
        if answer in ("yes", "no"):
            answered += 1
            weighed += item["weight"]
            passed += item["weight"] if answer == item.get("pass_if", "yes") else 0
    return {
        "score": round(100 * passed / weighed, 2) if weighed else None,
        "coverage": round(answered / len(items), 4),
        "answered": answered,
        "total": len(items),
    }


FLAG_PREFIX = {"no": "Not met: ", "yes": "Concern: "}


def flag_problem_text(item_text, red_flag_if, flag_text=None):
    """How a raised red flag reads: the item's problem phrasing (flag_text) when set, else the item text with a
    prefix saying what went wrong ("Not met:" for an item answered no, "Concern:" for one answered yes), so a
    flag never reads as the positively phrased item alone."""
    if flag_text and flag_text.strip():
        return flag_text.strip()
    return FLAG_PREFIX.get(red_flag_if, "Concern: ") + item_text


def red_flags(panel, reviews):
    flags = {}
    for reviewer in panel:
        answers = {a["key"]: a for a in reviews[reviewer["key"]]["answers"]}
        for item in reviewer["items"]:
            answer = answers[item["key"]]
            if item.get("red_flag_if") and answer["answer"] == item["red_flag_if"]:
                flag = flags.setdefault(
                    item.get("source") or item["text"],
                    {
                        "text": flag_problem_text(item["text"], item["red_flag_if"], item.get("flag_text")),
                        "item_text": item["text"],
                        "source": item.get("source"),
                        "raised_by": [],
                    },
                )
                flag["raised_by"].append(
                    {
                        "reviewer": reviewer["key"],
                        "item": item["key"],
                        "answer": answer["answer"],
                        "quote": answer["quote"],
                        "section": answer["section"],
                    }
                )
    return list(flags.values())


def score_paper(panel, reviews):
    per = {
        r["key"]: score_reviewer(r["items"], {a["key"]: a for a in reviews[r["key"]]["answers"]})
        for r in panel
    }
    scores = [v["score"] for v in per.values() if v["score"] is not None]
    total = sum(v["total"] for v in per.values())
    return {
        "reviewers": per,
        "score": round(sum(scores) / len(scores), 2) if scores else None,
        "coverage": round(sum(v["answered"] for v in per.values()) / total, 4) if total else 0.0,
        "red_flags": red_flags(panel, reviews),
    }


def rank_panel(review):
    rows = [
        {
            "paper_id": pid,
            "score": r["score"],
            "coverage": r["coverage"],
            "verdict": r["editor"]["verdict"],
            "decision": {"verdict": r["editor"]["verdict"], "reason": r["editor"]["reason"]},
        }
        for pid, r in review.items()
        if r["editor"]["verdict"] != "exclude" and r["score"] is not None
    ]
    return sorted(rows, key=lambda r: (-r["score"], VERDICT_ORDER[r["verdict"]], r["paper_id"]))[:10]
