"""Index every foreign key column that had no index starting with it: joins on them and the reference checks
when a user, run, gold set or paper is deleted no longer scan the whole table.

Revision ID: 0019
Revises: 0018
"""

from alembic import op

revision = "0019"
down_revision = "0018"
branch_labels = None
depends_on = None

COLUMNS = (
    ("alerts", "created_by"),
    ("alerts", "last_run_id"),
    ("collections", "created_by"),
    ("criterion_scores", "criterion_id"),
    ("eval_reports", "created_by"),
    ("eval_reports", "gold_set_id"),
    ("eval_reports", "parent_id"),
    ("field_versions", "created_by"),
    ("fields", "created_by"),
    ("gold_labels", "paper_id"),
    ("gold_sets", "created_by"),
    ("human_ratings", "rater_id"),
    ("library_events", "user_id"),
    ("library_items", "added_by"),
    ("paper_files", "uploaded_by"),
    ("paper_maps", "created_by"),
    ("rankings", "paper_id"),
    ("rating_samples", "created_by"),
    ("reader_notes", "created_by"),
    ("reviewer_profiles", "created_by"),
    ("reviewer_versions", "created_by"),
    ("runs", "created_by"),
    ("runs", "gold_set_id"),
    ("sessions", "user_id"),
    ("settings_versions", "created_by"),
)


def upgrade():
    for table, column in COLUMNS:
        op.create_index(f"ix_{table}_{column}", table, [column])


def downgrade():
    for table, column in COLUMNS:
        op.drop_index(f"ix_{table}_{column}", table_name=table)
