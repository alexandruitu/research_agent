import json

import pytest
from eval_helpers import StubEvaluator, jev_client, jev_criteria_client, make_gold

from research_agent.agents import Evaluator
from research_agent.eval import cli
from research_agent.eval.gold import write_gold
from research_agent.eval.report import build_report
from research_agent.eval.screen import run_screen, write_manifest
from research_agent.jev import JevScreener
from research_agent.storage import Store

DOMAIN = {
    "schema": 1,
    "field": {"id": "f1", "name": "ML CT-FFR", "version": 1},
    "topic": "deep learning CT-FFR",
    "criteria": {
        "include": [{"key": "i1", "text": "Uses deep learning."}],
        "exclude": [{"key": "e1", "text": "Is a review."}],
    },
    "sources": [{"name": "europepmc"}],
}
# Positives 1-4 satisfy i1 and are not reviews; 5 is a review; 6 fails i1; others are unsure.
P = {1: (0.97, 0.02), 2: (0.95, 0.1), 3: (0.9, 0.05), 4: (0.6, 0.1), 5: (0.9, 0.99), 6: (0.01, 0.1)}


def probability(index, key):
    return P.get(index, (0.5, 0.5))[0 if key == "i1" else 1]


def test_cli_screens_and_reports_a_field(tmp_path, monkeypatch, capsys):
    gold, run, field = tmp_path / "toy.json", tmp_path / "run", tmp_path / "field.json"
    write_gold(make_gold(n=8), gold)
    field.write_text(json.dumps(DOMAIN))
    client = jev_criteria_client(probability)
    monkeypatch.setattr(cli, "make_jev", lambda store: JevScreener(store, "k", client=client))
    args = ["screen", str(gold), "--run-dir", str(run), "--mode", "demo", "--field", str(field)]
    assert cli.main(args, dotenv=False) == 0
    assert len(client.calls) == 8 and all(keys == ["e1", "i1"] for _i, keys in client.calls)
    manifest = json.loads((run / "manifest.json").read_text())
    assert manifest["field"]["field"]["name"] == "ML CT-FFR" and len(manifest["field_sha256"]) == 64
    assert cli.main(["report", str(run)], dotenv=False) == 0
    report = json.loads((run / "metrics.json").read_text())
    assert report["counts"]["screened"] == 8 and report["run"]["field"] == DOMAIN["field"]
    assert "Screened 8 candidates" in capsys.readouterr().out


def test_a_run_dir_refuses_a_different_field(tmp_path, monkeypatch):
    gold, run, field = tmp_path / "toy.json", tmp_path / "run", tmp_path / "field.json"
    write_gold(make_gold(n=2), gold)
    field.write_text(json.dumps(DOMAIN))
    monkeypatch.setattr(
        cli, "make_jev", lambda store: JevScreener(store, "k", client=jev_criteria_client(probability))
    )
    base = ["screen", str(gold), "--run-dir", str(run), "--mode", "demo"]
    assert cli.main([*base, "--field", str(field)], dotenv=False) == 0
    changed = {**DOMAIN, "topic": "another field topic"}
    field.write_text(json.dumps(changed))
    assert cli.main([*base, "--field", str(field)], dotenv=False) == 1
    assert "different field" in (run / "errors.log").read_text()


def test_report_reads_a_run_screened_under_an_older_prompt_version(tmp_path):
    gold_path, run = tmp_path / "toy.json", tmp_path / "run"
    gold = write_gold(make_gold(n=6), gold_path)
    store = Store(run)
    old = StubEvaluator(store, exclude={"MED:5"}, prompt_version="m1.1")
    jev = JevScreener(store, "k", client=jev_client({1: 0.97, 2: 0.9, 3: 0.02}))
    screened = run_screen(gold, store, old, jev)
    write_manifest(
        run, gold_path=gold_path, gold=gold, mode="demo", models={}, jev_model="jev-latest", screened=screened
    )
    manifest = json.loads((run / "manifest.json").read_text())
    manifest["prompt_version"] = "m1.1"
    (run / "manifest.json").write_text(json.dumps(manifest))
    report = build_report(run)
    assert report["counts"]["screened"] == 6 and report["run"]["prompt_version"] == "m1.1"
    with pytest.raises(Exception, match="missing cached calls"):
        manifest["prompt_version"] = "m1.2"
        (run / "manifest.json").write_text(json.dumps(manifest))
        build_report(run)


def test_legacy_eval_manifest_has_no_field(tmp_path):
    gold_path, run = tmp_path / "toy.json", tmp_path / "run"
    gold = write_gold(make_gold(n=2), gold_path)
    store = Store(run)
    screened = run_screen(gold, store, Evaluator(store), JevScreener(store, "k", client=jev_client({})))
    data = write_manifest(
        run, gold_path=gold_path, gold=gold, mode="demo", models={}, jev_model="m", screened=screened
    )
    assert data["field"] is None and data["field_sha256"] is None
