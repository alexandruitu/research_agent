"""Field alerts: scheduled "what's new" runs of a field with an in-app digest.

alerts (one per field), alert_subscriptions, digests (items frozen), digest_reads; runs.trigger
(manual | alert); app_settings.alerts_max_runs_per_day (default 5).

Revision ID: 0011
Revises: 0010
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None

NOW = sa.text("now()")


def upgrade():
    op.add_column("runs", sa.Column("trigger", sa.String(length=16), server_default="manual", nullable=False))
    op.add_column(
        "app_settings",
        sa.Column("alerts_max_runs_per_day", sa.Integer(), server_default="5", nullable=False),
    )
    op.create_table(
        "alerts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("field_id", sa.Uuid(), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("cadence", sa.String(length=16), server_default="weekly", nullable=False),
        sa.Column("weekday", sa.Integer(), server_default="0", nullable=False),
        sa.Column("hour", sa.Integer(), server_default="7", nullable=False),
        sa.Column("next_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_run_id", sa.Uuid(), nullable=True),
        sa.Column("max_new", sa.Integer(), server_default="50", nullable=False),
        sa.Column("min_group", sa.String(length=16), server_default="worth_a_look", nullable=False),
        sa.Column("years_back", sa.Integer(), server_default="1", nullable=False),
        sa.Column("failures", sa.Integer(), server_default="0", nullable=False),
        sa.Column("paused_reason", sa.Text(), nullable=True),
        sa.Column("deferred_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.ForeignKeyConstraint(["field_id"], ["fields.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["last_run_id"], ["runs.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("field_id"),
    )
    op.create_index(op.f("ix_alerts_next_run_at"), "alerts", ["next_run_at"], unique=False)
    op.create_table(
        "alert_subscriptions",
        sa.Column("alert_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.ForeignKeyConstraint(["alert_id"], ["alerts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("alert_id", "user_id"),
    )
    op.create_index(op.f("ix_alert_subscriptions_user_id"), "alert_subscriptions", ["user_id"], unique=False)
    op.create_table(
        "digests",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("alert_id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("counts", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("items", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.ForeignKeyConstraint(["alert_id"], ["alerts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["run_id"], ["runs.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_id"),
    )
    op.create_index(op.f("ix_digests_alert_id"), "digests", ["alert_id"], unique=False)
    op.create_table(
        "digest_reads",
        sa.Column("digest_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("read_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.ForeignKeyConstraint(["digest_id"], ["digests.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("digest_id", "user_id"),
    )
    op.create_index(op.f("ix_digest_reads_user_id"), "digest_reads", ["user_id"], unique=False)


def downgrade():
    op.drop_index(op.f("ix_digest_reads_user_id"), table_name="digest_reads")
    op.drop_table("digest_reads")
    op.drop_index(op.f("ix_digests_alert_id"), table_name="digests")
    op.drop_table("digests")
    op.drop_index(op.f("ix_alert_subscriptions_user_id"), table_name="alert_subscriptions")
    op.drop_table("alert_subscriptions")
    op.drop_index(op.f("ix_alerts_next_run_at"), table_name="alerts")
    op.drop_table("alerts")
    op.drop_column("app_settings", "alerts_max_runs_per_day")
    op.drop_column("runs", "trigger")
