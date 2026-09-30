"""Full-text resolvers added with the new sources, and text_licence (no network; fixtures documented in
tests/test_sources.py, plus springer_jats*.xml, sciencedirect_*.xml, elsevier_entitlement.json after the
providers' documentation, europepmc_oa_links.json and s2_paper.json trimmed after their public API shapes)."""

import json
from pathlib import Path

import httpx
import pytest
from pdf_helpers import PAPER_LINES, tiny_pdf

from research_agent import connectors, ratelimit
from research_agent.fulltext import DEFAULT_ORDER, FullText, normalize_licence
from research_agent.schemas import FULLTEXT_SOURCES
from research_agent.storage import Store

FIXTURES = Path(__file__).parent / "fixtures"
PDF = tiny_pdf(PAPER_LINES)
DOI = "10.3390/diagnostics11050789"
PAPER = {"id": "core:148473", "title": "t", "abstract": "The abstract.", "doi": DOI, "pmcid": ""}
KEYS = (
    "CORE_API_KEY",
    "SPRINGER_API_KEY",
    "IEEE_API_KEY",
    "ELSEVIER_API_KEY",
    "ELSEVIER_INSTTOKEN",
    "S2_API_KEY",
)


@pytest.fixture(autouse=True)
def quiet(monkeypatch):
    monkeypatch.setattr(connectors.time, "sleep", lambda _s: None)
    monkeypatch.setattr(ratelimit.TokenBucket, "acquire", lambda self: 0.0)
    for key in KEYS:
        monkeypatch.delenv(key, raising=False)


def fixture(name):
    text = (FIXTURES / name).read_text()
    return json.loads(text) if name.endswith(".json") else text


def client(routes, seen=None):
    def handler(request):
        if seen is not None:
            seen.append(request)
        for prefix, response in routes.items():
            if str(request.url).startswith(prefix):
                if isinstance(response, dict):
                    return httpx.Response(200, json=response)
                if isinstance(response, str):
                    return httpx.Response(200, text=response)
                if isinstance(response, bytes):
                    return httpx.Response(200, content=response)
                return response
        return httpx.Response(404)

    return httpx.Client(transport=httpx.MockTransport(handler))


def resolve(tmp_path, sources, routes, paper=PAPER, seen=None):
    spec = {"sources": sources, "contact": "a@b.org", "max_chars": 60000}
    return FullText(Store(tmp_path), spec, client=client(routes, seen)).resolve(paper)


def test_default_order_is_the_spec_order_and_matches_the_schema():
    assert (
        DEFAULT_ORDER
        == FULLTEXT_SOURCES
        == (
            "pmc_oa",
            "europepmc",
            "core",
            "springer_oa",
            "semantic_scholar_oa",
            "unpaywall",
            "ieee",
            "sciencedirect",
            "upload",
        )
    )


@pytest.mark.parametrize(
    "value,expected",
    [
        ("http://creativecommons.org/licenses/by/4.0/", "cc-by"),
        ("https://creativecommons.org/licenses/by-nc-nd/4.0/", "cc-by-nc-nd"),
        ("cc by", "cc-by"),
        ("CC-BY-NC", "cc-by-nc"),
        ("cc_by_sa", "cc-by-sa"),
        ("http://creativecommons.org/publicdomain/zero/1.0/", "cc0"),
        ("CC0", "cc0"),
        ("publisher-specific", None),
        (None, None),
    ],
)
def test_normalize_licence(value, expected):
    assert normalize_licence(value) == expected


def test_pmc_oa_records_its_jats_licence(tmp_path):
    pmc = "https://www.ebi.ac.uk/europepmc/webservices/rest/PMC1/fullTextXML"
    xml = fixture("springer_jats.xml")
    article = xml[xml.index("<article") : xml.index("</article>") + len("</article>")]
    text = resolve(tmp_path, ["pmc_oa"], {pmc: article}, {**PAPER, "pmcid": "PMC1"})
    assert text["text_source"] == "pmc_oa" and text["text_licence"] == "cc-by"


