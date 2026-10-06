"""Migration 0006: every registry source has a row; key status columns; wider text_source, text_licence."""

import uuid

import sqlalchemy as sa
from alembic import command

from research_agent.sources import REGISTRY
from research_agent.web.db.migrate import alembic_config, upgrade


def test_every_registry_source_has_a_row_and_only_europepmc_is_enabled(db):
    rows = dict(db.execute(sa.text("select name, enabled from sources")).all())
    assert set(rows) == set(REGISTRY)
    assert {name for name, on in rows.items() if on} == {"europepmc"}
    status = db.execute(sa.text("select key_present, key_accepted, key_detail from sources limit 1")).one()
    assert status == (False, None, "")


def test_text_source_fits_the_longest_resolver_and_text_licence_is_stored(db):
    columns = {c["name"]: c for c in sa.inspect(db.connection()).get_columns("paper_reviews")}
    assert columns["text_source"]["type"].length >= len("semantic_scholar_oa")
    assert columns["text_licence"]["nullable"] is True


def test_upgrade_and_downgrade(pg_url, pg_engine):
    name = f"s_{uuid.uuid4().hex[:10]}"
    with pg_engine.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
        connection.execute(sa.text(f'create database "{name}"'))
    url = sa.engine.make_url(pg_url).set(database=name).render_as_string(hide_password=False)
    try:
        upgrade(url)
        engine = sa.create_engine(url)
        command.downgrade(alembic_config(url), "0005")
        with engine.connect() as c:
            assert {r[0] for r in c.execute(sa.text("select name from sources"))} == {
                "europepmc",
                "openalex",
                "arxiv",
            }
        assert "text_licence" not in {c["name"] for c in sa.inspect(engine).get_columns("paper_reviews")}
        upgrade(url)
        engine.dispose()
    finally:
        with pg_engine.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
            connection.execute(sa.text(f'drop database "{name}" with (force)'))
