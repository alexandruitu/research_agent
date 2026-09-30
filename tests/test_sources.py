"""New search sources against fixtures (no network).

Recorded once from the public APIs (2026-09-30, trimmed): crossref_works.json (GET api.crossref.org/works?
query.bibliographic=deep+learning+coronary+angiography&rows=2&filter=from-pub-date:2020), pubmed_esearch.json
and pubmed_efetch.xml (E-utilities, reference lists removed), europepmc_preprints.json (Europe PMC search with
SRC:PPR AND PUBLISHER:"medRxiv").

Hand-written from the providers' documented response examples (no key was used or read):
- s2_search.json: https://api.semanticscholar.org/api-docs/graph#tag/Paper-Data/operation/get_graph_paper_relevance_search
  (the unauthenticated pool answered 429 to three recording attempts)
- core_search.json: https://api.core.ac.uk/docs/v3#tag/Search
- ieee_search.json: https://developer.ieee.org/docs/read/Metadata_API_responses
- springer_meta.json: https://dev.springernature.com/docs/api-endpoints/meta-api/
- scopus_search.json, scopus_empty.json: https://dev.elsevier.com/documentation/ScopusSearchAPI.wadl
"""

import json
from pathlib import Path

import httpx
import pytest

from research_agent import connectors, ratelimit
from research_agent.connectors import SourceKeyMissing, SourceUnavailable, domain_connector
from research_agent.schemas import SEARCH_SOURCES, DomainSpec, Years
from research_agent.sources import (
    IEEE,
    REGISTRY,
    Core,
    Crossref,
    Preprints,
    PubMed,
    Scopus,
    SemanticScholar,
    Springer,
)
from research_agent.storage import Store

FIXTURES = Path(__file__).parent / "fixtures"
KEYS = (
    "S2_API_KEY",
    "NCBI_API_KEY",
    "CORE_API_KEY",
    "IEEE_API_KEY",
    "SPRINGER_API_KEY",
    "ELSEVIER_API_KEY",
    "ELSEVIER_INSTTOKEN",
    "OPENALEX_API_KEY",
    "RESEARCH_AGENT_CONTACT",
)


@pytest.fixture(autouse=True)
def isolated(monkeypatch):
    monkeypatch.setattr(connectors.time, "sleep", lambda _s: None)
    monkeypatch.setattr(ratelimit.TokenBucket, "acquire", lambda self: 0.0)
    for key in KEYS:
        monkeypatch.delenv(key, raising=False)


def load(name):
    text = (FIXTURES / name).read_text()
    return json.loads(text) if name.endswith(".json") else text


def recording(*bodies):
    """Answers with the bodies in order (the last one repeats)."""
    requests, queue = [], list(bodies)

    def handler(request):
        requests.append(request)
        body = queue.pop(0) if len(queue) > 1 else queue[0]
        if isinstance(body, httpx.Response):
            return body
        if isinstance(body, dict | list):
            return httpx.Response(200, json=body)
        return httpx.Response(200, text=body)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    client.requests = requests
    return client


KW = {"all": ["deep learning"], "any": ["coronary"], "none": []}


# Registry


def test_registry_covers_every_search_source_and_resolver():
    from research_agent.schemas import FULLTEXT_SOURCES

    searchable = {n for n, i in REGISTRY.items() if "search" in i.capabilities}
    assert searchable == set(SEARCH_SOURCES)
    resolvers = {r for i in REGISTRY.values() for r in i.resolvers}
    assert resolvers == set(FULLTEXT_SOURCES) - {"upload"}
    assert {i.group for i in REGISTRY.values()} == {
        "biomedical",
        "preprints",
        "multidisciplinary",
        "publishers",
        "identity",
    }


def test_registry_auth_matches_env_vars_and_rates():
    required = {n: i.env[0] for n, i in REGISTRY.items() if i.auth == "required"}
    assert required == {
        "core": "CORE_API_KEY",
        "ieee": "IEEE_API_KEY",
        "springer": "SPRINGER_API_KEY",
        "scopus": "ELSEVIER_API_KEY",
        "sciencedirect": "ELSEVIER_API_KEY",
    }
    optional = {n: i.env for n, i in REGISTRY.items() if i.auth == "optional"}
    assert optional == {
        "pubmed": ("NCBI_API_KEY",),
        "openalex": ("OPENALEX_API_KEY",),
        "semantic_scholar": ("S2_API_KEY",),
    }
    assert REGISTRY["pubmed"].rps == 3 and REGISTRY["pubmed"].rps_keyed == 10
    assert REGISTRY["medrxiv"].rps == 10 and all(i.max_results == 100 for i in REGISTRY.values())
    assert all(i.auth in ("none", "optional", "required") for i in REGISTRY.values())


