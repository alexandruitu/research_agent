import json

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
