"""Migration 0003 seeds the default review panel and review settings version 1."""

import uuid

import pytest
import sqlalchemy as sa

from research_agent.panel import DEFAULT_EDITOR, default_panel
from research_agent.schemas import ReviewSpec, Thresholds
from research_agent.web.db.migrate import alembic_config, upgrade


@pytest.fixture
def blank_url(pg_url, pg_engine):
    name = f"r_{uuid.uuid4().hex[:10]}"
    with pg_engine.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
        connection.execute(sa.text(f'create database "{name}"'))
    yield sa.engine.make_url(pg_url).set(database=name).render_as_string(hide_password=False)
    with pg_engine.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
        connection.execute(sa.text(f'drop database "{name}" with (force)'))


def rows(engine, sql):
    with engine.connect() as connection:
        return [tuple(r) for r in connection.execute(sa.text(sql))]


def test_upgrade_seeds_the_default_panel_and_settings_v1(blank_url):
    upgrade(blank_url, "0002")
    engine = sa.create_engine(blank_url)
    try:
        with engine.begin() as connection:
            connection.execute(sa.text("update app_settings set contact_email = 'team@example.org'"))
        upgrade(blank_url)
        profiles = rows(
            engine, "select key, current_version, archived_at from reviewer_profiles order by key"
        )
        assert profiles == [("clinician", 1, None), ("methodologist", 1, None), ("statistician", 1, None)]
        versions = rows(
            engine,
            "select p.key, v.version, v.name, v.perspective, v.items, v.model, v.note from reviewer_versions v"
            " join reviewer_profiles p on p.id = v.profile_id",
        )
        by_key = {v[0]: v for v in versions}
        for reviewer in default_panel():
            _key, number, name, perspective, items, model, note = by_key[reviewer["key"]]
            assert (number, name, perspective, model, note) == (
                1,
                reviewer["name"],
                reviewer["perspective"],
                None,
                "default",
            )
            assert items == reviewer["items"]
        [(number, models, screening, fulltext, panel, editor, note, imported)] = rows(
            engine,
            "select version, models, screening, fulltext, default_panel, editor, note, imported"
            " from settings_versions",
        )
        assert (number, note, imported) == (1, "default", False)
        assert models == {"plan": None, "screen": None, "screen_criteria": None, "extract": None}
        assert screening == Thresholds().model_dump()
        assert fulltext == {
            "sources": ["pmc_oa", "unpaywall", "upload"],
            "contact": "team@example.org",
            "max_chars": 60000,
            "upload_max_mb": 30,
        }
        assert panel == ["methodologist", "clinician", "statistician"] and editor == DEFAULT_EDITOR
        spec = {
            "schema": 1,
            "panel": [dict(r, model=None) for r in default_panel()],
            "editor": editor,
            "screening": screening,
            "fulltext": {k: v for k, v in fulltext.items() if k != "upload_max_mb"},
        }
        ReviewSpec.model_validate(spec)
    finally:
        engine.dispose()


def test_without_a_contact_unpaywall_is_left_out_and_downgrade_works(blank_url):
    from alembic import command

    upgrade(blank_url)
    engine = sa.create_engine(blank_url)
    try:
        [(fulltext,)] = rows(engine, "select fulltext from settings_versions")
        assert fulltext["sources"] == ["pmc_oa", "upload"] and fulltext["contact"] is None
        command.downgrade(alembic_config(blank_url), "0002")
        tables = sa.inspect(engine).get_table_names()
        assert "reviewer_profiles" not in tables and "paper_files" not in tables
    finally:
        engine.dispose()
    upgrade(blank_url)
