"""Migration 0007: eval report kind/config/parent, gold set columns, rating samples and human ratings."""

import uuid

import sqlalchemy as sa
from alembic import command

from research_agent.web.db.migrate import alembic_config, upgrade


def columns(db, table):
    return {c["name"]: c for c in sa.inspect(db.connection()).get_columns(table)}


def test_new_columns_and_tables(db):
    reports = columns(db, "eval_reports")
    assert {"kind", "config", "parent_id", "created_by"} <= set(reports)
    assert reports["gold_set_id"]["nullable"] is True
    assert {"path", "candidates", "positives", "unresolved", "source", "created_by"} <= set(
        columns(db, "gold_sets")
    )
    assert {"paper_ids", "size", "seed", "folder"} <= set(columns(db, "rating_samples"))
    assert {"item_text", "reviewer_version", "answer", "quote"} <= set(columns(db, "human_ratings"))


def test_old_reports_become_screening_and_downgrade_works(pg_url, pg_engine):
    name = f"e_{uuid.uuid4().hex[:10]}"
    with pg_engine.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
        connection.execute(sa.text(f'create database "{name}"'))
    url = sa.engine.make_url(pg_url).set(database=name).render_as_string(hide_password=False)
    try:
        config = alembic_config(url)
        command.upgrade(config, "0006")
        engine = sa.create_engine(url)
        with engine.begin() as c:
            field = c.execute(
                sa.text(
                    "insert into fields (id, name, topic) values (gen_random_uuid(), 'f', 't') returning id"
                )
            ).scalar()
            gold = c.execute(
                sa.text(
                    "insert into gold_sets (id, name, citation, sha256) "
                    "values (gen_random_uuid(), 'g', 'c', 's') returning id"
                )
            ).scalar()
            run = c.execute(
                sa.text(
                    "insert into runs (id, field_id, kind, status, manifest) "
                    "values (gen_random_uuid(), :f, 'eval', 'done', '{}') returning id"
                ),
                {"f": field},
            ).scalar()
            c.execute(
                sa.text(
                    "insert into eval_reports (id, gold_set_id, run_id, metrics) values (gen_random_uuid(), :g, :r, '{}')"
                ),
                {"g": gold, "r": run},
            )
        upgrade(url)
        with engine.connect() as c:
            assert c.execute(sa.text("select kind, config from eval_reports")).one() == ("screening", {})
        command.downgrade(config, "0006")
        assert "kind" not in {c["name"] for c in sa.inspect(engine).get_columns("eval_reports")}
        upgrade(url)
        engine.dispose()
    finally:
        with pg_engine.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
            connection.execute(sa.text(f'drop database "{name}" with (force)'))
