import json

import pytest
from sqlalchemy import func, select
from web_fixtures import add_jev_block, make_demo_run

from research_agent.web.db.models import (
    CriterionScore,
    EvidenceClaim,
    Field,
    Paper,
    Ranking,
    Review,
    Run,
    Screening,
)
from research_agent.web.importer.common import ImportFailed
from research_agent.web.importer.research import import_research_run


def count(db, model):
    return db.scalar(select(func.count()).select_from(model))


def test_import_maps_a_demo_run_into_rows(db, tmp_path):
    folder = make_demo_run(tmp_path / "run")
    result = import_research_run(db, folder)
    assert result.status == "created" and result.warnings == []
    run = db.get(Run, result.run_id)
    assert run.kind == "research" and run.status == "done" and run.folder == str(folder.resolve())
    assert run.manifest["prompt_version"] and run.source_sha256
    assert count(db, Paper) == 6 and count(db, Screening) == 6
    assert count(db, EvidenceClaim) == 6 and count(db, Ranking) == 6
    roles = sorted(r for (r,) in db.execute(select(Review.role)).all())
    assert (
        roles.count("a") == 6 and roles.count("b") == 6 and roles.count("adjudicator") == 6
    )  # demo always disagrees
    screening = db.scalars(select(Screening)).first()
    assert screening.tier == "llm" and screening.llm_decision == "include" and screening.call_key
    field = db.get(Field, run.field_id)
    assert field.topic == "retrieval augmented generation"


def test_jev_decided_papers_carry_probabilities_and_the_jev_call_key(db, tmp_path):
    folder = make_demo_run(tmp_path / "run")
    add_jev_block(folder, "demo:1", 0.93)
    import_research_run(db, folder)
    screening = db.scalar(select(Screening).join(Paper).where(Paper.source_id == "demo:1"))
    assert screening.tier == "jev" and screening.jev_decision == "include" and screening.llm_decision is None
    score = db.scalar(select(CriterionScore).where(CriterionScore.screening_id == screening.id))
    assert score.probability == pytest.approx(0.93) and score.jev_version == "jev-1.13.0"


def test_reimport_is_idempotent_and_updates_in_place(db, tmp_path):
    folder = make_demo_run(tmp_path / "run")
    first = import_research_run(db, folder)
    again = import_research_run(db, folder)
    assert again.status == "unchanged" and again.run_id == first.run_id
    add_jev_block(folder, "demo:2", 0.9)  # changes report.json, hence its hash
    updated = import_research_run(db, folder)
    assert updated.status == "updated" and updated.run_id == first.run_id
    assert count(db, Run) == 1 and count(db, Screening) == 6 and count(db, Paper) == 6
    assert count(db, CriterionScore) == 1


def test_two_runs_share_papers_and_the_field(db, tmp_path):
    import_research_run(db, make_demo_run(tmp_path / "one"))
    import_research_run(db, make_demo_run(tmp_path / "two"))
    assert count(db, Run) == 2 and count(db, Field) == 1 and count(db, Paper) == 6  # papers are global
    assert count(db, Screening) == 12


def test_failed_import_changes_nothing(db, tmp_path):
    folder = make_demo_run(tmp_path / "run")
    path = folder / "report.json"
    data = json.loads(path.read_text())
    data["state"]["screens"]["demo:999"] = data["state"]["screens"]["demo:1"]  # a screen for an unknown paper
    path.write_text(json.dumps(data))
    with pytest.raises(ImportFailed, match="demo:999"):
        import_research_run(db, folder)
    assert count(db, Run) == 0 and count(db, Paper) == 0 and count(db, Screening) == 0


def test_missing_report_is_an_error(db, tmp_path):
    with pytest.raises(ImportFailed, match="report.json"):
        import_research_run(db, tmp_path)


def test_papers_missing_expected_downstream_data_produce_warnings(db, tmp_path):
    folder = make_demo_run(tmp_path / "run")
    path = folder / "report.json"
    data = json.loads(path.read_text())
    del data["state"]["evidence"]["demo:3"]
    path.write_text(json.dumps(data))
    result = import_research_run(db, folder)
    assert any("demo:3" in w and "evidence" in w for w in result.warnings)


def test_a_corrupt_call_store_is_an_import_error_and_writes_nothing(db, tmp_path):
    folder = make_demo_run(tmp_path / "run")
    (folder / "research.sqlite").write_bytes(b"not a sqlite database" * 100)
    with pytest.raises(ImportFailed, match="unreadable research.sqlite"):
        import_research_run(db, folder)
    db.rollback()
    assert count(db, Run) == 0


def test_reimport_moves_the_run_to_the_field_of_its_new_topic(db, tmp_path):
    folder = make_demo_run(tmp_path / "run")
    first = import_research_run(db, folder)
    report = folder / "report.json"
    data = json.loads(report.read_text())
    data["state"]["contract"]["topic"] = "a different topic"
    report.write_text(json.dumps(data))
    assert import_research_run(db, folder).status == "updated"
    run = db.get(Run, first.run_id)
    assert db.get(Field, run.field_id).topic == "a different topic"
