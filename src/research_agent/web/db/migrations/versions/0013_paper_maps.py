"""Paper maps: the Reader's fixed-schema map of a paper (quoted nodes, the run's red flags), per run, paper,
prompt version and model.

Revision ID: 0013
Revises: 0012
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "paper_maps",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("paper_id", sa.Uuid(), nullable=False),
        sa.Column("prompt_version", sa.String(length=64), nullable=False),
        sa.Column("model", sa.String(length=200), nullable=False),
        sa.Column("mode", sa.String(length=16), server_default="live", nullable=False),
        sa.Column("text_kind", sa.String(length=16), nullable=False),
        sa.Column("branches", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("red_flags", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("built_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["paper_id"], ["papers.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_id", "paper_id", "prompt_version", "model"),
    )
    op.create_index(op.f("ix_paper_maps_run_id"), "paper_maps", ["run_id"], unique=False)
    op.create_index(op.f("ix_paper_maps_paper_id"), "paper_maps", ["paper_id"], unique=False)


def downgrade():
    op.drop_index(op.f("ix_paper_maps_paper_id"), table_name="paper_maps")
    op.drop_index(op.f("ix_paper_maps_run_id"), table_name="paper_maps")
    op.drop_table("paper_maps")
