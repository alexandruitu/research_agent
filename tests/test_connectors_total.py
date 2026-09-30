"""Source-reported totals and raw (keyword-built) queries, against responses recorded once from the public
APIs (tests/fixtures/*_total.*, two results each)."""

import json
from pathlib import Path

import httpx
import pytest

from research_agent import connectors
from research_agent.connectors import ArXiv, DemoConnector, EuropePMC, MultiSource, OpenAlex
from research_agent.schemas import Years
from research_agent.storage import Store

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(autouse=True)
def no_backoff(monkeypatch):
    monkeypatch.setattr(connectors.time, "sleep", lambda _s: None)


def recording(body):
    requests = []

    def handler(request):
        requests.append(request)
        if isinstance(body, dict):
            return httpx.Response(200, json=body)
        return httpx.Response(200, text=body)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    client.requests = requests
    return client


def test_europepmc_reports_hit_count(tmp_path):
    client = recording(json.loads((FIXTURES / "europepmc_total.json").read_text()))
    query = 'TITLE_ABS:"coronary angiography" AND TITLE_ABS:"deep learning"'
    result = EuropePMC(Store(tmp_path), client, years=Years(start=2020)).search_with_total(query, 2, raw=True)
    assert result.total == 258 and len(result.papers) == 2
    assert result.query == f"({query}) AND (PUB_YEAR:[2020 TO 9999])"
    assert client.requests[0].url.params["query"] == result.query


def test_europepmc_without_hit_count_reports_none(tmp_path):
    client = recording({"resultList": {"result": []}})
    assert EuropePMC(Store(tmp_path), client).search_with_total("x", 2).total is None


def test_openalex_raw_query_goes_to_the_title_and_abstract_filter(tmp_path):
    client = recording(json.loads((FIXTURES / "openalex_total.json").read_text()))
    query = '"coronary angiography" AND "deep learning"'
    search = OpenAlex(Store(tmp_path), client, years=Years(start=2019, end=2024), contact="a@b.org")
    result = search.search_with_total(query, 2, raw=True)
    assert result.total == 491 and len(result.papers) == 2
    params = client.requests[0].url.params
    assert "search" not in params
    assert params["filter"] == (
        f"title_and_abstract.search:{query},from_publication_date:2019-01-01,to_publication_date:2024-12-31"
    )
    assert result.query == params["filter"] and params["mailto"] == "a@b.org"
    assert "a@b.org" not in json.dumps([p.model_dump() for p in result.papers])


def test_openalex_planned_query_is_unchanged(tmp_path):
    client = recording(json.loads((FIXTURES / "openalex_total.json").read_text()))
    result = OpenAlex(Store(tmp_path), client).search_with_total("ffr ct", 2)
    assert (
        client.requests[0].url.params["search"] == "ffr ct" and "filter" not in client.requests[0].url.params
    )
    assert result.query == "ffr ct"


def test_arxiv_raw_query_is_sent_as_built_plus_years(tmp_path):
    client = recording((FIXTURES / "arxiv_total.xml").read_text())
    query = 'abs:"coronary angiography" AND (cat:cs.CV OR cat:eess.IV)'
    result = ArXiv(Store(tmp_path), client, years=Years(start=2021)).search_with_total(query, 2, raw=True)
    assert result.total == 26 and len(result.papers) == 2
    sent = client.requests[0].url.params["search_query"]
    assert sent == f"{query} AND submittedDate:[202101010000 TO 300012312359]" == result.query


def test_search_still_returns_papers_only(tmp_path):
    client = recording((FIXTURES / "arxiv_total.xml").read_text())
    papers = ArXiv(Store(tmp_path), client).search("coronary angiography", 2)
    assert isinstance(papers, list) and len(papers) == 2
    assert client.requests[0].url.params["search_query"].startswith("all:coronary AND all:angiography")


def test_demo_total_is_what_it_returns(tmp_path):
    result = DemoConnector(Store(tmp_path), source="openalex").search_with_total("x", 3, raw=True)
    assert result.total == 3 and result.query == "x" and len(result.papers) == 3


class Fake:
    def __init__(self, name):
        self.name, self.calls = name, []

    def search(self, query, limit, raw=False):
        self.calls.append((query, limit, raw))
        return []


def test_multisource_splits_raw_and_planned_sources():
    a, b = Fake("europepmc"), Fake("openalex")
    multi = MultiSource([(a, 5), (b, 7)], raw={"openalex": "built"})
    multi.search("planned", 12)
    multi.search_raw()
    assert a.calls == [("planned", 5, False)]
    assert b.calls == [("built", 7, True)]
    assert multi.planned
    assert not MultiSource([(b, 7)], raw={"openalex": "q"}).planned
    assert MultiSource([(a, 5)]).search_raw() == []
