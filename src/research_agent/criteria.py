"""Per-criterion screening decisions. Models answer each criterion; this code decides (no LLM here).

Inclusion criteria must all hold; any exclusion criterion drops the paper. Inclusion is checked first,
in the field's order, so `decided_by` is the first criterion that failed.
"""


def criterion_keys(criteria):
    return [c["key"] for c in criteria["include"]] + [c["key"] for c in criteria["exclude"]]


def _include(criteria):
    return [c["key"] for c in criteria["include"]]


def _exclude(criteria):
    return [c["key"] for c in criteria["exclude"]]


def decide_jev(probabilities, criteria, thresholds):
    """Jev probabilities -> (include | exclude | escalate, decided_by)."""
    for key in _include(criteria):
        if probabilities[key] <= thresholds["include_fail_max"]:
            return "exclude", key
    for key in _exclude(criteria):
        if probabilities[key] >= thresholds["exclude_hit_min"]:
            return "exclude", key
    if all(probabilities[k] >= thresholds["keep_min"] for k in _include(criteria)) and all(
        probabilities[k] <= thresholds["exclude_clear_max"] for k in _exclude(criteria)
    ):
        return "include", None
    return "escalate", None


def decide_llm(answers, criteria):
    """LLM answers {key: yes | no | unclear} -> (include | exclude | uncertain, decided_by)."""
    for key in _include(criteria):
        if answers[key] == "no":
            return "exclude", key
    for key in _exclude(criteria):
        if answers[key] == "yes":
            return "exclude", key
    if all(answers[k] == "yes" for k in _include(criteria)) and all(
        answers[k] == "no" for k in _exclude(criteria)
    ):
        return "include", None
    return "uncertain", None


def screen_payload(domain, paper):
    """The LLM screen payload; shared by the pipeline and research-eval so cache keys match."""
    return {"topic": domain["topic"], "criteria": domain["criteria"], "paper": paper}


def satisfied(probabilities, criteria):
    """Probability that each criterion is *satisfied* (exclusion criteria inverted), for the eval sweep."""
    excluded = set(_exclude(criteria))
    return {k: round(1 - p, 12) if k in excluded else p for k, p in probabilities.items()}
