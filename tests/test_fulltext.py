from pathlib import Path

import pytest
from pdf_helpers import PAPER_LINES, tiny_pdf

from research_agent.fulltext import (
    FulltextUnavailable,
    Section,
    assemble,
    parse_jats,
    pdf_sections,
    section_kind,
    split_sections,
    upload_name,
)

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
