"""Library export: CSV (spreadsheet-injection safe) and BibTeX (escaped), with the list filters."""

import csv
import io
from datetime import UTC, datetime

from sqlalchemy import select

from research_agent.web.db.models import Paper
from research_agent.web.library import EXPORT_KEYS, bibtex_escape, to_bibtex, to_csv

API = "/api/v1"


def item(title="T", source_id="MED:1", note="", tags=(), doi=""):
    return {
        "paper": {"title": title, "year": 2024, "doi": doi, "source_id": source_id},
        "status": "read",
        "score": 81.5,
        "red_flag_count": 1,
        "collections": [{"id": "x", "name": "C"}],
        "tags": list(tags),
        "note": note,
        "field": {"name": "F"},
        "added_by_name": "Member",
        "added_at": datetime(2026, 9, 30, tzinfo=UTC),
    }


def test_csv_neutralizes_formulas():
    rows = list(csv.reader(io.StringIO(to_csv([item(title="=HYPERLINK(1)", note="+1", tags=["-x", "@y"])]))))
    assert rows[0][:3] == ["title", "year", "doi"]
    assert rows[1][0] == "'=HYPERLINK(1)" and rows[1][9] == "'+1" and rows[1][8] == "'-x; @y"
    assert rows[1][4:7] == ["read", "81.5", "1"] and rows[1][7] == "C"


def test_bibtex_escapes_and_keys():
    assert (
        bibtex_escape(r"a{b}%&$#_~^\c")
        == r"a\{b\}\%\&\$\#\_\textasciitilde{}\textasciicircum{}\textbackslash{}c"
    )
    assert bibtex_escape("line\nbreak") == "line break"
    text = to_bibtex(
        [item(title="A {B}", doi="10.1/x"), item(source_id="MED/1"), item(source_id="arxiv:2401.1")]
    )
    assert "@article{ra_MED1,\n  title = {A \\{B\\}},\n  year = {2024},\n  doi = {10.1/x}" in text
    assert "@article{ra_MED1_2," in text and "eprint = {2401.1}" in text


def test_export_endpoint_honours_filters(sign_in, imported, db):
    member, csrf = sign_in("member")
    ids = [str(db.scalar(select(Paper.id).where(Paper.source_id == f"demo:{n}"))) for n in (1, 2)]
    body = {"run_id": str(imported["research"]), "paper_ids": ids, "tags": ["x"]}
    item_id = member.post(f"{API}/library", json=body, headers=csrf).json()["created"][0]
    member.patch(f"{API}/library/{item_id}", json={"status": "relevant"}, headers=csrf)
    viewer, _ = sign_in("viewer")
    r = viewer.get(f"{API}/library/export", params={"format": "csv", "status": "relevant"})
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/csv")
    assert r.headers["content-disposition"] == 'attachment; filename="library.csv"'
    assert len(list(csv.reader(io.StringIO(r.text)))) == 2  # header + the one relevant item
    bib = viewer.get(f"{API}/library/export", params={"format": "bibtex"})
    assert bib.headers["content-type"].startswith("application/x-bibtex")
    assert bib.text.count("@article{") == 2 and "keywords = {x}" in bib.text
    assert viewer.get(f"{API}/library/export", params={"format": "ris"}).status_code == 422


def test_exports_hold_metadata_only_even_for_publisher_licensed_text():
    """Text under a publisher licence (ScienceDirect) may be reviewed, never redistributed: whatever an item
    carries besides its metadata (panel quotes, sections, snapshot) never reaches CSV or BibTeX."""
    secret = "LICENSED-SENTINEL full-text sentence"
    leaky = item(title="Paper") | {
        "text_source": "sciencedirect",
        "text_licence": "publisher_licensed",
        "panel": {"text_licence": "publisher_licensed", "quote": secret, "text_sections": [secret]},
        "snapshot": {"panel": {"red_flags": [{"text": secret}]}},
    }
    for out in (to_csv([leaky]), to_bibtex([leaky])):
        assert secret not in out and "publisher_licensed" not in out
    assert EXPORT_KEYS == frozenset(
        {
            "paper",
            "status",
            "score",
            "red_flag_count",
            "collections",
            "tags",
            "note",
            "field",
            "added_by_name",
            "added_at",
        }
    )
