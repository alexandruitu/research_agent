import json
import sys
from dataclasses import replace

from research_agent.web.runner import (
    RunSpec,
    build_command,
    child_environment,
    failure_message,
    progress_snapshot,
    read_progress,
    sanitize_error,
)


def spec(tmp_path, **kw):
    return RunSpec(
        topic="t topic; rm -rf /", max_papers=3, mode="demo", jev=False, resume=False, run_dir=tmp_path, **kw
    )


def test_new_run_command_passes_the_topic_as_a_single_argument(tmp_path):
    command = build_command(spec(tmp_path))
    assert command[1:3] == ["-m", "research_agent.cli"]
    assert "t topic; rm -rf /" in command  # one argv element: never interpolated into a shell
    assert (
        command[command.index("--mode") + 1] == "demo" and command[command.index("--max-papers") + 1] == "3"
    )
    assert (
        command[command.index("--run-dir") + 1] == str(tmp_path)
        and "--jev" not in command
        and "--resume" not in command
    )


def test_resume_and_jev_flags(tmp_path):
    resume = build_command(replace(spec(tmp_path), resume=True))
    assert "--resume" in resume and "t topic; rm -rf /" not in resume and "--mode" not in resume
    assert "--jev" in build_command(replace(spec(tmp_path), mode="live", jev=True))


def test_a_topic_that_looks_like_an_option_stays_the_topic(tmp_path, monkeypatch):
    """A member-supplied topic must never be parsed as a pipeline flag (e.g. to move the run folder)."""
    import research_agent.cli as pipeline_cli

    topic = f"--run-dir={tmp_path / 'elsewhere'}"
    command = build_command(replace(spec(tmp_path), topic=topic))
    seen = {}
    monkeypatch.setattr(pipeline_cli, "load_dotenv", lambda *a, **k: None)  # never load the real .env
    monkeypatch.setattr(
        pipeline_cli,
        "run_research",
        lambda run_dir, contract, **kw: seen.update(run_dir=run_dir, contract=contract),
    )
    monkeypatch.setattr(sys, "argv", ["research-agent", *command[3:]])
    pipeline_cli.main()
    assert seen["run_dir"] == tmp_path and seen["contract"].topic == topic and seen["contract"].mode == "demo"


def test_child_environment_keeps_provider_keys_but_not_the_database(monkeypatch):
    monkeypatch.setenv("RESEARCH_WEB_DATABASE_URL", "postgresql://u:secret@h/db")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k1")
    env = child_environment()
    assert "RESEARCH_WEB_DATABASE_URL" not in env and env["ANTHROPIC_API_KEY"] == "k1"
    assert env["PYTHONUNBUFFERED"] == "1"


def test_child_environment_drops_every_web_setting_and_database_credential(monkeypatch):
    monkeypatch.setenv("RESEARCH_WEB_ADMIN_PASSWORD", "admin-password-123")
    monkeypatch.setenv("RESEARCH_WEB_COOKIE_SECURE", "true")
    monkeypatch.setenv("PGPASSWORD", "pg-password-123")
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:pg-password-123@h/db")
    monkeypatch.setenv("RESEARCH_RUNS_DIR", "/runs")
    monkeypatch.setenv("TYPESAFE_API_KEY", "typesafe-key-123")
    env = child_environment()
    assert not [name for name in env if name.startswith("RESEARCH_WEB_")]
    assert "PGPASSWORD" not in env and "DATABASE_URL" not in env
    assert env["RESEARCH_RUNS_DIR"] == "/runs" and env["TYPESAFE_API_KEY"] == "typesafe-key-123"


def test_read_progress_and_snapshot(tmp_path):
    assert read_progress(tmp_path) == {} and progress_snapshot(tmp_path) == {
        "status": None,
        "stages": {},
        "updated_at": None,
    }
    (tmp_path / "progress.json").write_text(
        json.dumps(
            {
                "status": "running",
                "stages": {"plan": "completed", "discover": "running"},
                "updated_at": "2026-09-26T10:00:00+00:00",
                "pid": 1,
            }
        )
    )
    assert progress_snapshot(tmp_path) == {
        "status": "running",
        "stages": {"plan": "completed", "discover": "running"},
        "updated_at": "2026-09-26T10:00:00+00:00",
    }
    (tmp_path / "progress.json").write_text("{ not json")
    assert read_progress(tmp_path) == {}


def test_failure_message_uses_only_the_pipelines_sanitized_fields(tmp_path):
    (tmp_path / "progress.json").write_text(
        json.dumps(
            {
                "status": "failed",
                "stages": {"plan": "completed", "screen": "failed"},
                "error_type": "ValidationError",
                "message": "Etapa nu s-a încheiat.",
            }
        )
    )
    assert failure_message(tmp_path, 1) == "failed at stage 'screen': ValidationError: Etapa nu s-a încheiat."
    assert failure_message(tmp_path / "missing", 3) == "the run process exited with code 3"
    (tmp_path / "progress.json").write_text(json.dumps({"status": "completed"}))
    assert failure_message(tmp_path, 1) == "the run process exited with code 1"


def test_failure_message_is_capped_as_a_whole(tmp_path):
    (tmp_path / "progress.json").write_text(
        json.dumps(
            {
                "status": "failed",
                "stages": {"s" * 200: "failed"},
                "error_type": "E" * 200,
                "message": "m" * 200,
            }
        )
    )
    assert len(failure_message(tmp_path, 1)) <= 300


def test_sanitize_error_redacts_key_values_and_truncates(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-SECRET-VALUE-123")
    monkeypatch.setenv("TYPESAFE_API_KEY", "abc")  # shorter than 8 characters: left alone (would mangle text)
    text = sanitize_error(RuntimeError("provider rejected sk-ant-SECRET-VALUE-123 and abc"))
    assert "SECRET" not in text and text.startswith("RuntimeError:") and "***" in text and "abc" in text
    assert len(sanitize_error(RuntimeError("x" * 1000))) <= 300


def test_sanitize_error_redacts_passwords_tokens_and_the_database_url(monkeypatch):
    monkeypatch.setenv(
        "RESEARCH_WEB_DATABASE_URL", "postgresql+psycopg://app:db%40pass-word-9@db:5432/research"
    )
    monkeypatch.setenv("RESEARCH_WEB_ADMIN_PASSWORD", "admin-password-123")
    monkeypatch.setenv("PGPASSWORD", "pg-password-456")
    monkeypatch.setenv("SOME_SERVICE_TOKEN", "token-value-789")
    message = (
        "connect postgresql+psycopg://app:db%40pass-word-9@db:5432/research failed; raw db@pass-word-9 and db%40pass-word-9; "
        "admin-password-123 pg-password-456 token-value-789"
    )
    text = sanitize_error(RuntimeError(message))
    for secret in ("pass-word-9", "admin-password-123", "pg-password-456", "token-value-789"):
        assert secret not in text
    assert text.startswith("RuntimeError: connect ***")
