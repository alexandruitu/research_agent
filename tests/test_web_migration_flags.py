"""Migration 0010: red flags read as the problem; item_text keeps the checklist item."""

import importlib.util
import uuid
from pathlib import Path

import sqlalchemy as sa
from alembic import command

from research_agent.web.db.migrate import alembic_config, upgrade

PATH = Path(__file__).parents[1] / "src/research_agent/web/db/migrations/versions/0010_red_flag_wording.py"


def module():
    spec = importlib.util.spec_from_file_location("m0010", PATH)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_problem_text_and_snapshot_rewrite():
    m = module()
    assert m.problem_text("Tested externally.", "no") == "Not met: Tested externally."
    assert m.problem_text("Tuned on test.", "yes") == "Concern: Tuned on test."
    from research_agent.panel import DEFAULT_PANEL

    m5 = next(i for i in DEFAULT_PANEL[0]["items"] if i["key"] == "m5")
    assert m.problem_text(m5["text"], "no") == "No external validation"
    snap = {"panel": {"red_flags": [{"text": "A."}, {"text": "B."}, {"text": "C", "item_text": "c"}]}}
    out = m.rewrite_snapshot(snap, {"A.": "Not met: A."})
    assert [(f["text"], f["item_text"]) for f in out["panel"]["red_flags"]] == [
        ("Not met: A.", "A."),
        ("Flagged: B.", "B."),
        ("C", "c"),
    ]
    assert m.rewrite_snapshot({"panel": None}, {}) is None


def test_upgrade_and_downgrade(pg_url, pg_engine):
    name = f"f_{uuid.uuid4().hex[:10]}"
    with pg_engine.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
        connection.execute(sa.text(f'create database "{name}"'))
    url = sa.engine.make_url(pg_url).set(database=name).render_as_string(hide_password=False)
    try:
        upgrade(url)
        engine = sa.create_engine(url)
        assert "item_text" in {c["name"] for c in sa.inspect(engine).get_columns("red_flags")}
        command.downgrade(alembic_config(url), "0009")
        assert "item_text" not in {c["name"] for c in sa.inspect(engine).get_columns("red_flags")}
        upgrade(url)
        engine.dispose()
    finally:
        with pg_engine.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
            connection.execute(sa.text(f'drop database "{name}" with (force)'))
