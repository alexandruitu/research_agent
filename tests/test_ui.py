import json
from pathlib import Path
from unittest.mock import Mock

import pytest
from streamlit.testing.v1 import AppTest

from research_agent import jobs
from research_agent.runner import STAGES, is_running, read_json, run_lock, run_research
from research_agent.schemas import Contract

APP = Path(jobs.__file__).with_name("ui.py")


def test_runner_progress_pause_resume_and_report(tmp_path):
    assert run_research(tmp_path, Contract(topic="test research", max_papers=2), stop_after="extract") is None
    progress = read_json(tmp_path / "progress.json")
    assert progress["status"] == "paused"
    assert progress["stages"]["extract"] == "completed"
    result = run_research(tmp_path, resume=True)
    assert len(result["ranking"]) == 2
    progress = read_json(tmp_path / "progress.json")
    assert progress["status"] == "completed"
    assert set(progress["stages"]) == set(STAGES)
    assert (tmp_path / "report.md").exists()


def test_lock_blocks_duplicate_workers(tmp_path):
    with run_lock(tmp_path):
        assert is_running(tmp_path)
        with pytest.raises(ValueError, match="deja"):
            run_research(tmp_path, Contract(topic="test topic"))
    assert not is_running(tmp_path)


def test_failed_worker_persists_safe_error(tmp_path, monkeypatch):
    def fail(*args):
        raise RuntimeError("secret-token-do-not-write")

    monkeypatch.setattr("research_agent.runner.DemoConnector.search", fail)
    with pytest.raises(RuntimeError):
        run_research(tmp_path, Contract(topic="test research"))
    progress = (tmp_path / "progress.json").read_text()
    assert "secret-token-do-not-write" not in progress
    assert json.loads(progress)["status"] == "failed"
    assert json.loads(progress)["stages"]["discover"] == "failed"


def test_subprocess_environment_and_no_secrets_on_disk(tmp_path, monkeypatch):
    popen = Mock(return_value=Mock(poll=Mock(return_value=None)))
    monkeypatch.setattr(jobs.subprocess, "Popen", popen)
    monkeypatch.setenv("RESEARCH_REVIEWER_B_MODEL", "old:old")
    jobs.launch(
        tmp_path,
        Contract(topic="test research", mode="live"),
        models={"default": "anthropic:test", "review_b": ""},
        credentials={"ANTHROPIC_API_KEY": "not-a-real-secret"},
    )
    args, kwargs = popen.call_args
    assert "not-a-real-secret" not in str(args)
    assert kwargs["env"]["ANTHROPIC_API_KEY"] == "not-a-real-secret"
    assert kwargs["env"]["RESEARCH_REVIEWER_B_MODEL"] == "anthropic:test"
    assert not list(tmp_path.glob("*.json"))
    with pytest.raises(ValueError, match="deja"):
        jobs.launch(tmp_path, Contract(topic="test research"))
    jobs.PROCESSES.pop(str(tmp_path.resolve()))


def test_results_interface_renders_and_filters(tmp_path, monkeypatch):
    monkeypatch.setenv("RESEARCH_RUNS_DIR", str(tmp_path))
    at = AppTest.from_file(str(APP)).run()
    assert not at.exception
    assert any("retrieval augmented generation" in title.value for title in at.title)
    assert len(at.metric) == 4
    assert len(at.tabs) == 3
    at.slider[0].set_value(100).run()
    assert not at.exception
    assert any("filtrul" in item.value for item in at.info)


def test_configuration_validation_and_demo_launch(tmp_path, monkeypatch):
    monkeypatch.setenv("RESEARCH_RUNS_DIR", str(tmp_path))
    fake = Mock()
    monkeypatch.setattr(jobs, "launch", fake)
    at = AppTest.from_file(str(APP)).run()
    next(b for b in at.button if "Cercetare nouă" in b.label).click().run()
    assert not at.exception
    at.text_area[0].set_value("x")
    next(b for b in at.button if "Pornește" in b.label).click().run()
    assert at.error
    assert not fake.called
    at.text_area[0].set_value("test topic")
    next(b for b in at.button if "Pornește" in b.label).click().run()
    assert fake.call_count == 1
    assert fake.call_args.args[1].topic == "test topic"
    assert read_json(tmp_path / "ui-settings.json")["topic"] == "test topic"
