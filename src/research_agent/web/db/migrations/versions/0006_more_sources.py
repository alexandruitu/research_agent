"""More sources: a row per registry source (only Europe PMC enabled by default), the worker's key status per
source (never a value), paper_reviews.text_source wide enough for every resolver, and text_licence.

The names are listed here, not imported: a migration must not change when the code does.

Revision ID: 0006
Revises: 0005
"""

import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None

OLD = ("europepmc", "openalex", "arxiv")
NEW = (
    "pubmed",
    "medrxiv",
    "biorxiv",
    "semantic_scholar",
    "core",
    "unpaywall",
    "ieee",
    "springer",
    "scopus",
    "sciencedirect",
    "crossref",
)


def upgrade():
    op.alter_column("paper_reviews", "text_source", type_=sa.String(length=24), existing_nullable=False)
    op.add_column("paper_reviews", sa.Column("text_licence", sa.String(length=24), nullable=True))
    op.add_column(
        "sources", sa.Column("key_present", sa.Boolean(), server_default=sa.false(), nullable=False)
    )
    op.add_column("sources", sa.Column("key_accepted", sa.Boolean(), nullable=True))
    op.add_column("sources", sa.Column("key_detail", sa.String(length=200), server_default="", nullable=False))
    op.add_column("sources", sa.Column("key_checked_at", sa.DateTime(timezone=True), nullable=True))
    conn = op.get_bind()
    for name in NEW:
        conn.execute(
            sa.text(
                "insert into sources (name, enabled, max_results) values (:n, false, 100)"
                " on conflict (name) do nothing"
            ),
            {"n": name},
        )


def downgrade():
    conn = op.get_bind()
    conn.execute(sa.text("delete from sources where name <> all(:old)"), {"old": list(OLD)})
    for column in ("key_checked_at", "key_detail", "key_accepted", "key_present"):
        op.drop_column("sources", column)
    op.drop_column("paper_reviews", "text_licence")
    op.alter_column("paper_reviews", "text_source", type_=sa.String(length=16), existing_nullable=False)
