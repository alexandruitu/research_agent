"""Shared fixtures. Web tests use a real PostgreSQL 16 from the pip package `pgserver`."""

import pytest

pgserver = pytest.importorskip(
    "pgserver", reason="install the web-dev extra: pip install -e '.[web,web-dev]'"
)
sa = pytest.importorskip("sqlalchemy")


@pytest.fixture(scope="session")
def pg_url(tmp_path_factory):
    server = pgserver.get_server(tmp_path_factory.mktemp("pgdata"), cleanup_mode="delete")
    yield server.get_uri().replace("postgresql://", "postgresql+psycopg://", 1)
    server.cleanup()


@pytest.fixture(scope="session")
def pg_engine(pg_url):
    engine = sa.create_engine(pg_url)
    yield engine
    engine.dispose()


@pytest.fixture(scope="session")
def migrated_engine(pg_url, pg_engine):
    from research_agent.web.db.migrate import upgrade

    upgrade(pg_url)
    return pg_engine


@pytest.fixture
def db(migrated_engine):
    """Each test runs inside a transaction that is rolled back afterwards."""
    from sqlalchemy.orm import Session

    connection = migrated_engine.connect()
    outer = connection.begin()
    session = Session(bind=connection, join_transaction_mode="create_savepoint", expire_on_commit=False)
    yield session
    session.close()
    outer.rollback()
    connection.close()


PASSWORD = "correct horse battery"


@pytest.fixture
def settings(tmp_path, pg_url):
    from research_agent.web.settings import load_settings

    return load_settings(
        {
            "RESEARCH_WEB_DATABASE_URL": pg_url,
            "RESEARCH_RUNS_DIR": str(tmp_path / "runs"),
            "RESEARCH_EVALS_DIR": str(tmp_path / "evals"),
            "RESEARCH_GOLD_DIR": str(tmp_path / "gold"),
            "RESEARCH_WEB_COOKIE_SECURE": "false",
        }
    )


@pytest.fixture
def app(settings, db):
    from research_agent.web.api.app import create_app
    from research_agent.web.api.deps import get_db

    application = create_app(settings, session_factory=lambda: db)
    application.dependency_overrides[get_db] = lambda: db
    return application


@pytest.fixture
def client(app):
    from fastapi.testclient import TestClient

    return TestClient(app)


@pytest.fixture
def users(db):
    from research_agent.web.auth import create_user

    made = {
        role: create_user(db, email=f"{role}@example.org", name=role.title(), role=role, password=PASSWORD)
        for role in ("viewer", "member", "admin")
    }
    db.commit()
    return made


@pytest.fixture
def sign_in(app, users):
    """sign_in(role) -> (client, csrf_headers); each call gets its own cookie jar."""
    from fastapi.testclient import TestClient

    def go(role):
        c = TestClient(app)
        r = c.post("/api/v1/auth/login", json={"email": f"{role}@example.org", "password": PASSWORD})
        assert r.status_code == 200, r.text
        return c, {"X-CSRF-Token": r.json()["csrf_token"]}

    return go


@pytest.fixture
def imported(db, tmp_path):
    """A demo research run and a toy eval run imported into the database (folders live in the roots)."""
    from web_fixtures import make_demo_run, make_eval_run

    from research_agent.web.importer.evals import import_eval_run
    from research_agent.web.importer.research import import_research_run

    research = import_research_run(db, make_demo_run(tmp_path / "runs" / "demo"))
    eval_dir, _gold, report = make_eval_run(tmp_path)
    evaluated = import_eval_run(db, eval_dir)
    db.commit()
    return {"research": research.run_id, "eval": evaluated.run_id, "report": report}


@pytest.fixture
def fresh_db_url(pg_url, pg_engine):
    """A brand-new migrated database on the shared server, dropped after the test."""
    import uuid

    from research_agent.web.db.migrate import upgrade

    name = f"t_{uuid.uuid4().hex[:10]}"
    with pg_engine.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
        connection.execute(sa.text(f'create database "{name}"'))
    url = sa.engine.make_url(pg_url).set(database=name).render_as_string(hide_password=False)
    upgrade(url)
    yield url
    with pg_engine.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
        connection.execute(sa.text(f'drop database "{name}" with (force)'))
