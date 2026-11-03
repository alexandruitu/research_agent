"""Two libraries: library items and collections get a `scope` (company | personal) and an owner; items record
the text they rest on (has_full_text, text_source, text_licence); Reader notes get a visibility.

The existing team library becomes the Company library, keeping every item: items whose snapshot shows a
full-text panel review, or whose paper has an uploaded PDF, are marked with full text; the others stay,
flagged abstract only. Existing Reader notes were shared with the team, so they become company notes.

Revision ID: 0018
Revises: 0017
"""

import sqlalchemy as sa
from alembic import op

revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None


def upgrade():
    for table in ("library_items", "collections"):
        op.add_column(table, sa.Column("scope", sa.String(16), server_default="company", nullable=False))
        op.add_column(
            table,
            sa.Column("owner_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=True),
        )
        op.create_index(f"ix_{table}_owner_id", table, ["owner_id"])
    op.add_column(
        "library_items", sa.Column("has_full_text", sa.Boolean(), server_default="false", nullable=False)
    )
    op.add_column("library_items", sa.Column("text_source", sa.String(24), nullable=True))
    op.add_column("library_items", sa.Column("text_licence", sa.String(24), nullable=True))
    op.add_column(
        "reader_notes", sa.Column("visibility", sa.String(16), server_default="company", nullable=False)
    )

    op.drop_constraint("library_items_paper_id_key", "library_items", type_="unique")
    op.create_index("ix_library_items_paper_id", "library_items", ["paper_id"])
    op.create_index(
        "ux_library_items_company_paper",
        "library_items",
        ["paper_id"],
        unique=True,
        postgresql_where=sa.text("scope = 'company'"),
    )
    op.create_index(
        "ux_library_items_personal_paper",
        "library_items",
        ["owner_id", "paper_id"],
        unique=True,
        postgresql_where=sa.text("scope = 'personal'"),
    )
    op.drop_index("ux_collections_lower_name", table_name="collections")
    op.create_index(
        "ux_collections_lower_name",
        "collections",
        [sa.text("lower(name)")],
        unique=True,
        postgresql_where=sa.text("scope = 'company'"),
    )
    op.create_index(
        "ux_collections_owner_lower_name",
        "collections",
        ["owner_id", sa.text("lower(name)")],
        unique=True,
        postgresql_where=sa.text("scope = 'personal'"),
    )

    # Full text of the existing (now Company) items: the panel's text at snapshot time, else an uploaded PDF.
    op.execute(
        """
        update library_items
           set has_full_text = true,
               text_source = snapshot -> 'panel' ->> 'text_source',
               text_licence = snapshot -> 'panel' ->> 'text_licence'
         where coalesce(snapshot -> 'panel' ->> 'text_source', 'abstract') <> 'abstract'
        """
    )
    op.execute(
        """
        update library_items i
           set has_full_text = true, text_source = 'upload', text_licence = 'user_upload'
         where not i.has_full_text
           and exists (select 1 from paper_files f where f.paper_id = i.paper_id)
        """
    )


def downgrade():
    # Personal items and collections have no place in the single team library: they go.
    op.execute("delete from library_items where scope = 'personal'")
    op.execute("delete from collections where scope = 'personal'")
    op.drop_index("ux_collections_owner_lower_name", table_name="collections")
    op.drop_index("ux_collections_lower_name", table_name="collections")
    op.create_index("ux_collections_lower_name", "collections", [sa.text("lower(name)")], unique=True)
    op.drop_index("ux_library_items_personal_paper", table_name="library_items")
    op.drop_index("ux_library_items_company_paper", table_name="library_items")
    op.drop_index("ix_library_items_paper_id", table_name="library_items")
    op.create_unique_constraint("library_items_paper_id_key", "library_items", ["paper_id"])
    op.drop_column("reader_notes", "visibility")
    for column in ("text_licence", "text_source", "has_full_text"):
        op.drop_column("library_items", column)
    for table in ("collections", "library_items"):
        op.drop_index(f"ix_{table}_owner_id", table_name=table)
        op.drop_column(table, "owner_id")
        op.drop_column(table, "scope")
