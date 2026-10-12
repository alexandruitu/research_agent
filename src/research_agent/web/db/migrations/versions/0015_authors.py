"""Authors: `authors` (one row per ORCID / OpenAlex id, or per normalized name for name-only authors) and
`paper_authors` (a paper's authors in order, with the affiliations given for that paper).

Revision ID: 0015
Revises: 0014
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "authors",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=300), nullable=False),
        sa.Column("normalized_name", sa.String(length=300), nullable=False),
        sa.Column("orcid", sa.String(length=19), nullable=True),
        sa.Column("openalex_id", sa.String(length=40), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("orcid"),
        sa.UniqueConstraint("openalex_id"),
    )
    op.create_index(op.f("ix_authors_normalized_name"), "authors", ["normalized_name"], unique=False)
    op.create_table(
        "paper_authors",
        sa.Column("paper_id", sa.Uuid(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("author_id", sa.Uuid(), nullable=False),
        sa.Column("affiliations", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.ForeignKeyConstraint(["paper_id"], ["papers.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["author_id"], ["authors.id"]),
        sa.PrimaryKeyConstraint("paper_id", "position"),
    )
    op.create_index(op.f("ix_paper_authors_author_id"), "paper_authors", ["author_id"], unique=False)


def downgrade():
    op.drop_index(op.f("ix_paper_authors_author_id"), table_name="paper_authors")
    op.drop_table("paper_authors")
    op.drop_index(op.f("ix_authors_normalized_name"), table_name="authors")
    op.drop_table("authors")
