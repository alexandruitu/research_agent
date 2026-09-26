"""Password hashing, opaque tokens and a per-process login rate limiter."""

import hashlib
import secrets
import time
from collections import deque

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

_hasher = PasswordHasher()


def hash_password(password):
    return _hasher.hash(password)


def verify_password(hashed, password):
    try:
        return _hasher.verify(hashed, password)
    except (VerificationError, InvalidHashError):
        return False


def new_token():
    return secrets.token_urlsafe(32)


def token_hash(token):
    return hashlib.sha256(token.encode()).hexdigest()


class RateLimiter:
    """Sliding window of failures per key. In-process: with several API processes each keeps its own count.

    Memory is bounded: expired keys are swept at most once per window (on any call), and at most
    `max_keys` keys are kept (the least recently failing are dropped first)."""

    def __init__(self, max_attempts, window_seconds, clock=time.monotonic, max_keys=10_000):
        self.max_attempts, self.window, self.clock = max_attempts, window_seconds, clock
        self.max_keys, self.failures = max_keys, {}
        self._last_sweep = clock()

    def _prune(self, key):
        queue = self.failures.get(key)
        if queue is None:
            return ()
        cutoff = self.clock() - self.window
        while queue and queue[0] <= cutoff:
            queue.popleft()
        if not queue:
            del self.failures[key]  # one-off keys must not accumulate
            return ()
        return queue

    def _sweep(self):
        now = self.clock()
        if now - self._last_sweep < self.window:
            return
        self._last_sweep = now
        for key in list(self.failures):
            self._prune(key)

    def allowed(self, key):
        self._sweep()
        return len(self._prune(key)) < self.max_attempts

    def record_failure(self, key):
        self._sweep()
        self._prune(key)
        queue = self.failures.pop(key, None) or deque()  # re-inserted last: dict order = recency of failure
        queue.append(self.clock())
        self.failures[key] = queue
        while len(self.failures) > self.max_keys:
            del self.failures[next(iter(self.failures))]  # the least recently failing key

    def record_success(self, key):
        self.failures.pop(key, None)
