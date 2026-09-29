import json
from pathlib import Path

import httpx
import pytest
from pdf_helpers import PAPER_LINES, tiny_pdf

from research_agent.fulltext import (
    FullText,
    FulltextUnavailable,
    Section,
    assemble,
    parse_jats,
    pdf_sections,
    section_kind,
    split_sections,
    upload_name,
)
from research_agent.storage import Store

FIXTURES = Path(__file__).parent / "fixtures"


def test_section_kinds():
    assert [
        section_kind(t) for t in ["2. Materials and Methods", "RESULTS", "Discussion", "References", "x"]
    ] == ["methods", "results", "discussion", "references", "other"]


def test_assemble_prioritises_methods_and_results_and_keeps_document_order():
    sections = [
        Section("Introduction", "i" * 300),
        Section("Methods", "m" * 300),
        Section("Results", "r" * 300),
        Section("References", "ref"),
    ]
    content, kept, truncated = assemble(sections, 700)
    assert kept == ["Methods", "Results"] and truncated and len(content) <= 700
    assert content.index("## Methods") < content.index("## Results") and "ref" not in content
    content, kept, truncated = assemble(sections, 5000)
    assert kept == ["Introduction", "Methods", "Results"] and not truncated


def test_assemble_cuts_a_section_that_no_longer_fits():
    content, kept, truncated = assemble([Section("Methods", "m" * 5000)], 2000)
    assert kept == ["Methods"] and truncated and len(content) == 2000


def test_parse_jats_reads_abstract_and_body_sections_without_references():
    sections = parse_jats((FIXTURES / "europepmc_fulltext.xml").read_text())
    assert [s.title for s in sections] == [
        "Abstract",
        "Background",
        "Methods",
        "Results",
        "Discussion",
        "Conclusions",
    ]
    assert "registered with PROSPERO" in sections[2].text
    assert all("must never reach" not in s.text for s in sections)


def test_parse_jats_without_body_is_unavailable():
    with pytest.raises(FulltextUnavailable, match="no body"):
        parse_jats("<article><front/></article>")


def test_pdf_text_and_sections():
    sections = pdf_sections(tiny_pdf(PAPER_LINES))
    titles = [s.title for s in sections]
    assert titles == ["", "Methods", "Results", "References"]
    assert "split at patient level" in sections[1].text


def test_split_sections_accepts_numbered_headings():
    sections = split_sections("Title\n1. Introduction\nWhy.\n2 Methods\nHow.")
    assert [(s.title, s.text) for s in sections] == [
        ("", "Title"),
        ("Introduction", "Why."),
        ("Methods", "How."),
    ]


def test_unreadable_pdfs_are_unavailable():
    with pytest.raises(FulltextUnavailable, match="not a PDF"):
        pdf_sections(b"<html>")
    with pytest.raises(FulltextUnavailable, match="could not be read"):
        pdf_sections(b"%PDF-1.4 garbage")
    with pytest.raises(FulltextUnavailable, match="no extractable text"):
        pdf_sections(tiny_pdf([]))


def test_upload_name_is_filesystem_safe():
    assert upload_name("MED:123") == "MED_123.pdf" and upload_name("arxiv:2401.1/x") == "arxiv_2401.1_x.pdf"


PAPER = {
    "id": "MED:1",
    "title": "t",
    "abstract": "The abstract.",
    "doi": "10.3348/kjr.2025.1963",
    "pmcid": "PMC13202077",
}
SPEC = {
    "sources": ["pmc_oa", "unpaywall", "upload"],
    "contact": "research-team@example.org",
    "max_chars": 60000,
}


def client(routes, seen=None):
    def handler(request):
        if seen is not None:
            seen.append(str(request.url))
        for prefix, response in routes.items():
            if str(request.url).startswith(prefix):
                return response() if callable(response) else response
        return httpx.Response(404)

    return httpx.Client(transport=httpx.MockTransport(handler))


PMC = "https://www.ebi.ac.uk/europepmc/webservices/rest/PMC13202077/fullTextXML"
UNPAYWALL = "https://api.unpaywall.org/v2/10.3348/kjr.2025.1963"
PDF_URL = "http://kjronline.org/Synapse/Data/PDFData/0068KJR/kjr-27-e68.pdf"


def test_pmc_oa_first_and_cached(tmp_path):
    store, seen = Store(tmp_path), []
    xml = httpx.Response(200, text=(FIXTURES / "europepmc_fulltext.xml").read_text())
    text = FullText(store, SPEC, client=client({PMC: xml}, seen)).resolve(PAPER)
    assert text["text_source"] == "pmc_oa" and text["reason"] is None and text["origin"] == PMC
    assert text["sections"][:2] == ["Abstract", "Background"] and "PROSPERO" in text["content"]
    again = FullText(store, SPEC, client=client({}, seen)).resolve(PAPER)
    assert again == text and len(seen) == 1


