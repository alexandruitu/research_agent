"""Migration 0005: the team library tables."""

import uuid

import pytest
import sqlalchemy as sa
from alembic import command

from research_agent.web.db.migrate import alembic_config, upgrade

TABLES = {
    "collections",
    "library_items",
    "library_item_collections",
    "library_tags",
    "library_item_tags",
    "library_events",
}


def test_upgrade_and_downgrade(pg_url, pg_engine):
    name = f"l_{uuid.uuid4().hex[:10]}"
    with pg_engine.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
        connection.execute(sa.text(f'create database "{name}"'))
    url = sa.engine.make_url(pg_url).set(database=name).render_as_string(hide_password=False)
    try:
        upgrade(url)
        engine = sa.create_engine(url)
        assert TABLES <= set(sa.inspect(engine).get_table_names())
        command.downgrade(alembic_config(url), "0004")
        assert not TABLES & set(sa.inspect(engine).get_table_names())
        upgrade(url)
        engine.dispose()
    finally:
        with pg_engine.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
            connection.execute(sa.text(f'drop database "{name}" with (force)'))


def test_collection_names_are_unique_ignoring_case(db):
    from research_agent.web.db.models import Collection

    db.add(Collection(name="Stenosis"))
    db.flush()
    db.add(Collection(name="stenosis"))
    with pytest.raises(sa.exc.IntegrityError):
        db.flush()
    db.rollback()


def test_one_library_item_per_paper(db):
    from research_agent.web.db.models import LibraryItem, Paper

    paper = Paper(source_id="MED:lib", title="t", abstract="a")
    db.add(paper)
    db.flush()
    db.add(LibraryItem(paper_id=paper.id, status="to_read", snapshot={}))
    db.flush()
    db.add(LibraryItem(paper_id=paper.id, status="read", snapshot={}))
    with pytest.raises(sa.exc.IntegrityError):
        db.flush()
    db.rollback()
