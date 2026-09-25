"""Run reviewers A and B (and the adjudicator on disagreement) over a gold sample."""

import json
import random
from pathlib import Path

from ..graph import disagreement
from ..schemas import Decision, Evidence, Review
from .gold import gold_paper


def sample_papers(gold, limit, seed=0):
    """All positives with an abstract plus `limit` seeded-random negatives with an abstract."""
    positives = [c for c in gold.candidates if c.label == "include" and c.abstract]
    negatives = sorted(
        (c for c in gold.candidates if c.label != "include" and c.abstract), key=lambda c: c.id
    )
    picked = random.Random(seed).sample(negatives, min(limit, len(negatives)))
    return positives + sorted(picked, key=lambda c: c.id)


def run_agreement(gold, run_dir, evaluator, limit=40, seed=0):
    """Same payloads as the pipeline graph, so cached calls are shared. Errors propagate (fail closed)."""
    papers = {}
    for candidate in sample_papers(gold, limit, seed):
        paper = gold_paper(candidate, gold).model_dump()
        evidence = evaluator.ask("extract", Evidence, {"paper": paper}).model_dump()
        payload = {"topic": gold.topic, "paper": paper, "evidence": evidence}
        a = evaluator.ask("review_a", Review, payload).model_dump()
        b = evaluator.ask("review_b", Review, payload).model_dump()
        adjudicated = disagreement(a, b)
        if adjudicated:
            evaluator.ask("adjudicate", Decision, {**payload, "reviews": [a, b]})
        papers[candidate.id] = {
            "label": candidate.label,
            "review_a": a,
            "review_b": b,
            "adjudicated": adjudicated,
        }
    path = Path(run_dir) / "agreement.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"seed": seed, "limit": limit, "papers": papers}, ensure_ascii=False, indent=2)
    )
    return path
