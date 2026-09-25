import json

import pytest
from eval_helpers import europepmc, jev_client, make_gold, row

from research_agent.agents import Evaluator
from research_agent.connectors import EuropePMC
from research_agent.eval import cli
from research_agent.eval.gold import write_gold
from research_agent.eval.screen import write_manifest
from research_agent.jev import JevScreener

SR = """name: toy
citation: Test et al. 2026
topic: deep learning CT-FFR
query: ctffr
included:
  - doi: 10.1000/p1
  - doi: 10.1000/p2
"""


def test_cli_end_to_end_in_demo_mode(tmp_path, monkeypatch, capsys):
    rows = [row(i) for i in range(1, 9)]
    monkeypatch.setattr(cli, "make_connector", lambda store: EuropePMC(store, europepmc({"*": rows})))
    monkeypatch.setattr(
        cli, "make_jev", lambda store: JevScreener(store, "k", client=jev_client({1: 0.97, 2: 0.9, 3: 0.02}))
    )
    sr, gold, run = tmp_path / "sr.yaml", tmp_path / "gold" / "toy.json", tmp_path / "run"
    sr.write_text(SR)

    assert cli.main(["build-gold", str(sr), "-o", str(gold)], dotenv=False) == 0
    assert cli.main(["screen", str(gold), "--run-dir", str(run), "--mode", "demo"], dotenv=False) == 0
    assert cli.main(["agreement", str(gold), "--run-dir", str(run), "--limit", "2"], dotenv=False) == 0
    assert cli.main(["report", str(run), "--target-recall", "0.9"], dotenv=False) == 0

    report = json.loads((run / "metrics.json").read_text())
    assert report["counts"]["positives_screened"] == 2 and report["agreement"]["n"] == 4
    assert "## Screening recall" in (run / "metrics.md").read_text()
    assert "Gold:" in capsys.readouterr().out


def test_cli_failure_writes_errors_log_and_returns_1(tmp_path, capsys):
    run = tmp_path / "nope"
    assert cli.main(["report", str(run)], dotenv=False) == 1
    log = (run / "errors.log").read_text()
    assert "ValueError" in log and "no eval run" in log
    assert "errors.log" in capsys.readouterr().err


def test_make_evaluator_demo_and_live(tmp_path, monkeypatch):
    from research_agent.storage import Store

    store = Store(tmp_path)
    assert cli.make_evaluator(store, "demo").mode == "demo"
    live = cli.make_evaluator(store, "live", {"screen": "m-1"})
    assert (live.mode, live.models) == ("live", {"screen": "m-1"})
    monkeypatch.setattr(cli, "live_models", lambda: {"screen": "from-env"})
    assert cli.make_evaluator(store, "live").models == {"screen": "from-env"}


def test_agreement_uses_the_mode_and_models_of_the_screening_run(tmp_path, monkeypatch):
    gold = write_gold(make_gold(n=4, positive_ids=(1,)), tmp_path / "g.json")
    run = tmp_path / "run"
    models = {"extract": "model-x", "review_a": "model-a", "review_b": "model-b", "adjudicate": "model-c"}
    write_manifest(
        run,
        gold_path=tmp_path / "g.json",
        gold=gold,
        mode="live",
        models=models,
        jev_model="jev-latest",
        screened={"screened": 4, "jev_model_versions": ["jev-1.13.0"]},
    )
    seen = []

    class Recording(Evaluator):
        def __init__(self, store, mode, models):
            super().__init__(store, "demo")  # runs offline of any provider; only the arguments matter
            seen.append((mode, models))

    monkeypatch.setattr(
        cli, "make_evaluator", lambda store, mode, models=None: Recording(store, mode, models)
    )
    assert (
        cli.main(["agreement", str(tmp_path / "g.json"), "--run-dir", str(run), "--limit", "1"], dotenv=False)
        == 0
    )
    assert seen == [("live", models)]


def test_agreement_rejects_a_gold_file_that_differs_from_the_screened_one(tmp_path):
    other = write_gold(make_gold(n=4, positive_ids=(1,), name="other"), tmp_path / "other.json")
    gold = write_gold(make_gold(n=4, positive_ids=(1, 2)), tmp_path / "g.json")
    run = tmp_path / "run"
    write_manifest(
        run,
        gold_path=tmp_path / "g.json",
        gold=gold,
        mode="demo",
        models={},
        jev_model="jev-latest",
        screened={"screened": 4, "jev_model_versions": []},
    )
    assert cli.main(["agreement", str(tmp_path / "other.json"), "--run-dir", str(run)], dotenv=False) == 1
    assert "differs" in (run / "errors.log").read_text() and other.content_sha256 != gold.content_sha256


def test_negative_limit_is_rejected_by_argparse(tmp_path):
    with pytest.raises(SystemExit) as exit_info:
        cli.main(["agreement", "g.json", "--run-dir", str(tmp_path), "--limit", "-1"], dotenv=False)
    assert exit_info.value.code == 2
    assert cli.build_parser().parse_args(["agreement", "g.json", "--run-dir", "r", "--limit", "0"]).limit == 0


def test_dotenv_is_loaded_only_when_requested(tmp_path, monkeypatch):
    loaded = []
    monkeypatch.setattr(cli, "load_dotenv", lambda path: loaded.append(path))
    cli.main(["report", str(tmp_path / "nope")], dotenv=False)
    assert loaded == []
    cli.main(["report", str(tmp_path / "nope")])
    assert loaded == [".env"]
