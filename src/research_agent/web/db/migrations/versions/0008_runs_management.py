"""Runs management: a run's name, note, pin and start time; a running job's cancel request.

Revision ID: 0008
Revises: 0007
"""

import sqlalchemy as sa
from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "jobs", sa.Column("cancel_requested", sa.Boolean(), server_default=sa.text("false"), nullable=False)
    )
    op.add_column("runs", sa.Column("started_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("runs", sa.Column("name", sa.String(length=200), nullable=True))
    op.add_column("runs", sa.Column("note", sa.Text(), server_default="", nullable=False))
    op.add_column("runs", sa.Column("pinned", sa.Boolean(), server_default=sa.text("false"), nullable=False))


def downgrade():
    op.drop_column("runs", "pinned")
    op.drop_column("runs", "note")
    op.drop_column("runs", "name")
    op.drop_column("runs", "started_at")
    op.drop_column("jobs", "cancel_requested")
