"""Shared token buckets, Retry-After, identification and secret-safe failures of connectors.fetch."""

import threading
from datetime import UTC, datetime, timedelta
from email.utils import format_datetime

import httpx
import pytest

from research_agent import connectors, ratelimit
from research_agent.connectors import SourceKeyMissing, SourceUnavailable, fetch
from research_agent.ratelimit import TokenBucket


class FakeClock:
    def __init__(self):
        self.now = 0.0
        self.slept = []
        self.lock = threading.Lock()

    def clock(self):
        return self.now

    def sleep(self, seconds):
        with self.lock:
            self.slept.append(seconds)


@pytest.fixture(autouse=True)
def fresh(monkeypatch):
    ratelimit.reset()
    slept = []
    monkeypatch.setattr(connectors.time, "sleep", slept.append)
    yield slept
    ratelimit.reset()


def client(*responses):
    requests = []
    queue = list(responses)

    def handler(request):
        requests.append(request)
        return queue.pop(0) if len(queue) > 1 else queue[0]

    http = httpx.Client(transport=httpx.MockTransport(handler))
    http.requests = requests
    return http


def test_bucket_allows_a_burst_then_spaces_requests():
    fake = FakeClock()
    bucket = TokenBucket(2, clock=fake.clock, sleep=fake.sleep)
    waits = [bucket.acquire() for _ in range(4)]
    assert waits == [0.0, 0.0, 0.5, 1.0]
    assert fake.slept == [0.5, 1.0]


def test_bucket_refills_with_time():
    fake = FakeClock()
    bucket = TokenBucket(1, clock=fake.clock, sleep=fake.sleep)
    bucket.acquire()
    fake.now = 1.0
    assert bucket.acquire() == 0.0


def test_bucket_is_shared_across_threads():
    fake = FakeClock()
    bucket = TokenBucket(4, clock=fake.clock, sleep=fake.sleep)
    threads = [threading.Thread(target=bucket.acquire) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    # 4 tokens of burst, then 4 more at 0.25 s spacing: waits 0.25, 0.5, 0.75, 1.0
    assert sorted(fake.slept) == [0.25, 0.5, 0.75, 1.0]


def test_limiter_registry_returns_one_bucket_per_bucket_and_key_state():
    assert ratelimit.limiter("medrxiv") is ratelimit.limiter("europepmc")
    assert ratelimit.limiter("pubmed") is not ratelimit.limiter("pubmed", keyed=True)
    assert ratelimit.limiter("pubmed").rate == 3 and ratelimit.limiter("pubmed", keyed=True).rate == 10
    assert ratelimit.limiter("scopus") is ratelimit.limiter("sciencedirect")
    assert ratelimit.limiter("nowhere") is None


def test_fetch_acquires_the_source_bucket_per_attempt(monkeypatch):
    taken = []
    monkeypatch.setattr(ratelimit.TokenBucket, "acquire", lambda self: taken.append(self.rate))
    http = client(httpx.Response(503), httpx.Response(200, json={"ok": 1}))
    assert fetch(http, "https://x.test/", None, "crossref", lambda r: r.json()) == {"ok": 1}
    assert taken == [5, 5]


def test_retry_after_seconds_is_respected(fresh):
    http = client(httpx.Response(429, headers={"Retry-After": "7"}), httpx.Response(200, json={}))
    fetch(http, "https://x.test/", None, "crossref", lambda r: r.json())
    assert fresh == [7.0]


def test_retry_after_http_date_is_respected(fresh):
    when = format_datetime(datetime.now(UTC) + timedelta(seconds=30), usegmt=True)
    http = client(httpx.Response(503, headers={"Retry-After": when}), httpx.Response(200, json={}))
    fetch(http, "https://x.test/", None, "crossref", lambda r: r.json())
    assert len(fresh) == 1 and 25 <= fresh[0] <= 30


def test_retry_after_above_cap_fails_closed_at_once(fresh):
    http = client(httpx.Response(429, headers={"Retry-After": "3600"}))
    with pytest.raises(SourceUnavailable):
        fetch(http, "https://x.test/", None, "crossref", lambda r: r.json())
    assert len(http.requests) == 1 and fresh == []


def test_without_retry_after_backoff_is_one_then_two_seconds(fresh):
    http = client(httpx.Response(500))
    with pytest.raises(SourceUnavailable):
        fetch(http, "https://x.test/", None, "crossref", lambda r: r.json())
    assert fresh == [1, 2] and len(http.requests) == 3


def test_user_agent_carries_the_contact(monkeypatch):
    monkeypatch.delenv("RESEARCH_AGENT_CONTACT", raising=False)
    http = client(httpx.Response(200, json={}))
    fetch(http, "https://x.test/", None, "crossref", lambda r: r.json(), contact="me@lab.org")
    assert http.requests[0].headers["User-Agent"] == "research-agent/0.1 (+mailto:me@lab.org)"
    assert connectors.user_agent() == "research-agent/0.1"


def test_user_agent_contact_from_environment(monkeypatch):
    monkeypatch.setenv("RESEARCH_AGENT_CONTACT", "ops@lab.org")
    assert connectors.user_agent() == "research-agent/0.1 (+mailto:ops@lab.org)"


def test_headers_are_sent_and_secret_failures_do_not_chain():
    http = client(httpx.Response(403))
    with pytest.raises(SourceUnavailable) as info:
        fetch(
            http,
            "https://x.test/",
            {"apikey": "SENTINEL"},
            "ieee",
            lambda r: r.json(),
            headers={"X-Key": "SENTINEL"},
            secret=True,
        )
    assert http.requests[0].headers["X-Key"] == "SENTINEL"
    assert info.value.__cause__ is None and info.value.__suppress_context__
    assert "SENTINEL" not in repr(info.value) and "SENTINEL" not in str(info.value)


def test_source_key_missing_message_names_the_variable():
    exc = SourceKeyMissing("core", "CORE_API_KEY")
    assert isinstance(exc, SourceUnavailable)
    assert exc.source == "core" and exc.env_var == "CORE_API_KEY"
    assert str(exc) == exc.message == "core: set CORE_API_KEY in the worker environment"
    assert SourceUnavailable("arxiv").message == "arxiv"


def test_env_key_ignores_blank_values(monkeypatch):
    monkeypatch.setenv("S2_API_KEY", "  ")
    assert connectors.env_key("S2_API_KEY") is None
    monkeypatch.setenv("S2_API_KEY", "k")
    assert connectors.env_key("S2_API_KEY") == "k"
