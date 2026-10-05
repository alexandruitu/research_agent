"""Pure evaluation metrics: no I/O, no network, no models."""

import math
from itertools import product

from ..jev import JevThresholds, decide_from_probabilities

Z95 = 1.959964


def wilson(k, n, z=Z95):
    """Wilson score interval for k successes in n trials; None when n == 0."""
    if n == 0:
        return None
    p = k / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (max(0.0, centre - half), min(1.0, centre + half))


def rate(k, n):
    """k of n with a Wilson interval. A zero denominator gives value None plus a reason, never 100%."""
    if n == 0:
        return {"k": k, "n": n, "value": None, "ci": None, "reason": "zero denominator"}
    return {"k": k, "n": n, "value": k / n, "ci": wilson(k, n), "reason": None}


def _check_pairs(a, b):
    if len(a) != len(b) or not a:
        raise ValueError("kappa needs two equal-length, non-empty label lists")


def cohen_kappa(a, b):
    """Cohen's kappa for two raters. Reports raw agreement and prevalence, because kappa collapses
    when one class dominates. Single-class input gives kappa None plus a reason."""
    _check_pairs(a, b)
    n = len(a)
    labels = sorted(set(a) | set(b), key=str)
    observed = sum(x == y for x, y in zip(a, b, strict=True)) / n
    expected = sum((a.count(label) / n) * (b.count(label) / n) for label in labels)
    result = {
        "n": n,
        "agreement": observed,
        "prevalence": {label: (a.count(label) + b.count(label)) / (2 * n) for label in labels},
    }
    if expected == 1:
        return {**result, "kappa": None, "reason": "single class: kappa undefined"}
    return {**result, "kappa": (observed - expected) / (1 - expected), "reason": None}


def weighted_kappa(a, b, levels=range(5)):
    """Quadratic-weighted kappa for ordinal scores (default 0..4)."""
    _check_pairs(a, b)
    levels = list(levels)
    k = len(levels)
    if k < 2:
        raise ValueError("weighted kappa needs at least two levels")
    if not set(a) <= set(levels) or not set(b) <= set(levels):
        raise ValueError(f"scores must all be in levels {levels}")
    index = {value: i for i, value in enumerate(levels)}
    n = len(a)
    observed = [[0.0] * k for _ in range(k)]
    for x, y in zip(a, b, strict=True):
        observed[index[x]][index[y]] += 1 / n
    rows = [sum(r) for r in observed]
    cols = [sum(observed[i][j] for i in range(k)) for j in range(k)]
    num = den = 0.0
    for i, j in product(range(k), repeat=2):
        weight = ((i - j) / (k - 1)) ** 2
        num += weight * observed[i][j]
        den += weight * rows[i] * cols[j]
    result = {
        "n": n,
        "agreement": sum(x == y for x, y in zip(a, b, strict=True)) / n,
        "prevalence": {
            level: (a.count(level) + b.count(level)) / (2 * n) for level in levels if level in a or level in b
        },
    }
    if den == 0:
        return {**result, "kappa": None, "reason": "single class: kappa undefined"}
    return {**result, "kappa": 1 - num / den, "reason": None}


INCLUDE_GRID = [round(i / 10, 1) for i in range(1, 10)]
EXCLUDE_GRID = [0.5, 0.6, 0.7, 0.8, 0.9, 0.95, 0.99]
STRATEGIES = ("llm_only", "jev_only", "cascade")


def cascade_decision(probabilities, llm_decision, thresholds):
    """The shipped cascade: a confident Jev verdict decides, otherwise the LLM screen does."""
    verdict = decide_from_probabilities(probabilities, thresholds)
    return (verdict, "jev") if verdict != "escalate" else (llm_decision, "llm")


def _decide(record, strategy, thresholds):
    if strategy == "llm_only":
        return record["llm"], "llm"
    if strategy == "jev_only":
        return decide_from_probabilities(record["probabilities"], thresholds), "jev"
    if strategy == "cascade":
        return cascade_decision(record["probabilities"], record["llm"], thresholds)
    raise ValueError(f"unknown strategy {strategy!r}")


