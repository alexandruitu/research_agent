"""Importing panel and ablation eval folders as immutable eval reports (kind + frozen config)."""

import json
import shutil

from sqlalchemy import select
from web_fixtures import make_ablation_eval, make_panel_eval

from research_agent.web.db.models import EvalReport, GoldSet, Run
from research_agent.web.importer.evals import import_eval_run


def test_a_panel_folder_becomes_a_panel_report_linked_to_its_gold_set(db, tmp_path):
    folder, _gold = make_panel_eval(tmp_path)
    result = import_eval_run(db, folder)
    report = db.get(EvalReport, result.report_id)
    metrics = json.loads((folder / "metrics.json").read_text())
    assert result.status == "created" and report.kind == "panel" and report.metrics == metrics
    assert report.config == metrics["config"] and report.config["sample"]["n"] == 4
    assert db.get(GoldSet, report.gold_set_id).name == "panel-toy"
    run = db.get(Run, result.run_id)
    assert (
        run.kind == "eval" and run.settings_version_id is not None and run.gold_set_id == report.gold_set_id
    )
    again = import_eval_run(db, folder)
    assert again.status == "unchanged" and again.report_id == report.id


def test_an_ablation_folder_links_to_its_imported_panel(db, tmp_path):
    panel, _gold = make_panel_eval(tmp_path)
    parent = import_eval_run(db, panel)
    ablation = make_ablation_eval(tmp_path, panel)
    result = import_eval_run(db, ablation)
    report = db.get(EvalReport, result.report_id)
    assert report.kind == "ablation" and report.parent_id == parent.report_id
    assert len(report.metrics["ablation"]["subsets"]) == 7 and report.config["kind"] == "ablation"
    assert report.gold_set_id == db.get(EvalReport, parent.report_id).gold_set_id


def test_kind_override_and_extra_config_for_a_human_copy(db, tmp_path):
    panel, _gold = make_panel_eval(tmp_path)
    parent = import_eval_run(db, panel)
    copy = tmp_path / "evals" / "panel-a-human"
    shutil.copytree(panel, copy)
    result = import_eval_run(
        db, copy, kind="human", parent_id=parent.report_id, extra_config={"rating_sample_id": "s1"}
    )
    report = db.get(EvalReport, result.report_id)
    assert report.kind == "human" and report.parent_id == parent.report_id
    assert report.config["rating_sample_id"] == "s1"
    assert db.scalar(select(EvalReport).where(EvalReport.id == parent.report_id)).kind == "panel"
