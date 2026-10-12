"""Researcher topics: `field_versions.authors` (null: a keyword or topic field), the saved author search
{people, group, coauthors, institutions, min_shared} (research_agent.authorsearch).

Revision ID: 0016
Revises: 0015
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "field_versions",
        sa.Column("authors", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade():
    op.drop_column("field_versions", "authors")
