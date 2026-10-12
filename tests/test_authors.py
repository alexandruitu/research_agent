"""Authors in the pipeline: each connector's parsing (fixtures, no network), dedup merge, and that authors
never reach a model payload or a cache key."""

import json
from pathlib import Path

import httpx
import pytest

from research_agent import connectors, ratelimit
from research_agent.agents import without_sources
from research_agent.connectors import (
    ArXiv,
    EuropePMC,
    OpenAlex,
    deduplicate,
    make_authors,
    merge_authors,
    normalize_name,
    normalize_orcid,
)
from research_agent.schemas import Paper, Source
from research_agent.sources import Crossref, PubMed, SemanticScholar
from research_agent.storage import Store

FIXTURES = Path(__file__).parent / "fixtures" / "authors"
ORCID = "0000-0002-1825-0097"


@pytest.fixture(autouse=True)
def isolated(monkeypatch):
    monkeypatch.setattr(connectors.time, "sleep", lambda _s: None)
    monkeypatch.setattr(ratelimit.TokenBucket, "acquire", lambda self: 0.0)
    for key in ("S2_API_KEY", "NCBI_API_KEY", "OPENALEX_API_KEY", "RESEARCH_AGENT_CONTACT"):
        monkeypatch.delenv(key, raising=False)


def client(*names):
    bodies = [(FIXTURES / n).read_text() for n in names]
    requests = []

    def handler(request):
        requests.append(request)
        body = bodies.pop(0) if len(bodies) > 1 else bodies[0]
        return httpx.Response(200, text=body)

    http = httpx.Client(transport=httpx.MockTransport(handler))
    http.requests = requests
    return http


def brief(authors):
    return [(a.position, a.name, a.orcid, a.openalex_id, a.affiliations) for a in authors]


def test_openalex_authorships(tmp_path):
    http = client("openalex_works.json")
    [paper] = OpenAlex(Store(tmp_path), http).search("q", 5)
    assert "authorships" in http.requests[0].url.params["select"]
    assert brief(paper.authors) == [
        (1, "Ana Popescu", ORCID, "A5000000001", ["Carol Davila University"]),
        (2, "Jon Smith", "", "A5000000002", ["Some Lab, Oxford"]),  # no institution: the raw string
    ]


def test_europepmc_author_list(tmp_path):
    [paper] = EuropePMC(Store(tmp_path), client("europepmc_core.json")).search("q", 5)
    assert brief(paper.authors) == [
        (1, "Ana Popescu", ORCID, "", ["Carol Davila University, Bucharest"]),
        (2, "Jon Smith", "", "", []),
        (3, "CT-FFR Consortium", "", "", []),
    ]


def test_semantic_scholar_authors_keep_the_s2_id(tmp_path):
    http = client("s2_search.json")
    [paper] = SemanticScholar(Store(tmp_path), http).search("q", 5)
    assert "authors" in http.requests[0].url.params["fields"]
    assert [(a.name, a.s2_id, a.orcid) for a in paper.authors] == [
        ("Ana Popescu", "1741101", ""),
        ("Jon Smith", "", ""),
    ]


def test_crossref_authors(tmp_path):
    http = client("crossref_works.json")
    [paper] = Crossref(Store(tmp_path), http).search("q", 5)
    assert http.requests[0].url.params["select"].endswith(",author")
    assert brief(paper.authors) == [
        (1, "Ana Popescu", ORCID, "", ["Carol Davila University"]),
        (2, "Jon Smith", "", "", []),
        (3, "The CT-FFR Group", "", "", []),
    ]


def test_pubmed_authors(tmp_path):
    [paper] = PubMed(Store(tmp_path), client("pubmed_esearch.json", "pubmed_efetch.xml")).search("q", 5)
    assert brief(paper.authors) == [
        (1, "Ana Popescu", ORCID, "", ["Carol Davila University, Bucharest, Romania."]),
        (2, "Jon Smith", "", "", []),
        (3, "CT-FFR Consortium", "", "", []),
    ]


def test_arxiv_names_and_affiliations(tmp_path):
    [paper] = ArXiv(Store(tmp_path), client("arxiv.xml"), sleep=lambda _s: None).search("q", 5)
    assert brief(paper.authors) == [
        (1, "Ana Popescu", "", "", ["Carol Davila University"]),
        (2, "Jon Smith", "", "", []),
    ]


def test_normalizers():
    assert normalize_orcid("https://orcid.org/0000-0002-1825-009x") == "0000-0002-1825-009X"
    assert normalize_orcid("not an orcid") == ""
    assert normalize_name("  Ánä  POPESCU-Ionescu, Jr. ") == "ana popescu ionescu jr"


def paper(pid, source, authors, doi="10.1/x"):
    return Paper(
        id=pid,
        title="Same work",
        abstract="text",
        year="2024",
        doi=doi,
        sources=[source],
        authors=make_authors(authors),
        provenance=[
            Source(connector=source, record_id=pid, url="u", query="q", retrieved_at="t", raw_sha256="h")
        ],
    )


def test_dedup_keeps_the_richer_list_and_fills_what_it_lacks():
    openalex = paper(
        "openalex:W1",
        "openalex",
        [{"name": "Ana Popescu", "openalex_id": "A1"}, {"name": "Jon Smith", "openalex_id": "A2"}],
    )
    crossref = paper(
        "crossref:10.1/x",
        "crossref",
        [{"name": "Ana Popescu", "orcid": ORCID, "affiliations": ["Carol Davila"]}, {"name": "Jon Smith"}],
    )
    arxiv = paper("arxiv:1", "arxiv", [{"name": "Ana Popescu"}], doi="")
    [merged] = deduplicate([arxiv, crossref, openalex])
    assert brief(merged.authors) == [
        (1, "Ana Popescu", ORCID, "A1", ["Carol Davila"]),
        (2, "Jon Smith", "", "A2", []),
    ]


def test_merge_never_joins_people_with_conflicting_identifiers():
    a = make_authors([{"name": "Wei Li", "orcid": "0000-0001-0000-0001", "openalex_id": "A1"}])
    b = make_authors([{"name": "Wei Li", "orcid": "0000-0001-0000-0002", "affiliations": ["Elsewhere"]}])
    [kept] = merge_authors([a, b])
    assert (kept.orcid, kept.openalex_id) == ("0000-0001-0000-0002", "")  # A1 is not pulled across


def test_merge_of_records_without_authors_is_empty():
    assert merge_authors([[], []]) == []


def test_authors_are_left_out_of_dumps_when_empty_and_hidden_from_models():
    bare = paper("MED:1", "europepmc", [])
    assert "authors" not in bare.model_dump()  # dumps (report.json, checkpoints) unchanged for old papers
    full = paper("MED:1", "europepmc", [{"name": "Ana Popescu", "orcid": ORCID}])
    dumped = full.model_dump()
    assert dumped["authors"] == [{"name": "Ana Popescu", "orcid": ORCID, "affiliations": [], "position": 1}]
    payload = {"topic": "t", "paper": dumped}
    assert without_sources(payload) == without_sources({"topic": "t", "paper": bare.model_dump()})  # same key
    assert Paper.model_validate(json.loads(json.dumps(dumped))).authors == full.authors
