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


from pathlib import Path

from research_agent.connectors import OpenAlex, rebuild_abstract

FIXTURES = Path(__file__).parent / "fixtures"
# Recorded 2026-09-28: GET https://api.openalex.org/works?search=CT%20fractional%20flow%20reserve%20deep%20learning
# &filter=from_publication_date:2018-01-01&per-page=3&select=id,doi,title,publication_year,abstract_inverted_index
OPENALEX = json.loads((FIXTURES / "openalex_works.json").read_text())


def test_rebuild_abstract_orders_words_by_position():
    assert rebuild_abstract({"b": [1], "a": [0, 2]}) == "a b a"
    assert rebuild_abstract(None) == "" and rebuild_abstract({}) == ""


def test_openalex_parses_recorded_works(tmp_path):
    store = Store(tmp_path)
    first, second = OpenAlex(store, recording(OPENALEX)).search("ct ffr", 2)
    assert first.id == "openalex:W2807965844" and first.year == "2018"
    assert first.doi == "10.1161/circimaging.117.007217"
    assert first.title.startswith("Diagnostic Accuracy of a Machine-Learning Approach")
    assert first.abstract.startswith(
        "Background: Coronary computed tomographic angiography (CTA) is a reliable"
    )
    assert first.abstract.endswith("performs equally well as CFD-based CT-FFR.")
    assert first.sources == ["openalex"]
    assert first.provenance[0].url == "https://openalex.org/W2807965844"
    assert first.provenance[0].connector == "openalex"
    assert second.id == "openalex:W4281259955" and second.abstract == ""
    with store.connect() as db:
        raw = db.execute("SELECT payload FROM raw WHERE hash=?", (first.provenance[0].raw_sha256,)).fetchone()
    assert json.loads(raw[0])["results"][0]["id"] == "https://openalex.org/W2807965844"


def test_openalex_request_parameters(tmp_path):
    client = recording(OPENALEX)
    OpenAlex(Store(tmp_path), client, years=Years(start=2018, end=2024), contact="team@example.org").search(
        "ct ffr", 500
    )
    OpenAlex(Store(tmp_path), client).search("ct ffr", 20)
    with_all, plain_request = (r.url.params for r in client.requests)
    assert with_all["search"] == "ct ffr" and with_all["per-page"] == "200"
    assert with_all["filter"] == "from_publication_date:2018-01-01,to_publication_date:2024-12-31"
    assert with_all["mailto"] == "team@example.org"
    assert with_all["select"] == "id,doi,title,publication_year,abstract_inverted_index"
    assert (
        "filter" not in plain_request and "mailto" not in plain_request and plain_request["per-page"] == "20"
    )


@pytest.mark.parametrize(
    "status,body", [(500, OPENALEX), (200, {"meta": {}}), (200, {"results": [{"title": "x"}]})]
)
def test_openalex_failures_fail_closed(tmp_path, status, body):
    with pytest.raises(SourceUnavailable, match="openalex"):
        OpenAlex(Store(tmp_path), recording(body, status=status)).search("q", 2)


from research_agent.connectors import ArXiv

ARXIV = (FIXTURES / "arxiv_query.xml").read_text()
ARXIV_ERROR = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom"><entry><id>http://arxiv.org/api/errors#incorrect_id_format</id>
<title>Error</title><summary>incorrect id format</summary></entry></feed>"""


def test_arxiv_query_uses_words_categories_and_dates(tmp_path):
    arxiv = ArXiv(Store(tmp_path), years=Years(start=2018))
    assert arxiv.search_query('"deep learning" AND (FFR OR CT-FFR)') == (
        "all:deep AND all:learning AND all:FFR AND all:CT-FFR"
        " AND (cat:cs.CV OR cat:eess.IV OR cat:physics.med-ph)"
        " AND submittedDate:[201801010000 TO 300012312359]"
    )
    assert ArXiv(Store(tmp_path)).search_query("a b c d e f g h i j") == (
        "all:a AND all:b AND all:c AND all:d AND all:e AND all:f AND all:g AND all:h"
        " AND (cat:cs.CV OR cat:eess.IV OR cat:physics.med-ph)"
    )


def test_arxiv_parses_recorded_entries_and_caches_the_atom_text(tmp_path):
    store = Store(tmp_path)
    client = recording(ARXIV)
    first, second = ArXiv(store, client).search("fractional flow reserve", 500)
    assert client.requests[0].url.params["max_results"] == "200"
    assert client.requests[0].url.params["start"] == "0"
    assert first.id == "arxiv:1805.11472" and first.year == "2018" and first.doi == ""
    assert first.title == "Comparison of 1D and 3D Models for the Estimation of Fractional Flow Reserve"
    assert first.abstract.startswith("In this work we propose to validate the predictive capabilities")
    assert "  " not in first.abstract and "\n" not in first.abstract
    assert first.sources == ["arxiv"] and first.provenance[0].url == "https://arxiv.org/abs/1805.11472"
    assert second.id == "arxiv:2308.04923" and second.year == "2023"
    with store.connect() as db:
        raw = db.execute("SELECT payload FROM raw WHERE hash=?", (first.provenance[0].raw_sha256,)).fetchone()
    assert json.loads(raw[0]) == {"atom": ARXIV}


def test_arxiv_waits_three_seconds_between_requests(tmp_path):
    waits = []
    arxiv = ArXiv(Store(tmp_path), recording(ARXIV), sleep=waits.append)
    arxiv.search("a", 1)
    arxiv.search("b", 1)
    assert waits == [3]


@pytest.mark.parametrize("status,body", [(503, ARXIV), (200, ARXIV_ERROR), (200, "<feed><entry>")])
def test_arxiv_failures_fail_closed(tmp_path, status, body):
    with pytest.raises(SourceUnavailable, match="arxiv"):
        ArXiv(Store(tmp_path), recording(body, status=status)).search("q", 2)