def evaluate(records, strategy, thresholds):
    """Recall on SR-included papers plus workload. 'Kept' means not excluded, as in the pipeline."""
    decided = [(r, *_decide(r, strategy, thresholds)) for r in records]
    positives = [r for r in records if r["label"] == "include"]
    missed = [
        {"id": r["id"], "title": r["title"], "probabilities": r["probabilities"], "decision": d, "tier": t}
        for r, d, t in decided
        if r["label"] == "include" and d == "exclude"
    ]
    # Positives this strategy excludes although llm_only would keep them: the regression the pipeline must avoid.
    lost = (
        []
        if strategy == "llm_only"
        else [
            {"id": r["id"], "title": r["title"], "probabilities": r["probabilities"], "tier": t}
            for r, d, t in decided
            if r["label"] == "include" and d == "exclude" and r["llm"] != "exclude"
        ]
    )
    n = len(records)
    kept = [r for r, d, _t in decided if d != "exclude"]
    if strategy == "llm_only":
        auto_include = auto_exclude = 0
        escalated, calls_saved = n, 0
    else:
        verdicts = [decide_from_probabilities(r["probabilities"], thresholds) for r in records]
        auto_include, auto_exclude = verdicts.count("include"), verdicts.count("exclude")
        escalated = verdicts.count("escalate")
        calls_saved = n if strategy == "jev_only" else n - escalated
    return {
        "recall": rate(len(positives) - len(missed), len(positives)),
        "missed": missed,
        "lost_vs_llm": lost,
        "auto_include": auto_include,
        "auto_exclude": auto_exclude,
        "escalated": escalated,
        "calls_saved": calls_saved,
        # Downstream cost: kept papers go on to extraction and both reviewers.
        "kept": len(kept),
        "kept_negatives": sum(r["label"] == "not_included" for r in kept),
    }


def sweep(records, includes=INCLUDE_GRID, excludes=EXCLUDE_GRID):
    """Cascade outcome for every allowed threshold pair (exclude must be >= include: recall first)."""
    rows = []
    for include, exclude in product(includes, excludes):
        if exclude < include:
            continue
        out = evaluate(records, "cascade", JevThresholds(include, exclude))
        rows.append(
            {
                "min_confidence": include,
                "exclude_min_confidence": exclude,
                "recall": out["recall"],
                "missed": len(out["missed"]),
                "lost_vs_llm": len(out["lost_vs_llm"]),
                "lost_ids": [m["id"] for m in out["lost_vs_llm"]],
                "calls_saved": out["calls_saved"],
                "auto_include": out["auto_include"],
                "auto_exclude": out["auto_exclude"],
                "escalated": out["escalated"],
                "kept": out["kept"],
                "kept_negatives": out["kept_negatives"],
            }
        )
    return rows


def recommend(rows, target=None, other_rows=None):
    """Admissible = loses no SR-included paper that llm_only keeps (`lost_vs_llm == 0`) on `rows` and, when
    given, on `other_rows` (the same threshold pair; a pair missing there is not admissible), and, only
    when `target` is set, point-estimate recall >= target on `rows`. Rank: most calls saved (summed over
    both row sets), then fewer missed, then the stricter include, then the stricter exclude threshold.
    None when nothing is admissible: never silently pick the 'least bad' pair."""
    other = None
    if other_rows is not None:
        other = {(r["min_confidence"], r["exclude_min_confidence"]): r for r in other_rows}
    candidates = []
    for r in rows:
        if r["lost_vs_llm"] != 0:
            continue
        if target is not None and (r["recall"]["value"] is None or r["recall"]["value"] < target):
            continue
        partner = None
        if other is not None:
            partner = other.get((r["min_confidence"], r["exclude_min_confidence"]))
            if partner is None or partner["lost_vs_llm"] != 0:
                continue
        saved = r["calls_saved"] + (partner["calls_saved"] if partner else 0)
        missed = r["missed"] + (partner["missed"] if partner else 0)
        candidates.append(((-saved, missed, -r["min_confidence"], -r["exclude_min_confidence"]), r))
    return min(candidates, key=lambda c: c[0])[1] if candidates else None


