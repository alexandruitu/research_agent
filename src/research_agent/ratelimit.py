"""Per-source request rates: one token bucket per rate bucket, shared by every thread of the process.

Rates are requests per second taken from each API's documented limits (docs/architecture.md, Sources); a source
with an optional key gets its keyed rate only when the key is present. Unknown sources are not limited."""

import threading
import time

# bucket: (requests/second without key, with key)
RATES = {
    "europepmc": (10, 10),
    "openalex": (10, 10),
    "semantic_scholar": (1, 1),
    "crossref": (5, 5),
    "pubmed": (3, 10),
    "core": (1 / 6, 1 / 6),
    "ieee": (2, 2),
    "springer": (1, 1),
    "elsevier": (5, 5),
    "unpaywall": (5, 5),
}
# Sources that share another source's bucket (same host or same provider limit).
BUCKETS = {
    "medrxiv": "europepmc",
    "biorxiv": "europepmc",
    "pmc_oa": "europepmc",
    "scopus": "elsevier",
    "sciencedirect": "elsevier",
    "springer_oa": "springer",
    "semantic_scholar_oa": "semantic_scholar",
}


class TokenBucket:
    """`rate` tokens per second, at most `burst` (default max(1, rate)) saved; acquire() waits for one token."""

    def __init__(self, rate, burst=None, clock=time.monotonic, sleep=None):
        self.rate = float(rate)
        self.capacity = float(burst or max(1.0, self.rate))
        self.tokens = self.capacity
        self.clock = clock
        self.sleep = sleep
        self.updated = clock()
        self.lock = threading.Lock()

    def acquire(self):
        with self.lock:
            now = self.clock()
            self.tokens = min(self.capacity, self.tokens + (now - self.updated) * self.rate)
            self.updated = now
            self.tokens -= 1  # reserved now; a negative balance is the wait of this caller
            wait = -self.tokens / self.rate if self.tokens < 0 else 0.0
        if wait > 0:
            (self.sleep or time.sleep)(wait)
        return wait


_lock = threading.Lock()
_buckets = {}


def bucket_name(source):
    return BUCKETS.get(source, source)


def rate(source, keyed=False):
    rates = RATES.get(bucket_name(source))
    return None if rates is None else rates[1 if keyed else 0]


def limiter(source, keyed=False):
    """The shared bucket of a source (None when the source has no documented limit here)."""
    name = bucket_name(source)
    if name not in RATES:
        return None
    with _lock:
        key = (name, bool(keyed))
        if key not in _buckets:
            _buckets[key] = TokenBucket(rate(source, keyed))
        return _buckets[key]


def reset():
    """Forget every bucket (tests)."""
    with _lock:
        _buckets.clear()
