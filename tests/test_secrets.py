"""Keys never reach the store, provenance, recorded queries or exceptions (sentinel test, no network)."""

import json
from pathlib import Path

import httpx
import pytest
from pdf_helpers import PAPER_LINES, tiny_pdf

from research_agent import connectors, ratelimit
from research_agent.connectors import OpenAlex, SourceUnavailable
from research_agent.fulltext import DEFAULT_ORDER, FullText
from research_agent.sources import IEEE, Core, Crossref, PubMed, Scopus, SemanticScholar, Springer
from research_agent.storage import Store

FIXTURES = Path(__file__).parent / "fixtures"
SENTINEL = "SENTINEL-KEY-4f1c"
ENV = (
    "S2_API_KEY",
    "NCBI_API_KEY",
    "CORE_API_KEY",
    "IEEE_API_KEY",
    "SPRINGER_API_KEY",
    "ELSEVIER_API_KEY",
    "ELSEVIER_INSTTOKEN",
    "OPENALEX_API_KEY",
)


@pytest.fixture(autouse=True)
def keys(monkeypatch):
    monkeypatch.setattr(connectors.time, "sleep", lambda _s: None)
    monkeypatch.setattr(ratelimit.TokenBucket, "acquire", lambda self: 0.0)
    for name in ENV:
        monkeypatch.setenv(name, SENTINEL)


def echoing(name):
    """Serves the fixture with the key echoed into it, the way a careless API might."""
    body = (FIXTURES / name).read_text()
    if name.endswith(".json"):
        data = json.loads(body)
        data["echo"] = {"apikey": SENTINEL, "note": f"request made with {SENTINEL}"}
        return httpx.Response(200, json=data)
    return httpx.Response(200, text=body.replace("</", f"<!-- {SENTINEL} --></", 1))


def mock(*responses):
    queue = list(responses)
    return httpx.Client(
        transport=httpx.MockTransport(lambda request: queue.pop(0) if len(queue) > 1 else queue[0])
    )


CASES = [
    (SemanticScholar, ["s2_search.json"]),
    (Crossref, ["crossref_works.json"]),
    (PubMed, ["pubmed_esearch.json", "pubmed_efetch.xml"]),
    (Core, ["core_search.json"]),
    (IEEE, ["ieee_search.json"]),
    (Springer, ["springer_meta.json"]),
    (Scopus, ["scopus_search.json"]),
    (OpenAlex, ["openalex_total.json"]),
]


def everything(store):
    blob = (store.path).read_bytes().decode("utf-8", "replace")
    with store.connect() as db:
        for table in ("raw", "calls", "papers", "fulltext", "lookups"):
            blob += json.dumps(db.execute(f"SELECT * FROM {table}").fetchall())
    return blob


KEYED = [case for case in CASES if case[0] is not Crossref]  # Crossref sends no key


@pytest.mark.parametrize("cls,files", KEYED, ids=[c.__name__ for c, _ in KEYED])
def test_no_key_value_reaches_the_store_or_the_results(tmp_path, cls, files):
    store = Store(tmp_path)
    result = cls(store, mock(*[echoing(f) for f in files])).search_with_total("q", 5)
    assert result.papers
    assert SENTINEL not in json.dumps([p.model_dump() for p in result.papers]) + result.query
    assert SENTINEL not in everything(store)


@pytest.mark.parametrize("cls", [c for c, _ in CASES], ids=[c.__name__ for c, _ in CASES])
@pytest.mark.parametrize("status", [401, 503])
def test_no_key_value_in_failures(tmp_path, cls, status):
    with pytest.raises(SourceUnavailable) as info:
        cls(Store(tmp_path), mock(httpx.Response(status))).search("q", 5)
    chain, exc = [], info.value
    while exc is not None and len(chain) < 10:
        chain.append(repr(exc))
        exc = exc.__cause__ if exc.__cause__ is not None or exc.__suppress_context__ else exc.__context__
    assert SENTINEL not in " ".join(chain)


def test_no_key_value_reaches_the_fulltext_cache(tmp_path):
    pdf = tiny_pdf(PAPER_LINES)

    def handler(request):
        url = str(request.url)
        if url.endswith(".pdf") or "stamp.jsp" in url:
            return httpx.Response(200, content=pdf)
        if "core.ac.uk" in url:
            return echoing("core_search.json")
        return httpx.Response(404)

    store = Store(tmp_path)
    spec = {"sources": list(DEFAULT_ORDER), "contact": "a@b.org", "max_chars": 60000}
    paper = {"id": "x:1", "title": "t", "abstract": "a", "doi": "10.3390/diagnostics11050789", "pmcid": ""}
    text = FullText(store, spec, client=httpx.Client(transport=httpx.MockTransport(handler))).resolve(paper)
    assert text["text_source"] == "core"
    assert SENTINEL not in json.dumps(text) and SENTINEL not in everything(store)