# Semantic Scholar


def test_s2_parses_every_identifier(tmp_path):
    client = recording(load("s2_search.json") | {"next": None})
    result = SemanticScholar(Store(tmp_path), client).search_with_total("deep learning coronary", 10)
    assert result.total == 1843 and len(result.papers) == 2 and result.note is None
    first, second = result.papers
    assert first.id == "semantic_scholar:649def34f8be52c8b66281af98ae884c09aef38b"
    assert first.doi == "10.1016/j.media.2021.102021" and first.pmid == "33657462"
    assert first.pmcid == "PMC8012345" and first.s2 == "649def34f8be52c8b66281af98ae884c09aef38b"
    assert first.sources == ["semantic_scholar"] and first.year == "2021"
    assert first.provenance[0].url.startswith("https://www.semanticscholar.org/paper/")
    assert second.arxiv == "2103.01234" and second.abstract == "" and second.doi == ""


def test_s2_sends_years_fields_and_the_optional_key_header(tmp_path, monkeypatch):
    client = recording(load("s2_search.json") | {"next": None})
    search = SemanticScholar(Store(tmp_path), client, years=Years(start=2020))
    result = search.search_with_total("q", 5)
    request = client.requests[0]
    assert request.url.params["year"] == "2020-" and request.url.params["limit"] == "5"
    assert "openAccessPdf" in request.url.params["fields"] and "x-api-key" not in request.headers
    assert result.query == "q [year 2020-]"
    monkeypatch.setenv("S2_API_KEY", "k-s2")
    search.search_with_total("q", 5)
    assert client.requests[1].headers["x-api-key"] == "k-s2"


def test_s2_pages_up_to_max_results(tmp_path):
    page = load("s2_search.json")
    client = recording(page | {"next": 100}, page | {"next": 200})
    papers = SemanticScholar(Store(tmp_path), client).search("q", 150)
    offsets = [(r.url.params["offset"], r.url.params["limit"]) for r in client.requests]
    assert offsets == [("0", "100"), ("100", "50")] and len(papers) == 4


def test_s2_raw_filters_locally_and_reports_the_api_total_with_a_note(tmp_path):
    client = recording(load("s2_search.json") | {"next": None})
    search = SemanticScholar(Store(tmp_path), client, keywords=KW)
    result = search.search_with_total("deep learning coronary", 10, raw=True)
    assert [p.s2 for p in result.papers] == ["649def34f8be52c8b66281af98ae884c09aef38b"]
    assert result.total == 1843 and "filtered locally" in result.note


# Crossref


def test_crossref_parses_and_strips_jats(tmp_path):
    result = Crossref(Store(tmp_path), recording(load("crossref_works.json"))).search_with_total("q", 2)
    assert result.total == 2079088 and len(result.papers) == 2
    paper = result.papers[0]
    assert paper.id == "crossref:10.2139/ssrn.6218070" and paper.doi == "10.2139/ssrn.6218070"
    assert paper.year == "2026" and "<jats" not in paper.abstract and paper.abstract.startswith("Background")
    assert paper.provenance[0].url == "https://doi.org/10.2139/ssrn.6218070"


def test_crossref_sends_mailto_filter_and_rows(tmp_path):
    client = recording(load("crossref_works.json"))
    search = Crossref(Store(tmp_path), client, years=Years(start=2020, end=2024), contact="me@lab.org")
    result = search.search_with_total("deep learning", 7)
    params = client.requests[0].url.params
    assert params["query.bibliographic"] == "deep learning" and params["rows"] == "7"
    assert params["filter"] == "from-pub-date:2020,until-pub-date:2024" and params["mailto"] == "me@lab.org"
    assert "me@lab.org" in client.requests[0].headers["User-Agent"]
    assert result.query == "deep learning [from-pub-date:2020,until-pub-date:2024]"


