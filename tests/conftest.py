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
