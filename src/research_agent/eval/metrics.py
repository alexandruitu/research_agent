"""Pure evaluation metrics: no I/O, no network, no models."""

import math

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
