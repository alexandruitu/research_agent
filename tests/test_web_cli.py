import json
from typing import ClassVar

import pytest
import sqlalchemy as sa
from sqlalchemy import func, select
from web_fixtures import make_demo_run, make_eval_run

from research_agent.web.cli import detect_kind, find_import_targets, main
from research_agent.web.db.models import Paper, Run, User
from research_agent.web.settings import load_settings


@pytest.fixture
def cli_settings(fresh_db_url, tmp_path):
    make_demo_run(tmp_path / "runs" / "demo")
    make_eval_run(tmp_path)
    return load_settings(
        {
            "RESEARCH_WEB_DATABASE_URL": fresh_db_url,
            "RESEARCH_RUNS_DIR": str(tmp_path / "runs"),
            "RESEARCH_EVALS_DIR": str(tmp_path / "evals"),
            "RESEARCH_GOLD_DIR": str(tmp_path / "gold"),
        }
    )


def scalar(url, statement):
    engine = sa.create_engine(url)
    try:
        with engine.connect() as connection:
            return connection.scalar(statement)
    finally:
        engine.dispose()


def test_detect_kind_and_targets(cli_settings, tmp_path):
    assert detect_kind(tmp_path / "runs" / "demo") == "research"
    assert detect_kind(tmp_path / "evals" / "toy") == "eval"
    assert detect_kind(tmp_path) is None
    targets = find_import_targets(cli_settings)
    assert [(kind, path.name) for kind, path in targets] == [("research", "demo"), ("eval", "toy")]


def test_import_all_is_idempotent_and_reports_each_run(cli_settings, capsys):
    assert main(["import", "--all"], settings=cli_settings) == 0
    out = capsys.readouterr().out
    assert "created" in out and "demo" in out and "toy" in out
    assert scalar(cli_settings.database_url, select(func.count()).select_from(Run)) == 2
    assert scalar(cli_settings.database_url, select(func.count()).select_from(Paper)) == 6 + 12
    assert main(["import", "--all"], settings=cli_settings) == 0
    assert capsys.readouterr().out.count("unchanged") == 2


def test_import_of_a_bad_folder_fails_and_continues(cli_settings, tmp_path, capsys):
    broken = tmp_path / "runs" / "broken"
    broken.mkdir()
    (broken / "report.json").write_text(json.dumps({"state": {}, "manifest": {}}))
    assert main(["import", "--all"], settings=cli_settings) == 1
    out = capsys.readouterr().out
    assert "FAILED" in out and "broken" in out and "created" in out  # the good runs were still imported


def test_create_admin_reads_the_password_from_the_environment(cli_settings, monkeypatch):
    monkeypatch.setenv("RESEARCH_WEB_ADMIN_PASSWORD", "correct horse battery")
    assert main(["create-admin", "--email", "Root@Example.org", "--name", "Root"], settings=cli_settings) == 0
    assert (
        scalar(cli_settings.database_url, select(User.role).where(User.email == "root@example.org"))
        == "admin"
    )
    assert (
        main(["create-admin", "--email", "root@example.org", "--name", "Root"], settings=cli_settings) == 1
    )  # exists
    monkeypatch.setenv("RESEARCH_WEB_ADMIN_PASSWORD", "short")
    assert main(["create-admin", "--email", "b@example.org", "--name", "B"], settings=cli_settings) == 1


def test_openapi_dump_lists_the_routes_and_no_secrets(cli_settings, tmp_path):
    out = tmp_path / "openapi.json"
    assert main(["openapi", "-o", str(out)], settings=cli_settings) == 0
    schema = json.loads(out.read_text())
    assert "/api/v1/auth/login" in schema["paths"] and "/api/v1/runs/{run_id}/papers" in schema["paths"]
    assert "PaperRow" in schema["components"]["schemas"] and cli_settings.database_url not in out.read_text()


def test_migrate_is_repeatable(cli_settings):
    assert main(["migrate"], settings=cli_settings) == 0
    assert main(["migrate"], settings=cli_settings) == 0


def test_an_unexpected_import_error_is_reported_sanitized_and_the_others_continue(
    cli_settings, monkeypatch, capsys
):
    from research_agent.web import cli

    sentinel = "sk-ant-SENTINEL-cli-1234567890"
    monkeypatch.setenv("ANTHROPIC_API_KEY", sentinel)

    def explode(db, path, **kwargs):
        raise RuntimeError(f"disk said no, key {sentinel}")

    monkeypatch.setattr(cli, "import_research_run", explode)
    assert main(["import", "--all"], settings=cli_settings) == 1
    out = capsys.readouterr().out
    assert "FAILED" in out and "demo: RuntimeError: disk said no" in out
    assert sentinel not in out
    assert "created" in out and "toy" in out  # the eval run was still imported
    assert scalar(cli_settings.database_url, select(func.count()).select_from(Run)) == 1


def test_worker_once_drains_the_queue_and_exits(cli_settings, tmp_path):
    from research_agent.web.auth import create_user
    from research_agent.web.db.models import Job
    from research_agent.web.db.session import make_engine, make_session_factory
    from research_agent.web.jobs import enqueue

    assert main(["worker", "--once"], settings=cli_settings) == 0  # empty queue: exits at once
    factory = make_session_factory(make_engine(cli_settings.database_url))
    with factory() as db:
        admin = create_user(
            db, email="a@example.org", name="A", role="admin", password="correct horse battery"
        )
        enqueue(db, "import", {"kind": "research", "name": "demo"}, admin.id)
        db.commit()
    assert main(["worker", "--once"], settings=cli_settings) == 0
    assert scalar(cli_settings.database_url, select(Job.status)) == "done"
    assert scalar(cli_settings.database_url, select(func.count()).select_from(Run)) == 1


