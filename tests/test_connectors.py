import json

import httpx
import pytest
from eval_helpers import row

from research_agent import connectors
from research_agent.connectors import DemoConnector, EuropePMC, SourceUnavailable
from research_agent.schemas import Years
from research_agent.storage import Store


@pytest.fixture(autouse=True)
def no_backoff(monkeypatch):
    monkeypatch.setattr(connectors.time, "sleep", lambda _s: None)


def recording(payload, status=200):
    requests = []

    def handler(request):
        requests.append(request)
        body = payload(request) if callable(payload) else payload
        return httpx.Response(status, **({"json": body} if isinstance(body, dict) else {"text": body}))

    client = httpx.Client(transport=httpx.MockTransport(handler))
    client.requests = requests
    return client


def epmc(rows):
    return {"resultList": {"result": rows}}


def test_europepmc_year_filter_is_sent_and_recorded(tmp_path):
    client = recording(epmc([row(1)]))
    papers = EuropePMC(Store(tmp_path), client, years=Years(start=2018)).search("ffr", 5)
    sent = client.requests[0].url.params["query"]
    assert sent == "(ffr) AND (PUB_YEAR:[2018 TO 9999])"
    assert papers[0].provenance[0].query == sent
    assert papers[0].sources == ["europepmc"]
    bounded = recording(epmc([]))
    EuropePMC(Store(tmp_path), bounded, years=Years(start=2018, end=2020)).search("ffr", 5)
    assert bounded.requests[0].url.params["query"] == "(ffr) AND (PUB_YEAR:[2018 TO 2020])"


def test_europepmc_without_years_sends_the_query_unchanged(tmp_path):
    client = recording(epmc([row(1)]))
    EuropePMC(Store(tmp_path), client).search("ffr", 5)
    EuropePMC(Store(tmp_path), client, years=Years()).search("ffr", 5)
    assert [r.url.params["query"] for r in client.requests] == ["ffr", "ffr"]


@pytest.mark.parametrize("status,attempts", [(400, 1), (503, 3), (429, 3)])
def test_http_failures_raise_source_unavailable_after_the_same_retries(tmp_path, status, attempts):
    client = recording(epmc([]), status=status)
    with pytest.raises(SourceUnavailable) as info:
        EuropePMC(Store(tmp_path), client).search("q", 2)
    assert info.value.source == "europepmc" and str(info.value) == "europepmc"
    assert len(client.requests) == attempts


def test_transport_errors_are_retried_then_fail_closed(tmp_path):
    calls = []

    def handler(request):
        calls.append(request)
        raise httpx.ConnectError("down")

    with pytest.raises(SourceUnavailable):
        EuropePMC(Store(tmp_path), httpx.Client(transport=httpx.MockTransport(handler))).search("q", 2)
    assert len(calls) == 3


@pytest.mark.parametrize(
    "body", [{"unexpected": 1}, {"resultList": {"result": [{"title": "no id"}]}}, "not json"]
)
def test_malformed_responses_fail_closed(tmp_path, body):
    with pytest.raises(SourceUnavailable):
        EuropePMC(Store(tmp_path), recording(body)).search("q", 2)


def test_demo_connector_names_its_source(tmp_path):
    store = Store(tmp_path)
    assert DemoConnector(store).search("q", 1)[0].sources == ["demo"]
    assert DemoConnector(store, source="openalex").search("q", 1)[0].sources == ["openalex"]


def test_raw_payload_is_cached_before_parsing(tmp_path):
    store = Store(tmp_path)
    paper = EuropePMC(store, recording(epmc([row(7)]))).search("q", 1)[0]
    with store.connect() as db:
        raw = db.execute("SELECT payload FROM raw WHERE hash=?", (paper.provenance[0].raw_sha256,)).fetchone()
    assert json.loads(raw[0])["resultList"]["result"][0]["id"] == "7"