# PubMed


def test_pubmed_esearch_then_efetch_parses_ids_and_abstracts(tmp_path):
    client = recording(load("pubmed_esearch.json"), load("pubmed_efetch.xml"))
    result = PubMed(Store(tmp_path), client).search_with_total('"deep learning"[tiab]', 2)
    assert result.total == 281 and [p.pmid for p in result.papers] == ["42765352", "42756380"]
    first, second = result.papers
    assert first.id == "pubmed:42765352" and first.doi == "10.1088/1361-6560/aea2ea" and first.pmcid == ""
    assert second.pmcid == "PMC13582580" and second.doi == "10.3389/fdgth.2026.1847917"
    assert first.abstract and first.title and first.year.isdigit()
    assert first.provenance[0].url == "https://pubmed.ncbi.nlm.nih.gov/42765352/"
    assert client.requests[1].url.params["id"] == "42765352,42756380"


def test_pubmed_sends_tool_email_and_years_in_the_term(tmp_path):
    client = recording(load("pubmed_esearch.json"), load("pubmed_efetch.xml"))
    search = PubMed(Store(tmp_path), client, years=Years(start=2020), contact="me@lab.org")
    result = search.search_with_total("x[tiab]", 2)
    params = client.requests[0].url.params
    assert params["term"] == result.query == "(x[tiab]) AND (2020:3000[dp])"
    assert params["tool"] == "research-agent" and params["email"] == "me@lab.org" and "api_key" not in params


def test_pubmed_key_goes_to_params_and_uses_the_keyed_bucket(tmp_path, monkeypatch):
    monkeypatch.setenv("NCBI_API_KEY", "k-ncbi")
    used = []
    monkeypatch.setattr(ratelimit.TokenBucket, "acquire", lambda self: used.append(self.rate))
    client = recording(load("pubmed_esearch.json"), load("pubmed_efetch.xml"))
    PubMed(Store(tmp_path), client).search("x", 2)
    assert all(r.url.params["api_key"] == "k-ncbi" for r in client.requests) and used == [10, 10]


def test_pubmed_empty_result_makes_no_efetch(tmp_path):
    client = recording({"esearchresult": {"count": "0", "idlist": []}})
    result = PubMed(Store(tmp_path), client).search_with_total("x", 5)
    assert result.papers == [] and result.total == 0 and len(client.requests) == 1


# medRxiv / bioRxiv


@pytest.mark.parametrize("name,server", [("medrxiv", "medRxiv"), ("biorxiv", "bioRxiv")])
def test_preprints_append_the_server_filter_and_years(tmp_path, name, server):
    client = recording(load("europepmc_preprints.json"))
    result = Preprints(Store(tmp_path), name, client, years=Years(start=2025)).search_with_total("q", 2)
    expected = f'((q) AND (SRC:PPR AND PUBLISHER:"{server}")) AND (PUB_YEAR:[2025 TO 9999])'
    assert result.query == client.requests[0].url.params["query"] == expected
    assert result.total == 103 and all(p.sources == [name] for p in result.papers)
    assert result.papers[0].doi == "10.64898/2026.06.30.26356920"


# Key-required sources


def keyed(monkeypatch, **values):
    for name, value in values.items():
        monkeypatch.setenv(name, value)


def test_core_parses_and_sends_bearer_key_and_years(tmp_path, monkeypatch):
    keyed(monkeypatch, CORE_API_KEY="k-core")
    client = recording(load("core_search.json"))
    result = Core(Store(tmp_path), client, years=Years(start=2020, end=2022)).search_with_total('"x"', 2)
    request = client.requests[0]
    assert request.headers["Authorization"] == "Bearer k-core"
    assert request.url.params["q"] == result.query == '("x") AND yearPublished>=2020 AND yearPublished<=2022'
    assert result.total == 57 and [p.id for p in result.papers] == ["core:148473", "core:99001"]
    assert result.papers[0].doi == "10.3390/diagnostics11050789" and result.papers[0].pmid == "33925000"
    assert result.papers[1].arxiv == "2201.00001"


