from research_agent.web.security import RateLimiter, hash_password, new_token, token_hash, verify_password


def test_password_hash_roundtrip_and_wrong_password():
    hashed = hash_password("correct horse battery")
    assert hashed != "correct horse battery" and hashed.startswith("$argon2id$")
    assert verify_password(hashed, "correct horse battery") is True
    assert verify_password(hashed, "wrong") is False
    assert verify_password("not-a-hash", "x") is False


def test_tokens_are_random_and_hashed_deterministically():
    a, b = new_token(), new_token()
    assert a != b and len(a) >= 40
    assert token_hash(a) == token_hash(a) and token_hash(a) != token_hash(b) and len(token_hash(a)) == 64


def test_rate_limiter_blocks_after_max_attempts_and_recovers():
    now = [1000.0]
    limiter = RateLimiter(max_attempts=3, window_seconds=60, clock=lambda: now[0])
    for _ in range(3):
        assert limiter.allowed("k")
        limiter.record_failure("k")
    assert not limiter.allowed("k")
    assert limiter.allowed("other")
    now[0] += 61
    assert limiter.allowed("k")


def test_rate_limiter_success_clears_failures():
    limiter = RateLimiter(max_attempts=2, window_seconds=60, clock=lambda: 0.0)
    limiter.record_failure("k")
    limiter.record_success("k")
    limiter.record_failure("k")
    assert limiter.allowed("k")


def test_rate_limiter_forgets_expired_keys():
    now = [0.0]
    limiter = RateLimiter(max_attempts=3, window_seconds=60, clock=lambda: now[0])
    for i in range(100):
        limiter.record_failure(f"one-off-{i}")
    now[0] += 61
    assert limiter.allowed("one-off-0")
    for i in range(100):
        limiter.allowed(f"one-off-{i}")
    assert limiter.failures == {}
