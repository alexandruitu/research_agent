import pytest
import sqlalchemy as sa
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext

from research_agent.web.db.models import Base
from research_agent.web.settings import SettingsError, load_settings

TABLES = {
    "users",
    "sessions",
    "fields",
    "criteria",
    "papers",
    "runs",
    "screenings",
    "criterion_scores",
    "evidence_claims",
    "reviews",
    "rankings",
    "gold_sets",
    "gold_labels",
    "eval_reports",
    "jobs",
}


def test_settings_require_a_database_url(tmp_path):
    with pytest.raises(SettingsError, match="RESEARCH_WEB_DATABASE_URL"):
        load_settings({})
    s = load_settings(
        {"RESEARCH_WEB_DATABASE_URL": "postgresql+psycopg://x/y", "RESEARCH_RUNS_DIR": str(tmp_path)}
    )
    assert s.runs_dir == tmp_path.resolve() and s.cookie_secure is True
    dev = load_settings({"RESEARCH_WEB_DATABASE_URL": "u", "RESEARCH_WEB_COOKIE_SECURE": "false"})
    assert dev.cookie_secure is False


def test_migration_creates_every_table_and_matches_the_models(migrated_engine):
    inspector = sa.inspect(migrated_engine)
    assert TABLES <= set(inspector.get_table_names())
    assert {t.name for t in Base.metadata.sorted_tables} == TABLES
    with migrated_engine.connect() as connection:
        diff = compare_metadata(MigrationContext.configure(connection), Base.metadata)
    assert diff == [], f"models and migration drifted: {diff}"


def test_key_constraints_hold(db):
    from research_agent.web.db.models import Paper, Screening

    db.add(Paper(source_id="MED:1", title="t", abstract="a"))
    db.flush()
    db.add(Paper(source_id="MED:1", title="dup", abstract="a"))
    with pytest.raises(sa.exc.IntegrityError):
        db.flush()
    db.rollback()
    assert Screening.__table__.c.run_id.foreign_keys
