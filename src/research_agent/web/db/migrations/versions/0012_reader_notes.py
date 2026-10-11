"""Reader notes: a Reader answer saved on a paper (linked to the run and, when one exists, the library item).

Revision ID: 0012
Revises: 0011
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "reader_notes",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("paper_id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=True),
        sa.Column("library_item_id", sa.Uuid(), nullable=True),
        sa.Column("selection", sa.Text(), server_default="", nullable=False),
        sa.Column("tool", sa.String(length=16), nullable=False),
        sa.Column("question", sa.Text(), server_default="", nullable=False),
        sa.Column("answer", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("quotes", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("model", sa.String(length=200), server_default="", nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["paper_id"], ["papers.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["run_id"], ["runs.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["library_item_id"], ["library_items.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_reader_notes_paper_id"), "reader_notes", ["paper_id"], unique=False)
    op.create_index(op.f("ix_reader_notes_run_id"), "reader_notes", ["run_id"], unique=False)
    op.create_index(
        op.f("ix_reader_notes_library_item_id"), "reader_notes", ["library_item_id"], unique=False
    )


def downgrade():
    op.drop_index(op.f("ix_reader_notes_library_item_id"), table_name="reader_notes")
    op.drop_index(op.f("ix_reader_notes_run_id"), table_name="reader_notes")
    op.drop_index(op.f("ix_reader_notes_paper_id"), table_name="reader_notes")
    op.drop_table("reader_notes")
