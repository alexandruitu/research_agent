"""Field versions keep a free-text description, keyword groups and per-source query overrides.

Revision ID: 0004
Revises: 0003
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("field_versions", sa.Column("description", sa.Text(), server_default="", nullable=False))
    op.add_column("field_versions", sa.Column("keywords", postgresql.JSONB(), nullable=True))
    op.add_column("field_versions", sa.Column("query_override", postgresql.JSONB(), nullable=True))


def downgrade():
    op.drop_column("field_versions", "query_override")
    op.drop_column("field_versions", "keywords")
    op.drop_column("field_versions", "description")
