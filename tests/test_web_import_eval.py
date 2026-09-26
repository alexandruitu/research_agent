import json

import pytest
from sqlalchemy import func, select
from web_fixtures import JEV_P, make_eval_run

from research_agent.eval.metrics import cascade_decision
from research_agent.jev import JevThresholds
from research_agent.web.db.models import (
    CriterionScore,
    EvalReport,
    EvidenceClaim,
    GoldLabel,
    GoldSet,
    Paper,
    Review,
    Run,
    Screening,
)
from research_agent.web.importer.common import ImportFailed
from research_agent.web.importer.evals import import_eval_run


def count(db, model):
    return db.scalar(select(func.count()).select_from(model))


def test_import_maps_an_eval_run(db, tmp_path):
    run_dir, _gold_path, _report = make_eval_run(tmp_path)
    result = import_eval_run(db, run_dir)
    assert result.status == "created"
    run = db.get(Run, result.run_id)
    assert run.kind == "eval" and run.status == "done" and run.gold_set_id
    assert count(db, Paper) == 12 and count(db, Screening) == 12 and count(db, GoldLabel) == 12
    assert count(db, CriterionScore) == 12
    gold = db.get(GoldSet, run.gold_set_id)
    assert gold.name == "toy" and gold.sha256
    labels = {
        p.source_id: lab
        for p, lab in db.execute(
            select(Paper, GoldLabel.label).join(GoldLabel, GoldLabel.paper_id == Paper.id)
        )
    }
    assert sum(1 for v in labels.values() if v == "include") == 4


def test_screenings_equal_the_shipped_cascade_and_the_report(db, tmp_path):
    run_dir, _gold_path, report = make_eval_run(tmp_path)
    import_eval_run(db, run_dir)
    rows = {
        p.source_id: s
        for s, p in db.execute(select(Screening, Paper).join(Paper, Paper.id == Screening.paper_id))
    }
    for index in range(1, 13):
        s = rows[f"MED:{index}"]
        llm = "exclude" if f"MED:{index}" in {"MED:7", "MED:8"} else "include"
        decision, tier = cascade_decision({"topic_match": JEV_P[index]}, llm, JevThresholds())
        assert (s.decision, s.tier, s.llm_decision) == (decision, tier, llm)
    kept = sum(1 for s in rows.values() if s.decision != "exclude")
    assert kept == report["strategies"]["cascade"]["kept"]  # the UI numbers equal the report numbers
    assert rows["MED:3"].decision == "exclude" and rows["MED:3"].jev_decision == "exclude"
    assert rows["MED:2"].tier == "llm" and rows["MED:2"].jev_decision == "escalate" and rows["MED:2"].call_key


def test_eval_report_and_agreement_rows(db, tmp_path):
    run_dir, _gold_path, _report = make_eval_run(tmp_path)
    result = import_eval_run(db, run_dir)
    stored = db.scalar(select(EvalReport).where(EvalReport.run_id == result.run_id))
    assert stored.metrics == json.loads((run_dir / "metrics.json").read_text())
    assert stored.agreement["n"] == 6
    roles = [r for (r,) in db.execute(select(Review.role)).all()]
    assert roles.count("a") == 6 and roles.count("b") == 6 and roles.count("adjudicator") == 6
    assert count(db, EvidenceClaim) == 6  # one demo claim per sampled paper
    adjudicator = db.scalar(select(Review).where(Review.role == "adjudicator"))
    assert adjudicator.verdict and "reason" in adjudicator.detail and adjudicator.call_key


def test_reimport_is_idempotent_and_gold_changes_are_refused(db, tmp_path):
    run_dir, _gold, _report = make_eval_run(tmp_path / "one")
    first = import_eval_run(db, run_dir)
    assert import_eval_run(db, run_dir).status == "unchanged"
    other_dir, _g, _r = make_eval_run(
        tmp_path / "two", positive_ids=(1, 2)
    )  # same gold name, different labels
    with pytest.raises(ImportFailed, match="gold set 'toy' changed"):
        import_eval_run(db, other_dir)
    assert count(db, Run) == 1 and db.get(Run, first.run_id)


def test_gold_dir_override_for_moved_runs(db, tmp_path):
    run_dir, gold_path, _report = make_eval_run(tmp_path / "src")
    moved = tmp_path / "moved" / "gold"
    moved.mkdir(parents=True)
    (moved / gold_path.name).write_bytes(gold_path.read_bytes())
    gold_path.unlink()  # the manifest still points at the deleted original
    assert import_eval_run(db, run_dir, gold_dir=moved).status == "created"


def test_missing_metrics_json_is_an_error(db, tmp_path):
    run_dir, _g, _r = make_eval_run(tmp_path)
    (run_dir / "metrics.json").unlink()
    with pytest.raises(ImportFailed, match="research-eval report"):
        import_eval_run(db, run_dir)


def test_run_without_agreement_still_imports(db, tmp_path):
    run_dir, _g, _r = make_eval_run(tmp_path, with_agreement=False)
    import_eval_run(db, run_dir)
    assert count(db, Review) == 0 and db.scalar(select(EvalReport)).agreement is None


def test_candidates_without_an_abstract_are_kept_as_rule_screenings(db, tmp_path):
    from eval_helpers import StubEvaluator, jev_client, make_gold

    from research_agent.eval.gold import write_gold
    from research_agent.eval.report import build_report, write_report
    from research_agent.eval.screen import run_screen, write_manifest
    from research_agent.jev import JevScreener
    from research_agent.storage import Store

    gold = make_gold(n=6, positive_ids=(1, 2), name="noabs")
    gold.candidates[5].abstract = ""
    gold.candidates[5].flags = ["no_abstract"]
    gold_path = tmp_path / "gold" / "noabs.json"
    gold = write_gold(gold, gold_path)
    run = tmp_path / "evals" / "noabs"
    store = Store(run)
    result = run_screen(gold, store, StubEvaluator(store), JevScreener(store, "k", client=jev_client({})))
    write_manifest(
        run, gold_path=gold_path, gold=gold, mode="demo", models={}, jev_model="jev-latest", screened=result
    )
    write_report(run, build_report(run))
    import_eval_run(db, run)
    rule = db.scalar(select(Screening).where(Screening.tier == "rule"))
    assert rule.decision == "uncertain" and "No abstract" in rule.reason
    assert count(db, Screening) == 6 and count(db, CriterionScore) == 5


def test_a_gold_file_replaced_after_screening_is_an_import_error(db, tmp_path):
    from eval_helpers import make_gold

    from research_agent.eval.gold import write_gold

    run_dir, gold_path, _report = make_eval_run(tmp_path)
    write_gold(
        make_gold(n=12, positive_ids=(1,), name="toy"), gold_path
    )  # valid, frozen, but not the screened one
    with pytest.raises(ImportFailed, match="cannot read the eval run"):
        import_eval_run(db, run_dir)
    assert count(db, Run) == 0


def test_a_corrupt_manifest_is_an_import_error(db, tmp_path):
    run_dir, _g, _r = make_eval_run(tmp_path)
    (run_dir / "manifest.json").write_text("{not json")
    with pytest.raises(ImportFailed, match="cannot read the eval run"):
        import_eval_run(db, run_dir)


def test_corrupt_metrics_json_is_an_import_error_and_writes_nothing(db, tmp_path):
    run_dir, _g, _r = make_eval_run(tmp_path)
    (run_dir / "metrics.json").write_text("{not json")
    with pytest.raises(ImportFailed, match="unexpected eval run content"):
        import_eval_run(db, run_dir)
    assert count(db, Run) == 0 and count(db, Paper) == 0
