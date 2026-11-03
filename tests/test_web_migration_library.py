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


def test_0018_makes_the_team_library_the_company_library(pg_url, pg_engine):
    """Existing items become Company items and keep their data; full text comes from the snapshot's panel or an
    uploaded PDF, the rest is flagged abstract only; existing Reader notes become company notes."""
    name = f"l_{uuid.uuid4().hex[:10]}"
    with pg_engine.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
        connection.execute(sa.text(f'create database "{name}"'))
    url = sa.engine.make_url(pg_url).set(database=name).render_as_string(hide_password=False)
    try:
        command.upgrade(alembic_config(url), "0017")
        engine = sa.create_engine(url)
        papers = [uuid.uuid4() for _ in range(3)]
        items = [uuid.uuid4() for _ in range(3)]
        panel = '{"panel": {"text_source": "pmc", "text_licence": "cc-by", "score": 80}}'
        with engine.begin() as c:
            for n, p in enumerate(papers):
                c.execute(
                    sa.text(
                        "insert into papers (id, source_id, title, abstract, doi) values (:id, :s, 't', 'a', '')"
                    ),
                    {"id": p, "s": f"MED:{n}"},
                )
            snapshots = [panel, '{"panel": {"text_source": "abstract"}}', "{}"]
            for item, p, snap in zip(items, papers, snapshots, strict=True):
                c.execute(
                    sa.text(
                        "insert into library_items (id, paper_id, status, note, snapshot) "
                        "values (:id, :p, 'read', 'kept note', cast(:s as jsonb))"
                    ),
                    {"id": item, "p": p, "s": snap},
                )
            c.execute(
                sa.text(
                    "insert into paper_files (id, paper_id, sha256, filename, size) "
                    "values (:id, :p, :sha, 'x.pdf', 1)"
                ),
                {"id": uuid.uuid4(), "p": papers[1], "sha": "a" * 64},
            )
            c.execute(
                sa.text(
                    "insert into reader_notes (id, paper_id, tool, answer, quotes) values (:id, :p, 'explain', '{}', '[]')"
                ),
                {"id": uuid.uuid4(), "p": papers[0]},
            )
        upgrade(url)
        with engine.connect() as c:
            rows = c.execute(
                sa.text(
                    "select id, scope, owner_id, has_full_text, text_source, text_licence, status, note "
                    "from library_items"
                )
            ).all()
            by_id = {r.id: r for r in rows}
            assert all(r.scope == "company" and r.owner_id is None for r in rows)
            assert all(r.status == "read" and r.note == "kept note" for r in rows)
            first, second, third = (by_id[i] for i in items)
            assert (first.has_full_text, first.text_source, first.text_licence) == (True, "pmc", "cc-by")
            assert (second.has_full_text, second.text_source, second.text_licence) == (
                True,
                "upload",
                "user_upload",
            )
            assert (third.has_full_text, third.text_source) == (False, None)  # abstract only, kept
            assert c.execute(sa.text("select visibility from reader_notes")).scalar_one() == "company"
            assert c.execute(sa.text("select scope from collections")).all() == []
        command.downgrade(alembic_config(url), "0017")
        with engine.connect() as c:
            assert c.execute(sa.text("select count(*) from library_items")).scalar_one() == 3
        upgrade(url)
        engine.dispose()
    finally:
        with pg_engine.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
            connection.execute(sa.text(f'drop database "{name}" with (force)'))
