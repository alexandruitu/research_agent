"""Password hashing, opaque tokens and a per-process login rate limiter."""

import hashlib
import secrets
import time
from collections import defaultdict, deque

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
    """Sliding window of failures per key. In-process: with several API processes each keeps its own count."""

    def __init__(self, max_attempts, window_seconds, clock=time.monotonic):
        self.max_attempts, self.window, self.clock = max_attempts, window_seconds, clock
        self.failures = defaultdict(deque)

    def _prune(self, key):
        queue, cutoff = self.failures[key], self.clock() - self.window
        while queue and queue[0] <= cutoff:
            queue.popleft()
        return queue

    def allowed(self, key):
        return len(self._prune(key)) < self.max_attempts

    def record_failure(self, key):
        self._prune(key).append(self.clock())

    def record_success(self, key):
        self.failures.pop(key, None)