def test_europepmc_resolver_uses_oa_pdf_links_and_skips_pmc_records(tmp_path):
    seen = []
    routes = {
        "https://www.ebi.ac.uk/europepmc/webservices/rest/search": fixture("europepmc_oa_links.json"),
        "https://publisher.example/open.pdf": PDF,
    }
    text = resolve(tmp_path, ["europepmc"], routes, seen=seen)
    assert text["text_source"] == "europepmc" and text["origin"] == "https://publisher.example/open.pdf"
    assert text["text_licence"] == "cc-by" and seen[0].url.params["query"] == f'DOI:"{DOI}"'
    assert all("closed.pdf" not in str(r.url) for r in seen)
    text = resolve(tmp_path / "b", ["europepmc"], routes, {**PAPER, "pmcid": "PMC1"})
    assert text["reason"] == "europepmc: in PMC (pmc_oa)"


def test_core_uses_full_text_then_pdf(tmp_path, monkeypatch):
    monkeypatch.setenv("CORE_API_KEY", "k-core")
    seen = []
    payload = fixture("core_search.json")
    text = resolve(tmp_path, ["core"], {"https://api.core.ac.uk/": payload}, seen=seen)
    assert text["text_source"] == "core" and text["origin"] == "https://core.ac.uk/works/148473"
    assert "Methods" in text["sections"] and text["text_licence"] == "open_access"
    assert seen[0].headers["Authorization"] == "Bearer k-core" and seen[0].url.params["q"] == f'doi:"{DOI}"'
    payload["results"][0]["fullText"] = None
    routes = {"https://api.core.ac.uk/": payload, "https://core.ac.uk/download/pdf/148473.pdf": PDF}
    text = resolve(tmp_path / "b", ["core"], routes)
    assert text["origin"] == "https://core.ac.uk/download/pdf/148473.pdf"


def test_springer_oa_parses_jats_and_licence(tmp_path, monkeypatch):
    monkeypatch.setenv("SPRINGER_API_KEY", "k-spr")
    seen = []
    text = resolve(
        tmp_path,
        ["springer_oa"],
        {"https://api.springernature.com/": fixture("springer_jats.xml")},
        seen=seen,
    )
    assert text["text_source"] == "springer_oa" and text["text_licence"] == "cc-by"
    assert (
        text["sections"] == ["Abstract", "Methods", "Results"] and "Ignored reference" not in text["content"]
    )
    assert text["origin"] == f"https://doi.org/{DOI}" and seen[0].url.params["q"] == f"doi:{DOI}"
    closed = resolve(
        tmp_path / "b",
        ["springer_oa"],
        {"https://api.springernature.com/": fixture("springer_jats_empty.xml")},
    )
    assert closed["reason"] == "springer_oa: not open access at Springer Nature"


def test_s2_oa_downloads_the_open_access_pdf(tmp_path):
    seen = []
    routes = {
        "https://api.semanticscholar.org/": fixture("s2_paper.json"),
        "https://www.example.org/oa/": PDF,
    }
    text = resolve(tmp_path, ["semantic_scholar_oa"], routes, seen=seen)
    assert text["text_source"] == "semantic_scholar_oa" and text["text_licence"] == "cc-by-nc"
    assert str(seen[0].url).startswith(f"https://api.semanticscholar.org/graph/v1/paper/DOI:{DOI}")
    by_id = resolve(tmp_path / "b", ["semantic_scholar_oa"], routes, {**PAPER, "s2": "abc"}, seen=seen)
    assert by_id["text_source"] == "semantic_scholar_oa" and "/paper/abc?" in str(seen[2].url)


