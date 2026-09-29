import hashlib
import json
import sys

import pytest

from research_agent import cli, runner
from research_agent.agents import PROMPT_VERSION
from research_agent.connectors import SourceUnavailable
from research_agent.runner import run_research
from research_agent.schemas import Contract, read_domain

DOMAIN = {
    "schema": 1,
    "field": {"id": "f1", "name": "ML CT-FFR", "version": 3},
    "topic": "deep learning CT-FFR",
    "criteria": {
        "include": [{"key": "i1", "text": "Uses deep learning."}],
        "exclude": [{"key": "e1", "text": "Is a review."}],
    },
    "sources": [{"name": "europepmc", "max_results": 5}, {"name": "arxiv", "max_results": 5}],
    "years": {"from": 2018, "to": None},
}


def write_domain(tmp_path, data=DOMAIN):
    path = tmp_path / "field.json"
    path.write_text(json.dumps(data, indent=1))
    return path


def test_demo_field_run_copies_domain_json_and_records_it(tmp_path):
    source = write_domain(tmp_path)
    spec = read_domain(source)
    run = tmp_path / "run"
    run_research(run, Contract(topic=spec.topic, domain=spec, max_papers=3), domain_file=source)
    assert (run / "domain.json").read_bytes() == source.read_bytes()
    manifest = json.loads((run / "manifest.json").read_text())
    assert manifest["domain"] == {
        "file": "domain.json",
        "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "field": {"id": "f1", "name": "ML CT-FFR", "version": 3},
    }
    assert manifest["prompt_version"] == PROMPT_VERSION
    report = json.loads((run / "report.json").read_text())
    assert report["manifest"]["contract"]["domain"]["years"] == {"from": 2018, "to": None}
    papers = report["state"]["papers"]
    assert len(papers) == 3 and all(p["sources"] == ["arxiv", "europepmc"] for p in papers)
    assert all(
        s["decided_by"] is None and set(s["criteria"]) == {"i1", "e1"}
        for s in report["state"]["screens"].values()
    )


def test_a_field_run_resumes_from_its_saved_contract(tmp_path):
    spec = read_domain(write_domain(tmp_path))
    run = tmp_path / "run"
    assert (
        run_research(run, Contract(topic=spec.topic, domain=spec, max_papers=2), stop_after="discover")
        is None
    )
    result = run_research(run, resume=True)
    assert result["contract"]["domain"]["field"]["version"] == 3 and len(result["ranking"]) == 2


def test_legacy_manifest_has_no_domain(tmp_path):
    run_research(tmp_path / "run", Contract(topic="retrieval augmented generation", max_papers=1))
    assert json.loads((tmp_path / "run" / "manifest.json").read_text())["domain"] is None


def test_source_failure_is_recorded_with_the_source_name(tmp_path, monkeypatch):
    class Down:
        def search(self, query, limit):
            raise SourceUnavailable("openalex")

    monkeypatch.setattr(runner, "make_connector", lambda contract, store: Down())
    spec = read_domain(write_domain(tmp_path))
    with pytest.raises(SourceUnavailable):
        run_research(tmp_path / "run", Contract(topic=spec.topic, domain=spec))
    progress = json.loads((tmp_path / "run" / "progress.json").read_text())
    assert progress["status"] == "failed" and progress["stages"]["discover"] == "failed"
    assert (progress["error_type"], progress["message"]) == ("SourceUnavailable", "openalex")


def test_other_failures_get_the_generic_english_message(tmp_path, monkeypatch):
    class Broken:
        def search(self, query, limit):
            raise RuntimeError("provider said sk-secret")

    monkeypatch.setattr(runner, "make_connector", lambda contract, store: Broken())
    with pytest.raises(RuntimeError):
        run_research(tmp_path / "run", Contract(topic="retrieval augmented generation"))
    progress = json.loads((tmp_path / "run" / "progress.json").read_text())
    assert (
        progress["message"].startswith("The stage did not finish.") and "sk-secret" not in progress["message"]
    )


@pytest.mark.parametrize(
    "call,message",
    [
        (lambda run: run_research(run, resume=True), "There is no saved research in this folder."),
        (
            lambda run: (
                run_research(run, Contract(topic="retrieval augmented generation", max_papers=1)),
                run_research(run, Contract(topic="retrieval augmented generation", max_papers=1)),
            ),
            "This research already exists; resume it or choose a new folder.",
        ),
    ],
)
def test_runner_messages_are_english(tmp_path, call, message):
    with pytest.raises(ValueError, match=message):
        call(tmp_path / "run")


def run_cli(monkeypatch, *argv):
    monkeypatch.setattr(sys, "argv", ["research-agent", *argv])
    monkeypatch.setattr(cli, "load_dotenv", lambda: None)
    cli.main()


def test_cli_runs_a_field_in_demo_mode(tmp_path, monkeypatch, capsys):
    source = write_domain(tmp_path)
    run_cli(monkeypatch, "--domain", str(source), "--run-dir", str(tmp_path / "run"), "--max-papers", "2")
    assert "Report:" in capsys.readouterr().out
    assert (tmp_path / "run" / "domain.json").exists()


@pytest.mark.parametrize(
    "extra,message",
    [
        (["a topic"], "either a topic or --domain"),
        (["--resume"], "do not pass --domain"),
        (["--jev-min-confidence", "0.7"], "thresholds come from domain.json"),
    ],
)
def test_cli_refuses_domain_combinations(tmp_path, monkeypatch, capsys, extra, message):
    source = write_domain(tmp_path)
    with pytest.raises(SystemExit) as exited:
        run_cli(monkeypatch, "--domain", str(source), "--run-dir", str(tmp_path / "run"), *extra)
    assert exited.value.code == 2 and message in capsys.readouterr().err


def test_cli_reports_an_invalid_domain_file(tmp_path, monkeypatch, capsys):
    source = write_domain(tmp_path, {**DOMAIN, "sources": []})
    with pytest.raises(SystemExit) as exited:
        run_cli(monkeypatch, "--domain", str(source), "--run-dir", str(tmp_path / "run"))
    assert exited.value.code == 2
    assert "domain.json is invalid: sources: List should have at least 1 item" in capsys.readouterr().err


def test_cli_still_requires_a_topic_or_a_domain(tmp_path, monkeypatch, capsys):
    with pytest.raises(SystemExit):
        run_cli(monkeypatch, "--run-dir", str(tmp_path / "run"))
    assert "Topic or --domain is required" in capsys.readouterr().err
