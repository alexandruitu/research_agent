"""Compare two runs; export a run (CSV, BibTeX, bundle) and several runs at once."""

import csv
import io
import json
import zipfile
from pathlib import Path

import pytest
from sqlalchemy import select
from web_fixtures import make_demo_run

from research_agent.web.db.models import Paper, Run, Screening
from research_agent.web.importer.research import import_research_run


@pytest.fixture
def two(imported, db, tmp_path):
    other = import_research_run(db, make_demo_run(tmp_path / "runs" / "demo2", max_papers=4)).run_id
    db.commit()
    return db.get(Run, imported["research"]), db.get(Run, other)


def test_compare_lists_config_and_result_differences(sign_in, two, db):
    a, b = two
    dropped = db.scalars(select(Screening).where(Screening.run_id == b.id)).first()
    dropped.decision = "exclude"
    db.commit()
    viewer, _ = sign_in("viewer")
    r = viewer.get("/api/v1/runs/compare", params={"ids": f"{a.id},{b.id}"})
    assert r.status_code == 200, r.text
    body = r.json()
    rows = {row["label"]: row for row in body["config"]}
    assert rows["Papers to screen"]["differs"] is True and rows["Mode"]["differs"] is False
    title = db.get(Paper, dropped.paper_id).title
    assert title in [p["title"] for p in body["kept_only_a"]]
    assert body["only_in_a"] and not body["only_in_b"]  # 6 papers against 4
    assert [x["id"] for x in body["runs"]] == [str(a.id), str(b.id)]


def test_compare_needs_two_distinct_runs(sign_in, two):
    a, _ = two
    viewer, _ = sign_in("viewer")
    assert viewer.get("/api/v1/runs/compare", params={"ids": f"{a.id},{a.id}"}).status_code == 422
    assert viewer.get("/api/v1/runs/compare", params={"ids": "nope"}).status_code == 422


def test_csv_and_bibtex_export(sign_in, two):
    a, _ = two
    viewer, _ = sign_in("viewer")
    r = viewer.get(f"/api/v1/runs/{a.id}/export", params={"format": "csv"})
    assert r.status_code == 200 and "attachment" in r.headers["content-disposition"]
    rows = list(csv.DictReader(io.StringIO(r.text)))
    assert len(rows) == 6 and {"title", "decision", "score", "run"} <= set(rows[0])
    bib = viewer.get(f"/api/v1/runs/{a.id}/export", params={"format": "bibtex"})
    assert bib.status_code == 200 and bib.text.count("@article{") >= 1


def test_bulk_csv_export_has_a_run_column(sign_in, two):
    a, b = two
    viewer, _ = sign_in("viewer")
    r = viewer.get("/api/v1/runs/export", params={"ids": f"{a.id},{b.id}", "format": "csv"})
    rows = list(csv.DictReader(io.StringIO(r.text)))
    assert {row["run"] for row in rows} == {str(a.id), str(b.id)} and len(rows) == 10


def test_bundle_has_the_reports_and_never_the_database_or_licensed_quotes(sign_in, two):
    a, _ = two
    folder = Path(a.folder)
    report = json.loads((folder / "report.json").read_text())
    pid = next(iter(report["state"]["screens"]))
    report["state"]["review"] = {
        pid: {
            "text_licence": "publisher_licensed",
            "panel": {"m": {"answers": [{"quote": "secret licensed words"}]}},
        }
    }
    (folder / "report.json").write_text(json.dumps(report))
    (folder / "worker.log").write_text("log")
    viewer, _ = sign_in("viewer")
    r = viewer.get(f"/api/v1/runs/{a.id}/export", params={"format": "bundle"})
    assert r.status_code == 200 and r.headers["content-type"] == "application/zip"
    with zipfile.ZipFile(io.BytesIO(r.content)) as bundle:
        names = set(bundle.namelist())
        assert "report.json" in names and "manifest.json" in names and "README.txt" in names
        assert not names & {"research.sqlite", "checkpoints.sqlite", "worker.log", "progress.json"}
        assert "report.md" not in names  # it prints evidence quotes
        assert "secret licensed words" not in bundle.read("report.json").decode()