def test_ieee_only_for_open_access_articles(tmp_path, monkeypatch):
    monkeypatch.setenv("IEEE_API_KEY", "k-ieee")
    articles = fixture("ieee_search.json")
    open_one = {"articles": [articles["articles"][0]]}
    locked = {"articles": [articles["articles"][1]]}
    pdf = "https://ieeexplore.ieee.org/stamp/stamp.jsp?arnumber=9412345"
    text = resolve(tmp_path, ["ieee"], {"https://ieeexploreapi.ieee.org/": open_one, pdf: PDF})
    assert text["text_source"] == "ieee" and text["origin"] == pdf and text["text_licence"] == "open_access"
    text = resolve(tmp_path / "b", ["ieee"], {"https://ieeexploreapi.ieee.org/": locked})
    assert text["reason"] == "ieee: not open access via the IEEE API"
    html = resolve(tmp_path / "c", ["ieee"], {"https://ieeexploreapi.ieee.org/": open_one, pdf: "<html>"})
    assert html["reason"] == "ieee: PDF download failed"


def test_sciencedirect_only_when_entitled(tmp_path, monkeypatch):
    monkeypatch.setenv("ELSEVIER_API_KEY", "k-els")
    monkeypatch.setenv("ELSEVIER_INSTTOKEN", "tok")
    seen = []
    routes = {
        "https://api.elsevier.com/content/article/entitlement/": fixture("elsevier_entitlement.json"),
        "https://api.elsevier.com/content/article/doi/": fixture("sciencedirect_article.xml"),
    }
    text = resolve(tmp_path, ["sciencedirect"], routes, seen=seen)
    assert text["text_source"] == "sciencedirect" and text["text_licence"] == "publisher_licensed"
    assert text["sections"] == ["Abstract", "Methods", "Results"] and "Women 0.91" in text["content"]
    assert all(r.headers["X-ELS-APIKey"] == "k-els" and r.headers["X-ELS-Insttoken"] == "tok" for r in seen)
    assert "k-els" not in text["origin"]
    denied = fixture("elsevier_entitlement.json")
    denied["entitlement-response"]["document-entitlement"]["entitled"] = False
    text = resolve(
        tmp_path / "b",
        ["sciencedirect"],
        {**routes, "https://api.elsevier.com/content/article/entitlement/": denied},
    )
    assert text["reason"] == "sciencedirect: not entitled"


def test_sciencedirect_without_original_text_is_unavailable(tmp_path, monkeypatch):
    monkeypatch.setenv("ELSEVIER_API_KEY", "k")
    routes = {
        "https://api.elsevier.com/content/article/entitlement/": fixture("elsevier_entitlement.json"),
        "https://api.elsevier.com/content/article/doi/": fixture("sciencedirect_abstract_only.xml"),
    }
    text = resolve(tmp_path, ["sciencedirect"], routes)
    assert text["reason"] == "sciencedirect: no full text in the response (not entitled)"


def test_missing_keys_make_resolvers_unavailable_with_the_variable_name(tmp_path):
    text = resolve(tmp_path, ["core", "springer_oa", "ieee", "sciencedirect"], {})
    assert text["reason"] == (
        "core: CORE_API_KEY not set; springer_oa: SPRINGER_API_KEY not set; ieee: IEEE_API_KEY not set; "
        "sciencedirect: ELSEVIER_API_KEY not set"
    )
    assert text["text_source"] == "abstract" and text["text_licence"] == "abstract"


def test_new_resolvers_are_not_fetched_in_demo_mode(tmp_path):
    spec = {"sources": list(DEFAULT_ORDER[1:-1]), "contact": "a@b.org", "max_chars": 60000}
    text = FullText(Store(tmp_path), spec, mode="demo", client=client({})).resolve(PAPER)
    assert text["reason"].count("not fetched in demo mode") == 7


def test_uploads_and_cached_entries_without_licence(tmp_path):
    store = Store(tmp_path)
    (tmp_path / "up").mkdir()
    (tmp_path / "up" / "core_148473.pdf").write_bytes(PDF)
    spec = {"sources": ["upload"], "contact": None, "max_chars": 60000}
    assert FullText(store, spec, uploads=[tmp_path / "up"]).resolve(PAPER)["text_licence"] == "user_upload"
    with store.connect() as db:  # an ft-1 entry written before licences existed
        db.execute("UPDATE fulltext SET payload = json_remove(payload, '$.licence')")
    assert FullText(store, spec, uploads=[tmp_path / "up"]).resolve(PAPER)["text_licence"] == "user_upload"
