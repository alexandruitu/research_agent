"""Cross-source identity: DOI normalization, cross-id dedup, Crossref DOI enrichment (no network)."""

import json
from pathlib import Path

import httpx
import pytest

from research_agent import connectors, ratelimit
from research_agent.connectors import MultiSource, SourceUnavailable, deduplicate, domain_connector
from research_agent.schemas import DomainSpec, Paper, Source
from research_agent.sources import CrossrefEnricher
from research_agent.storage import Store

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(autouse=True)
def quiet(monkeypatch):
    monkeypatch.setattr(connectors.time, "sleep", lambda _s: None)
    monkeypatch.setattr(ratelimit.TokenBucket, "acquire", lambda self: 0.0)


def paper(pid, source, title="Title", year="2022", abstract="a", **ids):
    return Paper(
        id=pid,
        title=title,
        abstract=abstract,
        year=year,
        sources=[source],
        provenance=[
            Source(connector=source, record_id=pid, url=pid, query="q", retrieved_at="r", raw_sha256="h")
        ],
        **ids,
    )


def test_dois_are_normalized_before_matching():
    merged = deduplicate(
        [
            paper("a:1", "a", title="One", doi="https://doi.org/10.1/ABC"),
            paper("b:1", "b", title="Two", doi="doi:10.1/abc"),
        ]
    )
    assert len(merged) == 1 and merged[0].doi == "10.1/abc"


def test_pubmed_and_europepmc_merge_by_pmid():
    merged = deduplicate(
        [paper("MED:123", "europepmc", title="A"), paper("pubmed:123", "pubmed", title="B", pmid="123")]
    )
    assert len(merged) == 1 and merged[0].sources == ["europepmc", "pubmed"] and merged[0].pmid == "123"


def test_s2_and_arxiv_merge_by_arxiv_id_and_keep_every_id():
    merged = deduplicate(
        [
            paper("arxiv:2103.01234", "arxiv", title="Preprint title"),
            paper(
                "semantic_scholar:abc",
                "semantic_scholar",
                title="Journal title",
                arxiv="2103.01234",
                s2="abc",
                doi="10.1/j",
                pmid="9",
            ),
        ]
    )
    assert len(merged) == 1
    only = merged[0]
    assert (only.arxiv, only.s2, only.doi, only.pmid) == ("2103.01234", "abc", "10.1/j", "9")


def test_pmcid_merges():
    merged = deduplicate(
        [paper("PMC:PMC7", "europepmc", title="X"), paper("core:1", "core", title="Y", pmcid="PMC7")]
    )
    assert len(merged) == 1 and merged[0].pmcid == "PMC7"


def test_conflicting_dois_never_merge_by_cross_id():
    merged = deduplicate(
        [
            paper("pubmed:5", "pubmed", pmid="5", doi="10.1/a"),
            paper("scopus:9", "scopus", pmid="5", doi="10.1/b"),
        ]
    )
    assert len(merged) == 2


def test_existing_ids_are_not_added_to_dumps():
    merged = deduplicate(
        [paper("MED:1", "europepmc", doi="10.1/x"), paper("openalex:W1", "openalex", doi="10.1/x")]
    )
    assert not {"pmid", "arxiv", "s2"} & set(merged[0].model_dump())


def crossref_client(body):
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json=body)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    client.requests = requests
    return client


WORKS = json.loads((FIXTURES / "crossref_works.json").read_text())
TITLE = WORKS["message"]["items"][0]["title"][0]


def test_enricher_fills_the_doi_on_exact_title_and_year(tmp_path):
    client = crossref_client(WORKS)
    enricher = CrossrefEnricher(Store(tmp_path), client, contact="me@lab.org")
    out = enricher.enrich([paper("arxiv:1", "arxiv", title=TITLE.upper() + "!", year="2026")])
    assert out[0].doi == "10.2139/ssrn.6218070"
    params = client.requests[0].url.params
    assert params["filter"] == "from-pub-date:2026,until-pub-date:2026" and params["rows"] == "3"
    assert params["mailto"] == "me@lab.org"


@pytest.mark.parametrize("title,year", [(TITLE + " revisited", "2026"), (TITLE, "2025")])
def test_enricher_rejects_near_titles_and_other_years(tmp_path, title, year):
    out = CrossrefEnricher(Store(tmp_path), crossref_client(WORKS)).enrich(
        [paper("x:1", "x", title=title, year=year)]
    )
    assert out[0].doi == ""


def test_enricher_skips_papers_with_a_doi_or_without_title_or_year(tmp_path):
    client = crossref_client(WORKS)
    CrossrefEnricher(Store(tmp_path), client).enrich(
        [paper("a", "a", doi="10.1/x"), paper("b", "b", title=" "), paper("c", "c", year="")]
    )
    assert client.requests == []


def test_enricher_is_bounded(tmp_path):
    client = crossref_client(WORKS)
    papers = [paper(f"x:{i}", "x", title=f"Title {i}") for i in range(60)]
    CrossrefEnricher(Store(tmp_path), client).enrich(papers)
    assert len(client.requests) == CrossrefEnricher.MAX_LOOKUPS == 50


def test_enricher_caches_lookups(tmp_path):
    store = Store(tmp_path)
    client = crossref_client(WORKS)
    for _ in range(2):
        CrossrefEnricher(store, client).enrich([paper("x:1", "x", title=TITLE, year="2026")])
    assert len(client.requests) == 1
    with store.connect() as db:
        assert db.execute("SELECT source FROM lookups").fetchall() == [("crossref",)]


def test_enricher_failure_fails_closed(tmp_path):
    def handler(request):
        return httpx.Response(500)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    with pytest.raises(SourceUnavailable):
        CrossrefEnricher(Store(tmp_path), client).enrich([paper("x:1", "x")])


def domain(*names):
    return DomainSpec.model_validate(
        {
            "schema": 1,
            "topic": "coronary angiography",
            "criteria": {"include": [{"key": "i1", "text": "about angiography"}]},
            "sources": [{"name": n} for n in names],
        }
    )


def test_enrichment_only_with_crossref_in_live_mode(tmp_path):
    store = Store(tmp_path)
    assert domain_connector(domain("europepmc", "crossref"), store, "live").enricher is not None
    assert domain_connector(domain("europepmc"), store, "live").enricher is None
    assert domain_connector(domain("europepmc", "crossref"), store, "demo").enricher is None
    papers = [paper("x:1", "x")]
    assert MultiSource([]).enrich(papers) is papers


def test_normalize_calls_the_enricher_before_dedup(tmp_path, monkeypatch):
    from research_agent import runner
    from research_agent.connectors import DemoConnector
    from research_agent.schemas import Contract

    class Enriching(MultiSource):
        def enrich(self, papers):  # every demo paper gets the same DOI: dedup must then merge them
            return [p.model_copy(update={"doi": "10.9/same"}) for p in papers]

    spec = domain("europepmc")
    monkeypatch.setattr(
        runner, "make_connector", lambda c, store: Enriching([(DemoConnector(store, "europepmc"), 3)])
    )
    result = runner.run_research(tmp_path / "run", Contract(topic=spec.topic, domain=spec, max_papers=3))
    assert [p["doi"] for p in result["papers"]] == ["10.9/same"]
