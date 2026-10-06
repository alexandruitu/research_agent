"""Migration 0008: run name, note, pin and start time; the job cancel flag."""

import uuid

import sqlalchemy as sa
from alembic import command

from research_agent.web.db.migrate import alembic_config, upgrade


def test_upgrade_and_downgrade(pg_url, pg_engine):
    name = f"r_{uuid.uuid4().hex[:10]}"
    with pg_engine.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
        connection.execute(sa.text(f'create database "{name}"'))
    url = sa.engine.make_url(pg_url).set(database=name).render_as_string(hide_password=False)
    try:
        upgrade(url)
        engine = sa.create_engine(url)
        runs = {c["name"]: c for c in sa.inspect(engine).get_columns("runs")}
        assert {"name", "note", "pinned", "started_at"} <= set(runs)
        assert not runs["pinned"]["nullable"] and not runs["note"]["nullable"]
        jobs = {c["name"] for c in sa.inspect(engine).get_columns("jobs")}
        assert "cancel_requested" in jobs
        engine.dispose()
        command.downgrade(alembic_config(url), "0007")
        engine = sa.create_engine(url)
        assert "pinned" not in {c["name"] for c in sa.inspect(engine).get_columns("runs")}
        assert "cancel_requested" not in {c["name"] for c in sa.inspect(engine).get_columns("jobs")}
        engine.dispose()
    finally:
        with pg_engine.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
            connection.execute(sa.text(f'drop database "{name}" with (force)'))
