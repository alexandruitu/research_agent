import json

import langchain.chat_models
import pytest
from eval_helpers import panel_gold, small_review

from research_agent.eval import cli
from research_agent.eval.gold import write_gold
from research_agent.eval.panel_report import build_eval_report


def forbid_network(monkeypatch):
    monkeypatch.setattr(
        langchain.chat_models, "init_chat_model", lambda *a, **k: pytest.fail("no model calls")
    )


def test_demo_panel_ablation_human_report_end_to_end(tmp_path, monkeypatch, capsys):
    forbid_network(monkeypatch)
    gold = tmp_path / "gold.json"
    write_gold(panel_gold(), gold)
    review = small_review(tmp_path / "review.json", ("methodologist", "clinician", "statistician"))
    panel, abl = tmp_path / "panel", tmp_path / "abl"
    args = ["panel", "--gold", str(gold), "--review", str(review), "--eval-dir", str(panel)]
    assert cli.main([*args, "--sample", "4", "--seed", "1", "--mode", "demo"], dotenv=False) == 0
    assert cli.main(["ablation", str(panel), "--eval-dir", str(abl)], dotenv=False) == 0
    assert (
        cli.main(
            [
                "ablation",
                str(panel),
                "--eval-dir",
                str(tmp_path / "abl2"),
                "--rerun-editor",
                "--mode",
                "demo",
            ],
            dotenv=False,
        )
        == 0
    )

    ratings = tmp_path / "ratings.json"
    first = json.loads((panel / "manifest.json").read_text())["sample"]["ids"][0]
    ratings.write_text(
        json.dumps(
            {
                "schema": 1,
                "ratings": [
                    {
                        "paper_id": first,
                        "reviewer": "methodologist",
                        "reviewer_version": 1,
                        "item": "m1",
                        "item_text": "methodologist item one.",
                        "rater": "u1",
                        "answer": "yes",
                    }
                ],
            }
        )
    )
    assert cli.main(["human", str(panel), "--ratings", str(ratings)], dotenv=False) == 0
    assert (panel / "human_ratings.json").exists()

    assert cli.main(["report", str(panel)], dotenv=False) == 0
    report = json.loads((panel / "metrics.json").read_text())
    assert report["kind"] == "panel" and set(report) == {"kind", "config", "panel", "human"}
    assert report["panel"]["n"] == 4 and report["config"]["sample"]["seed"] == 1
    assert report["human"]["units"] == 1 and "# Panel evaluation" in (panel / "metrics.md").read_text()
    assert report == json.loads(json.dumps(build_eval_report(panel)))  # CLI == direct call (worker)

    assert cli.main(["report", str(abl)], dotenv=False) == 0
    ablation = json.loads((abl / "metrics.json").read_text())
    assert set(ablation) == {"kind", "config", "ablation"} and len(ablation["ablation"]["subsets"]) == 7
    assert "Going from 2 to 3 reviewers" in (abl / "metrics.md").read_text()
    assert "Panel eval: 4 papers" in capsys.readouterr().out


def test_panel_from_run_folder_has_no_auc(tmp_path, monkeypatch):
    forbid_network(monkeypatch)
    gold = panel_gold()
    papers = [
        {"id": c.id, "title": c.title, "abstract": c.abstract, "year": c.year, "sources": ["europepmc"]}
        for c in gold.candidates
    ]
    run = tmp_path / "run"
    run.mkdir()
    (run / "report.json").write_text(
        json.dumps({"manifest": {}, "state": {"contract": {"topic": "t"}, "papers": papers}})
    )
    review = small_review(tmp_path / "review.json")
    eval_dir = tmp_path / "panel"
    argv = [
        "panel",
        "--run",
        str(run),
        "--review",
        str(review),
        "--eval-dir",
        str(eval_dir),
        "--sample",
        "3",
        "--mode",
        "demo",
    ]
    assert cli.main(argv, dotenv=False) == 0
    assert cli.main(["report", str(eval_dir)], dotenv=False) == 0
    report = json.loads((eval_dir / "metrics.json").read_text())
    assert report["panel"]["sr_inclusion_auc"]["value"] is None and "human" not in report
    assert report["config"]["source"]["run_dir"] == str(run.resolve())


def test_panel_cli_errors_go_to_errors_log(tmp_path, capsys):
    review = small_review(tmp_path / "review.json")
    argv = [
        "panel",
        "--gold",
        str(tmp_path / "missing.json"),
        "--review",
        str(review),
        "--eval-dir",
        str(tmp_path / "e"),
        "--mode",
        "demo",
    ]
    assert cli.main(argv, dotenv=False) == 1
    assert "FileNotFoundError" in (tmp_path / "e" / "errors.log").read_text()
    with pytest.raises(SystemExit) as exit_info:
        cli.main(["panel", "--review", str(review), "--eval-dir", "x"], dotenv=False)
    assert exit_info.value.code == 2
    with pytest.raises(SystemExit):
        cli.main([*argv[:-2], "--sample", "0"], dotenv=False)
    capsys.readouterr()
