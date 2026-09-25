"""Pure evaluation metrics: no I/O, no network, no models."""

import math
from itertools import product

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
    if den == 0:
        return {"n": n, "kappa": None, "reason": "single class: kappa undefined"}
    return {"n": n, "kappa": 1 - num / den, "reason": None}
