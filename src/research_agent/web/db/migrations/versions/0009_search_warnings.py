"""Partial search: the sources a research run skipped, with the reason and the fix.

Revision ID: 0009
Revises: 0008
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade():
    # null: a legacy run or one imported before partial search; []: every source answered
    op.add_column("runs", sa.Column("search_warnings", postgresql.JSONB(), nullable=True))


def downgrade():
    op.drop_column("runs", "search_warnings")
