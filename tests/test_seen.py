"""Skip seen (alert runs): matching, counts, cap ordering, and the step inside a real demo run."""

import json

import pytest

from research_agent.runner import run_research
from research_agent.schemas import Contract, Paper, Source
from research_agent.seen import SeenSet, read_seen, skip_seen, write_seen


def paper(pid, title="A study", year="2026", doi="", records=()):
    provenance = [
        Source(connector="x", record_id=r, url="", query="q", retrieved_at="t", raw_sha256="0")
        for r in (records or [pid])
    ]
    return Paper(id=pid, title=title, abstract="", year=year, doi=doi, provenance=provenance)


def test_a_seen_doi_matches_whatever_its_spelling():
    seen = SeenSet.from_records([{"doi": "10.1/ABC", "source_id": "MED:1", "title": "Other", "year": 2020}])
    assert seen.contains(paper("OA:9", doi="https://doi.org/10.1/abc"))
    assert not seen.contains(paper("OA:9", doi="10.1/abd"))


def test_a_seen_source_id_matches_the_paper_id_or_any_record_that_found_it():
    seen = SeenSet.from_records([{"doi": "", "source_id": "MED:1", "title": "x", "year": None}])
    assert seen.contains(paper("MED:1"))
    assert seen.contains(paper("OA:5", records=["OA:5", "med:1"]))
    assert not seen.contains(paper("MED:2"))


def test_title_and_year_match_unless_the_dois_conflict():
    seen = SeenSet.from_records(
        [{"doi": "10.1/a", "source_id": "S:1", "title": "Deep  CT-FFR!", "year": 2025}]
    )
    assert seen.contains(paper("X:1", title="deep ct ffr", year="2025"))  # no DOI: same work
    assert not seen.contains(paper("X:1", title="deep ct ffr", year="2026"))  # another year
    assert not seen.contains(paper("X:1", title="deep ct ffr", year="2025", doi="10.1/b"))  # another work
    no_doi = SeenSet.from_records([{"doi": "", "source_id": "S:2", "title": "Deep CT-FFR", "year": 2025}])
    assert no_doi.contains(paper("X:1", title="Deep CT FFR", year="2025", doi="10.1/b"))


def test_skip_seen_counts_and_keeps_the_newest_within_the_cap_in_source_order():
    seen = SeenSet.from_records([{"doi": "", "source_id": "P:2", "title": "", "year": None}])
    papers = [
        paper("P:1", "one", "2025"),
        paper("P:2", "two", "2026"),
        paper("P:3", "three", "2026"),
        paper("P:4", "four", ""),
        paper("P:5", "five", "2026"),
    ]
    kept, counts = skip_seen(papers, seen, 3)
    assert [p.id for p in kept] == ["P:3", "P:5", "P:1"]  # 2026 in source order, then 2025; no year last
    assert counts == {"found": 5, "already_seen": 1, "new": 4, "over_cap": 1}
    kept, counts = skip_seen(papers, SeenSet(), 50)
    assert len(kept) == 5 and counts["over_cap"] == 0 and counts["already_seen"] == 0


def test_an_unreadable_seen_file_fails_closed(tmp_path):
    bad = tmp_path / "seen.json"
    bad.write_text("{not json")
    with pytest.raises(ValueError):
        read_seen(bad)
    bad.write_text(json.dumps({"schema": 1, "max_new": 0, "papers": []}))
    with pytest.raises(ValueError):
        read_seen(bad)


def test_a_demo_run_skips_seen_papers_before_screening(tmp_path):
    topic = "retrieval augmented generation"
    first = tmp_path / "first"
    result = run_research(first, contract=Contract(topic=topic, mode="demo", max_papers=6))
    ids = [p["id"] for p in result["papers"]]
    seen_file = write_seen(
        tmp_path / "in.json", [{"source_id": ids[0], "doi": "", "title": "", "year": None}], 2
    )
    second = tmp_path / "second"
    result = run_research(
        second, contract=Contract(topic=topic, mode="demo", max_papers=6), seen_file=seen_file
    )
    counts = result["skip_seen"]
    assert counts["already_seen"] == 1 and counts["new"] == counts["found"] - 1
    assert len(result["papers"]) == 2 and counts["over_cap"] == counts["new"] - 2
    assert ids[0] not in {p["id"] for p in result["papers"]}
    assert set(result["screens"]) == {p["id"] for p in result["papers"]}  # no model call for a seen paper
    manifest = json.loads((second / "manifest.json").read_text())
    assert manifest["skip_seen"] == {"file": "seen.json", "max_new": 2, "counts": counts}
    assert json.loads((second / "progress.json").read_text())["skip_seen"] == counts
    assert (second / "seen.json").exists()