# --- Panel evaluation metrics (slice 6). Pure functions: label lists in, dicts out. ---------------------


def fleiss_kappa(units):
    """Fleiss' kappa. `units`: one list of labels per rated unit, every unit rated by the same number (>= 2)
    of raters. Raw agreement (mean pairwise agreement per unit) and prevalence are always reported; kappa is
    None with a reason when only one class occurs."""
    if not units:
        raise ValueError("fleiss kappa needs at least one unit")
    m = len(units[0])
    if m < 2 or any(len(u) != m for u in units):
        raise ValueError("fleiss kappa needs the same number (>= 2) of ratings per unit")
    labels = sorted({label for u in units for label in u}, key=str)
    n = len(units)
    agreement = sum((sum(u.count(c) ** 2 for c in labels) - m) / (m * (m - 1)) for u in units) / n
    prevalence = {c: sum(u.count(c) for u in units) / (n * m) for c in labels}
    expected = sum(p * p for p in prevalence.values())
    result = {"n": n, "raters": m, "agreement": agreement, "prevalence": prevalence}
    if expected == 1:
        return {**result, "kappa": None, "reason": "single class: kappa undefined"}
    return {**result, "kappa": (agreement - expected) / (1 - expected), "reason": None}


def pairwise_cohen(labels_by_rater):
    """{rater: [labels]} (aligned) -> {"a|b": cohen_kappa(...)} for every pair, in sorted key order."""
    keys = sorted(labels_by_rater)
    return {
        f"{a}|{b}": cohen_kappa(labels_by_rater[a], labels_by_rater[b])
        for i, a in enumerate(keys)
        for b in keys[i + 1 :]
    }


def unit_agreement(answers, answered=("yes", "no")):
    """Per-item agreement over papers. `answers`: one {rater: answer} dict per paper. Only raters with an
    answer in `answered` count. Share = papers where >= 2 raters answered and all agree / such papers.
    Kappa: Cohen for two raters, Fleiss for more, over papers where every rater answered; None otherwise."""
    rated = [{r: a for r, a in unit.items() if a in answered} for unit in answers]
    multi = [u for u in rated if len(u) >= 2]
    share = rate(sum(len(set(u.values())) == 1 for u in multi), len(multi))
    raters = sorted({r for unit in answers for r in unit})
    full = [u for u in rated if len(u) == len(raters)]
    kappa = None
    if len(raters) < 2:
        reason = "single answerer: agreement undefined"
    elif not full:
        reason = "no paper answered by every rater"
    elif len(raters) == 2:
        kappa = cohen_kappa([u[raters[0]] for u in full], [u[raters[1]] for u in full])
        reason = kappa["reason"]
    else:
        kappa = fleiss_kappa([[u[r] for r in raters] for u in full])
        reason = kappa["reason"]
    return {"answerers": raters, "share": share, "kappa": kappa, "reason": reason}


def auc(positive_scores, negative_scores):
    """Mann-Whitney AUC (ties count 1/2) with a Hanley-McNeil 95% interval clamped to [0, 1]. None with a
    reason when a class is empty. Hanley-McNeil is closed form (no resampling, no seed); with the small
    samples of a panel eval a bootstrap would be unstable and give a degenerate interval when A = 1."""
    n1, n2 = len(positive_scores), len(negative_scores)
    if not n1 or not n2:
        return {"value": None, "ci": None, "n_pos": n1, "n_neg": n2, "reason": "needs both classes"}
    wins = sum((p > q) + 0.5 * (p == q) for p in positive_scores for q in negative_scores)
    a = wins / (n1 * n2)
    q1, q2 = a / (2 - a), 2 * a * a / (1 + a)
    variance = (a * (1 - a) + (n1 - 1) * (q1 - a * a) + (n2 - 1) * (q2 - a * a)) / (n1 * n2)
    half = Z95 * math.sqrt(max(variance, 0.0))
    return {
        "value": a,
        "ci": (max(0.0, a - half), min(1.0, a + half)),
        "n_pos": n1,
        "n_neg": n2,
        "method": "hanley-mcneil",
        "reason": None,
    }