def test_unpaywall_pdf_when_pmc_fails(tmp_path):
    seen = []
    routes = {
        UNPAYWALL: httpx.Response(200, json=json.loads((FIXTURES / "unpaywall_pdf.json").read_text())),
        PDF_URL: httpx.Response(200, content=tiny_pdf(PAPER_LINES)),
    }
    text = FullText(Store(tmp_path), SPEC, client=client(routes, seen)).resolve(PAPER)
    assert text["text_source"] == "unpaywall" and text["origin"] == PDF_URL
    assert text["reason"] == "pmc_oa: request failed" and "patient level" in text["content"]
    assert f"{UNPAYWALL}?email=research-team%40example.org" in seen


def test_unpaywall_without_pdf_then_upload(tmp_path):
    no_pdf = json.loads((FIXTURES / "unpaywall_no_pdf.json").read_text())
    (tmp_path / "uploads").mkdir()
    (tmp_path / "uploads" / "MED_1.pdf").write_bytes(tiny_pdf(PAPER_LINES))
    text = FullText(
        Store(tmp_path),
        SPEC,
        uploads=[tmp_path / "uploads"],
        client=client({UNPAYWALL: httpx.Response(200, json=no_pdf)}),
    ).resolve(PAPER)
    assert text["text_source"] == "upload" and text["origin"].startswith("upload:")
    # The recorded record's only PDF is a PMC repository copy (404 here); the publisher gives a landing page.
    assert text["reason"] == "pmc_oa: request failed; unpaywall: PDF download failed"


def test_an_unpaywall_record_without_pdf_locations_is_a_reason(tmp_path):
    record = json.loads((FIXTURES / "unpaywall_no_pdf.json").read_text())
    record["oa_locations"] = [loc for loc in record["oa_locations"] if not loc["url_for_pdf"]]
    spec = {**SPEC, "sources": ["unpaywall"]}
    text = FullText(
        Store(tmp_path), spec, client=client({UNPAYWALL: httpx.Response(200, json=record)})
    ).resolve(PAPER)
    assert text["text_source"] == "abstract" and text["reason"] == "unpaywall: no open-access PDF"


def test_everything_fails_falls_back_to_the_abstract(tmp_path):
    routes = {
        UNPAYWALL: httpx.Response(200, json=json.loads((FIXTURES / "unpaywall_pdf.json").read_text())),
        PDF_URL: httpx.Response(200, content=b"<html>login</html>"),
    }
    text = FullText(Store(tmp_path), SPEC, client=client(routes)).resolve(PAPER)
    assert text == {
        "text_source": "abstract",
        "content": "The abstract.",
        "sections": [],
        "truncated": False,
        "origin": None,
        "reason": "pmc_oa: request failed; unpaywall: PDF download failed; upload: no uploaded PDF",
    }


def test_demo_mode_uses_uploads_only_and_missing_ids_are_reasons(tmp_path):
    paper = {**PAPER, "pmcid": "", "doi": ""}
    text = FullText(Store(tmp_path), SPEC, mode="demo", client=client({})).resolve(paper)
    assert text["reason"] == "pmc_oa: no PMCID; unpaywall: no DOI; upload: no uploaded PDF"
    text = FullText(Store(tmp_path), SPEC, mode="demo", client=client({})).resolve(PAPER)
    assert text["reason"].startswith("pmc_oa: not fetched in demo mode; unpaywall: not fetched in demo mode")


def test_a_bad_upload_is_a_reason_not_an_error(tmp_path):
    (tmp_path / "MED_1.pdf").write_bytes(b"MZ executable")
    spec = {**SPEC, "sources": ["upload"]}
    text = FullText(Store(tmp_path), spec, uploads=[tmp_path]).resolve(PAPER)
    assert text["text_source"] == "abstract" and text["reason"] == "upload: not a PDF"


def test_the_contact_email_is_never_stored(tmp_path):
    routes = {
        UNPAYWALL: httpx.Response(200, json=json.loads((FIXTURES / "unpaywall_pdf.json").read_text())),
        PDF_URL: httpx.Response(200, content=tiny_pdf(PAPER_LINES)),
    }
    FullText(Store(tmp_path), {**SPEC, "sources": ["unpaywall"]}, client=client(routes)).resolve(PAPER)
    assert b"research-team" not in (tmp_path / "research.sqlite").read_bytes()