def test_core_pages_up_to_max_results(tmp_path, monkeypatch):
    keyed(monkeypatch, CORE_API_KEY="k")
    page = load("core_search.json") | {"totalHits": 500}
    page["results"] = page["results"] * 50
    client = recording(page)
    papers = Core(Store(tmp_path), client).search("x", 150)
    assert [(r.url.params["offset"], r.url.params["limit"]) for r in client.requests] == [
        ("0", "100"),
        ("100", "50"),
    ]
    assert len(papers) == 150  # never more than max_results, even when a page is longer than asked


def test_ieee_parses_and_sends_apikey_param_and_years(tmp_path, monkeypatch):
    keyed(monkeypatch, IEEE_API_KEY="k-ieee")
    client = recording(load("ieee_search.json"))
    result = IEEE(Store(tmp_path), client, years=Years(start=2021, end=2022)).search_with_total("x", 20)
    params = client.requests[0].url.params
    assert params["apikey"] == "k-ieee" and params["start_year"] == "2021" and params["end_year"] == "2022"
    assert params["max_records"] == "20" and result.total == 12
    assert result.query == "x [start_year 2021] [end_year 2022]"
    assert result.papers[0].id == "ieee:9412345" and result.papers[0].doi == "10.1109/tmi.2021.3060000"


def test_springer_parses_both_abstract_shapes_and_scrubs_the_echoed_key(tmp_path, monkeypatch):
    keyed(monkeypatch, SPRINGER_API_KEY="SPRINGER-KEY-ECHO")
    store = Store(tmp_path)
    client = recording(load("springer_meta.json"))
    result = Springer(store, client, years=Years(start=2021)).search_with_total("x", 10)
    params = client.requests[0].url.params
    assert params["api_key"] == "SPRINGER-KEY-ECHO" and params["q"] == "(x) AND datefrom:2021-01-01"
    assert result.total == 31 and len(result.papers) == 2
    first, second = result.papers
    assert first.abstract == "Objectives: to evaluate deep learning. Results: it worked."
    assert second.abstract == "Plain string abstract." and second.title == "Angiography review"
    assert first.provenance[0].url == "http://link.springer.com/10.1007/s00330-021-07890-1"
    with store.connect() as db:
        dump = " ".join(r[0] for r in db.execute("SELECT payload FROM raw"))
    assert "SPRINGER-KEY-ECHO" not in dump and "apiKey" not in dump


def test_springer_pages_by_25(tmp_path, monkeypatch):
    keyed(monkeypatch, SPRINGER_API_KEY="k")
    page = load("springer_meta.json")
    page["result"][0]["total"] = "100"
    page["records"] = page["records"] * 13  # 26 rows per mocked page
    client = recording(page)
    Springer(Store(tmp_path), client).search("x", 40)
    assert [(r.url.params["s"], r.url.params["p"]) for r in client.requests] == [("1", "25"), ("26", "15")]


def test_scopus_parses_and_sends_headers(tmp_path, monkeypatch):
    keyed(monkeypatch, ELSEVIER_API_KEY="k-els")
    client = recording(load("scopus_search.json"))
    result = Scopus(Store(tmp_path), client, years=Years(start=2020, end=2022)).search_with_total(
        "TITLE(x)", 2
    )
    request = client.requests[0]
    assert request.headers["X-ELS-APIKey"] == "k-els" and "X-ELS-Insttoken" not in request.headers
    assert request.url.params["query"] == "(TITLE(x)) AND PUBYEAR > 2019 AND PUBYEAR < 2023"
    assert result.total == 412 and [p.id for p in result.papers] == [
        "scopus:85100000001",
        "scopus:85100000002",
    ]
    assert result.papers[0].doi == "10.1016/j.jcmg.2021.01.001" and result.papers[0].pmid == "33600000"
    assert result.papers[0].abstract == "" and result.papers[1].abstract.startswith("Complete-view")


def test_scopus_insttoken_is_optional_and_sent_when_present(tmp_path, monkeypatch):
    keyed(monkeypatch, ELSEVIER_API_KEY="k", ELSEVIER_INSTTOKEN="tok")
    client = recording(load("scopus_search.json"))
    Scopus(Store(tmp_path), client).search("x", 2)
    assert client.requests[0].headers["X-ELS-Insttoken"] == "tok"


def test_scopus_empty_result_entry_is_zero_papers(tmp_path, monkeypatch):
    keyed(monkeypatch, ELSEVIER_API_KEY="k")
    result = Scopus(Store(tmp_path), recording(load("scopus_empty.json"))).search_with_total("x", 25)
    assert result.papers == [] and result.total == 0