def _ranks(values):
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        for k in range(i, j + 1):
            ranks[order[k]] = (i + j) / 2 + 1
        i = j + 1
    return ranks


def spearman(x, y):
    """Spearman's rho (average ranks for ties). None with a reason for n < 3 or a constant variable."""
    if len(x) != len(y):
        raise ValueError("spearman needs two equal-length lists")
    n = len(x)
    if n < 3:
        return {"n": n, "rho": None, "reason": "needs at least 3 pairs"}
    rx, ry = _ranks(x), _ranks(y)
    mx, my = sum(rx) / n, sum(ry) / n
    sxy = sum((a - mx) * (b - my) for a, b in zip(rx, ry, strict=True))
    sxx, syy = sum((a - mx) ** 2 for a in rx), sum((b - my) ** 2 for b in ry)
    if sxx == 0 or syy == 0:
        return {"n": n, "rho": None, "reason": "constant ranks: correlation undefined"}
    return {"n": n, "rho": sxy / math.sqrt(sxx * syy), "reason": None}


def dispersion(scores):
    """Spread of reviewer scores for one paper (None scores ignored)."""
    values = [s for s in scores if s is not None]
    if not values:
        return {"n": 0, "range": None, "sd": None}
    mean = sum(values) / len(values)
    sd = math.sqrt(sum((v - mean) ** 2 for v in values) / len(values))
    return {"n": len(values), "range": max(values) - min(values), "sd": sd}


def majority(labels):
    """Most frequent label; a tie for first place (or no labels) gives 'uncertain'."""
    if not labels:
        return "uncertain"
    counts = {label: labels.count(label) for label in labels}
    top = max(counts.values())
    winners = [label for label, c in counts.items() if c == top]
    return winners[0] if len(winners) == 1 else "uncertain"


def compare_to_full(full, subset):
    """Ablation comparison over shared papers. `full`/`subset`: {paper id: {"score", "verdict", "flags"
    (set of flag keys), "editor" (verdict or None), "cost": {"calls", "chars"}}}."""
    ids = sorted(full)
    changed = sum(full[p]["verdict"] != subset[p]["verdict"] for p in ids)
    edited = [p for p in ids if full[p].get("editor") and subset[p].get("editor")]
    flags_full = sum(len(full[p]["flags"]) for p in ids)
    missed = sum(len(full[p]["flags"] - subset[p]["flags"]) for p in ids)
    deltas = [
        abs(full[p]["score"] - subset[p]["score"])
        for p in ids
        if full[p]["score"] is not None and subset[p]["score"] is not None
    ]
    cost_full = {k: sum(full[p]["cost"][k] for p in ids) for k in ("calls", "chars")}
    cost_sub = {k: sum(subset[p]["cost"][k] for p in ids) for k in ("calls", "chars")}
    return {
        "papers": len(ids),
        "verdict_changed": rate(changed, len(ids)),
        "editor_verdict_changed": (
            rate(sum(full[p]["editor"] != subset[p]["editor"] for p in edited), len(edited))
            if edited
            else None
        ),
        "red_flags_missed": rate(missed, flags_full),
        "mean_abs_score_delta": sum(deltas) / len(deltas) if deltas else None,
        "scored_pairs": len(deltas),
        "cost": cost_sub,
        "cost_delta": {
            k: (cost_sub[k] - cost_full[k]) / cost_full[k] if cost_full[k] else None
            for k in ("calls", "chars")
        },
    }
