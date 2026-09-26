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