@pytest.mark.parametrize(
    "cls,env",
    [
        (Core, "CORE_API_KEY"),
        (IEEE, "IEEE_API_KEY"),
        (Springer, "SPRINGER_API_KEY"),
        (Scopus, "ELSEVIER_API_KEY"),
    ],
)
def test_key_required_sources_raise_before_any_request(tmp_path, cls, env):
    client = recording({})
    with pytest.raises(SourceKeyMissing) as info:
        cls(Store(tmp_path), client).search("x", 5)
    assert info.value.env_var == env and env in str(info.value) and client.requests == []


@pytest.mark.parametrize(
    "cls,body",
    [
        (SemanticScholar, {"total": 1}),
        (Crossref, {"message": {"items": [{"title": ["no doi"]}]}}),
        (PubMed, {"nothing": 1}),
        (Core, {"totalHits": 1}),
        (Springer, {"result": [{"total": "1"}]}),
        (Scopus, {"unexpected": 1}),
        (IEEE, {"articles": [{"title": "no number"}]}),
    ],
)
def test_new_sources_fail_closed_on_malformed_bodies(tmp_path, monkeypatch, cls, body):
    keyed(monkeypatch, CORE_API_KEY="k", SPRINGER_API_KEY="k", ELSEVIER_API_KEY="k", IEEE_API_KEY="k")
    with pytest.raises(SourceUnavailable) as info:
        cls(Store(tmp_path), recording(body)).search("x", 5)
    assert not isinstance(info.value, SourceKeyMissing)


def test_pubmed_malformed_xml_fails_closed(tmp_path):
    client = recording(load("pubmed_esearch.json"), "<not-xml")
    with pytest.raises(SourceUnavailable):
        PubMed(Store(tmp_path), client).search("x", 2)


def test_http_errors_fail_closed_after_retries(tmp_path):
    client = recording(httpx.Response(503))
    with pytest.raises(SourceUnavailable):
        Crossref(Store(tmp_path), client).search("x", 2)
    assert len(client.requests) == 3


# Wiring


def domain_with(*names, **extra):
    return DomainSpec.model_validate(
        {
            "schema": 1,
            "topic": "coronary angiography",
            "criteria": {"include": [{"key": "i1", "text": "about angiography"}]},
            "sources": [{"name": n} for n in names],
            "years": {"from": 2020},
            **extra,
        }
    )


def test_domain_connector_builds_every_live_source(tmp_path):
    domain = domain_with(*SEARCH_SOURCES, keywords={"all": ["ct"], "any": [], "none": []})
    multi = domain_connector(domain, Store(tmp_path), "live")
    built = {c.name: type(c).__name__ for c, _ in multi.sources}
    assert built == {
        "europepmc": "EuropePMC",
        "openalex": "OpenAlex",
        "arxiv": "ArXiv",
        "semantic_scholar": "SemanticScholar",
        "crossref": "Crossref",
        "pubmed": "PubMed",
        "medrxiv": "Preprints",
        "biorxiv": "Preprints",
        "core": "Core",
        "ieee": "IEEE",
        "springer": "Springer",
        "scopus": "Scopus",
    }
    s2 = next(c for c, _ in multi.sources if c.name == "semantic_scholar")
    assert s2.keywords == {"all": ["ct"], "any": [], "none": []} and s2.years.start == 2020


def test_domain_connector_demo_covers_every_source_without_network(tmp_path):
    multi = domain_connector(domain_with(*SEARCH_SOURCES), Store(tmp_path), "demo")
    for connector, _ in multi.sources:
        result = connector.search_with_total("q", 2)
        assert [p.sources for p in result.papers] == [[connector.name]] * 2


def test_openalex_key_is_an_optional_param_never_recorded(tmp_path, monkeypatch):
    from research_agent.connectors import OpenAlex

    monkeypatch.setenv("OPENALEX_API_KEY", "k-oa")
    client = recording(load("openalex_total.json"))
    result = OpenAlex(Store(tmp_path), client).search_with_total("x", 2)
    assert client.requests[0].url.params["api_key"] == "k-oa"
    assert "k-oa" not in result.query and all("k-oa" not in p.provenance[0].url for p in result.papers)