def test_serve_and_dev_are_registered(capsys):
    from research_agent.web.cli import build_parser

    parser = build_parser()
    assert parser.parse_args(["serve", "--port", "9000"]).port == 9000
    dev = parser.parse_args(["dev", "--with-worker", "--allow-demo"])
    assert dev.with_worker is True and dev.allow_demo is True


class FakeWorker:
    """Stands in for the worker in CLI tests; `behaviour(worker)` runs inside drain/run_forever."""

    behaviour = staticmethod(lambda worker: None)
    made: ClassVar[list] = []

    def __init__(self, settings):
        import threading

        self.stop_requested = threading.Event()
        self.worker_id = "fake"
        FakeWorker.made.append(self)

    def request_stop(self):
        self.stop_requested.set()

    def drain(self):
        FakeWorker.behaviour(self)

    def run_forever(self, stop=lambda: False):
        FakeWorker.behaviour(self)


@pytest.fixture
def fake_worker(monkeypatch):
    from research_agent.web import cli

    FakeWorker.made = []
    monkeypatch.setattr(cli, "Worker", FakeWorker)
    return FakeWorker


def test_worker_once_reports_an_error_on_one_redacted_line(cli_settings, fake_worker, monkeypatch, capsys):
    sentinel = "sk-ant-SENTINEL-once-1234567890"
    monkeypatch.setenv("ANTHROPIC_API_KEY", sentinel)

    def explode(worker):
        raise RuntimeError(f"database unreachable\nkey {sentinel}")

    monkeypatch.setattr(fake_worker, "behaviour", staticmethod(explode))
    assert main(["worker", "--once"], settings=cli_settings) == 1
    out = capsys.readouterr().out
    assert out.startswith("FAILED: RuntimeError: database unreachable") and out.count("\n") == 1
    assert sentinel not in out


@pytest.mark.parametrize("once", [True, False])
@pytest.mark.parametrize("signum", ["SIGTERM", "SIGINT"])
def test_a_signal_asks_the_worker_to_stop_instead_of_killing_it(
    cli_settings, fake_worker, monkeypatch, once, signum
):
    import signal

    signum = getattr(signal, signum)
    before = signal.getsignal(signum)

    def receive(worker):
        signal.raise_signal(signum)  # what `docker stop` or Ctrl-C does
        assert worker.stop_requested.is_set()

    monkeypatch.setattr(fake_worker, "behaviour", staticmethod(receive))
    assert main(["worker", *(["--once"] if once else [])], settings=cli_settings) == 0
    assert fake_worker.made[0].stop_requested.is_set()
    assert signal.getsignal(signum) is before  # the handlers are put back


def test_dev_with_worker_stops_and_joins_the_worker_on_shutdown(
    cli_settings, fake_worker, monkeypatch, tmp_path
):
    import threading

    import pgserver
    import uvicorn

    from research_agent.web import cli

    class Server:
        def get_uri(self):
            return cli_settings.database_url

    seen, loaded = {}, []
    monkeypatch.setattr(pgserver, "get_server", lambda *a, **k: Server())
    monkeypatch.setattr(cli, "upgrade", lambda url: None)
    monkeypatch.setattr(cli, "create_app", lambda settings: object())
    monkeypatch.setattr(cli, "load_dotenv", lambda *a, **k: loaded.append(True))
    monkeypatch.setattr(fake_worker, "behaviour", staticmethod(lambda worker: worker.stop_requested.wait(5)))

    def serve(app, **kwargs):
        [thread] = [t for t in threading.enumerate() if t.name == "dev-worker"]
        seen.update(thread=thread, alive=thread.is_alive(), daemon=thread.daemon)

    monkeypatch.setattr(uvicorn, "run", serve)
    assert main(["dev", "--data-dir", str(tmp_path / "pg"), "--with-worker"]) == 0
    assert seen["alive"] and seen["daemon"] is False
    assert fake_worker.made[0].stop_requested.is_set() and not seen["thread"].is_alive()  # stopped, joined
    assert loaded == [True]  # the worker's provider keys come from .env, only with --with-worker

    loaded.clear()
    monkeypatch.setattr(uvicorn, "run", lambda app, **kwargs: None)
    assert main(["dev", "--data-dir", str(tmp_path / "pg")]) == 0
    assert loaded == []


def test_the_real_worker_process_exits_cleanly_on_sigterm(cli_settings):
    import os
    import signal
    import subprocess
    import sys

    env = {k: v for k, v in os.environ.items() if not k.endswith("_API_KEY")}
    env.update(
        RESEARCH_WEB_DATABASE_URL=cli_settings.database_url,
        RESEARCH_RUNS_DIR=str(cli_settings.runs_dir),
        RESEARCH_EVALS_DIR=str(cli_settings.evals_dir),
        RESEARCH_GOLD_DIR=str(cli_settings.gold_dir),
        PYTHON_DOTENV_DISABLED="1",
        PYTHONUNBUFFERED="1",
    )
    process = subprocess.Popen(
        [sys.executable, "-m", "research_agent.web.cli", "worker"], env=env, stdout=subprocess.PIPE, text=True
    )
    try:
        assert "started" in process.stdout.readline()
        process.send_signal(signal.SIGTERM)
        assert process.wait(timeout=20) == 0
    finally:
        process.kill()
        process.stdout.close()
