"""Migration 0002 backfills every existing field into version 1 and seeds sources and settings."""

import uuid

import pytest
import sqlalchemy as sa

from research_agent.web.db.migrate import alembic_config, upgrade


@pytest.fixture
def blank_url(pg_url, pg_engine):
    name = f"m_{uuid.uuid4().hex[:10]}"
    with pg_engine.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
        connection.execute(sa.text(f'create database "{name}"'))
    yield sa.engine.make_url(pg_url).set(database=name).render_as_string(hide_password=False)
    with pg_engine.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
        connection.execute(sa.text(f'drop database "{name}" with (force)'))


def rows(engine, sql, **params):
    with engine.connect() as connection:
        return [tuple(r) for r in connection.execute(sa.text(sql), params)]


def test_upgrade_backfills_existing_fields_into_version_1(blank_url):
    upgrade(blank_url, "0001")
    engine = sa.create_engine(blank_url)
    field_id, criterion_id, run_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    with engine.begin() as connection:
        connection.execute(
            sa.text(
                "insert into fields (id, name, topic) values (:i, 'RAG', 'retrieval augmented generation')"
            ),
            {"i": field_id},
        )
        connection.execute(
            sa.text(
                "insert into criteria (id, field_id, key, question, version, position)"
                " values (:c, :f, 'topic_match', 'Is it on topic?', 1, 0)"
            ),
            {"c": criterion_id, "f": field_id},
        )
        connection.execute(
            sa.text(
                "insert into runs (id, field_id, kind, status, manifest) values (:r, :f, 'research', 'done', '{}')"
            ),
            {"r": run_id, "f": field_id},
        )
    upgrade(blank_url)
    try:
        [(version_id, number, name, topic, sources, note)] = rows(
            engine,
            "select id, version, name, topic, sources, note from field_versions where field_id = :f",
            f=field_id,
        )
        assert (number, name, topic, note) == (1, "RAG", "retrieval augmented generation", "migrated")
        assert sources == {"names": ["europepmc"], "years": {"from": None, "to": None}}
        assert rows(engine, "select kind, field_version_id from criteria") == [("legacy", version_id)]
        assert rows(engine, "select current_version, archived_at from fields") == [(1, None)]
        assert rows(engine, "select field_version_id from runs") == [(version_id,)]
        # every catalogued source gets a row; only the legacy default (Europe PMC) starts enabled
        seeded = rows(engine, "select name, enabled, max_results from sources order by name")
        assert {"arxiv", "europepmc", "openalex"} <= {name for name, _, _ in seeded}
        assert [(name, enabled) for name, enabled, _ in seeded if enabled] == [("europepmc", True)]
        assert {limit for _, _, limit in seeded} == {100}
        assert rows(engine, "select id, contact_email from app_settings") == [(1, None)]
        # topic is no longer unique: a second field may share it (versions own the topic now)
        with engine.begin() as connection:
            connection.execute(
                sa.text(
                    "insert into fields (id, name, topic) values (:i, 'RAG 2', 'retrieval augmented generation')"
                ),
                {"i": uuid.uuid4()},
            )
    finally:
        engine.dispose()


def test_downgrade_to_0001_and_back(blank_url):
    from alembic import command

    upgrade(blank_url)
    command.downgrade(alembic_config(blank_url), "0001")
    engine = sa.create_engine(blank_url)
    try:
        assert "field_versions" not in sa.inspect(engine).get_table_names()
    finally:
        engine.dispose()
    upgrade(blank_url)
