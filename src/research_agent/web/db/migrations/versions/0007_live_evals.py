"""Live evals: eval report kind, frozen config and parent; gold sets built in the app; rating samples and
human reference ratings.

Revision ID: 0007
Revises: 0006
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "eval_reports", sa.Column("kind", sa.String(16), server_default="screening", nullable=False)
    )
    op.add_column(
        "eval_reports", sa.Column("config", JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False)
    )
    op.add_column(
        "eval_reports",
        sa.Column(
            "parent_id", sa.Uuid(), sa.ForeignKey("eval_reports.id", ondelete="SET NULL"), nullable=True
        ),
    )
    op.add_column(
        "eval_reports", sa.Column("created_by", sa.Uuid(), sa.ForeignKey("users.id"), nullable=True)
    )
    op.alter_column("eval_reports", "gold_set_id", nullable=True)
    for name, column in (
        ("path", sa.Text()),
        ("candidates", sa.Integer()),
        ("positives", sa.Integer()),
        ("unresolved", sa.Integer()),
        ("source", JSONB()),
    ):
        op.add_column("gold_sets", sa.Column(name, column, nullable=True))
    op.add_column("gold_sets", sa.Column("created_by", sa.Uuid(), sa.ForeignKey("users.id"), nullable=True))
    op.create_table(
        "rating_samples",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "eval_report_id",
            sa.Uuid(),
            sa.ForeignKey("eval_reports.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("folder", sa.Text(), nullable=False),
        sa.Column("size", sa.Integer(), nullable=False),
        sa.Column("seed", sa.Integer(), nullable=False),
        sa.Column("paper_ids", JSONB(), nullable=False),
        sa.Column("created_by", sa.Uuid(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_table(
        "human_ratings",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "sample_id",
            sa.Uuid(),
            sa.ForeignKey("rating_samples.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("paper_id", sa.String(200), nullable=False),
        sa.Column("rater_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("reviewer", sa.String(64), nullable=False),
        sa.Column("reviewer_version", sa.Integer(), nullable=False),
        sa.Column("item", sa.String(64), nullable=False),
        sa.Column("item_text", sa.Text(), nullable=False),
        sa.Column("answer", sa.String(16), nullable=False),
        sa.Column("quote", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("sample_id", "paper_id", "rater_id", "reviewer", "item"),
    )


def downgrade():
    op.drop_table("human_ratings")
    op.drop_table("rating_samples")
    for name in ("created_by", "source", "unresolved", "positives", "candidates", "path"):
        op.drop_column("gold_sets", name)
    op.execute("delete from eval_reports where gold_set_id is null")
    op.alter_column("eval_reports", "gold_set_id", nullable=False)
    for name in ("created_by", "parent_id", "config", "kind"):
        op.drop_column("eval_reports", name)
