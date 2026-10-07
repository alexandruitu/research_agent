"""Red flags read as the problem: red_flags.text becomes the problem phrasing, item_text keeps the checklist item.

Existing rows predate flag_text, so their text is the (positively phrased) item: it moves to item_text and text
gets the default panel's wording for that item when it is one, else the generated phrasing ("Not met: <item>" when the flag was raised by a "no", "Concern: <item>" by a "yes").
Library snapshots get the same rewrite, matched to their run's red flags; unmatched snapshot flags are prefixed
"Flagged: " (their raising answer was not kept).

Revision ID: 0010
Revises: 0009
"""

import json

import sqlalchemy as sa
from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None

PREFIX = {"no": "Not met: ", "yes": "Concern: "}


def problem_text(item_text, answer):
    """The shipped wording of a default panel item, else the generated phrasing."""
    from research_agent.scoring import default_flag_text

    return default_flag_text(item_text) or PREFIX.get(answer, "Concern: ") + item_text


def rewrite_snapshot(snapshot, known):
    """snapshot: a library item snapshot; known: {item text: problem text} of its run's red flags. Returns the
    rewritten snapshot, or None when nothing changed."""
    flags = ((snapshot or {}).get("panel") or {}).get("red_flags") or []
    changed = False
    for flag in flags:
        if "item_text" in flag:
            continue
        flag["item_text"] = flag.get("text", "")
        flag["text"] = known.get(flag["item_text"]) or "Flagged: " + flag["item_text"]
        changed = True
    return snapshot if changed else None


def upgrade():
    op.add_column("red_flags", sa.Column("item_text", sa.Text(), nullable=True))
    c = op.get_bind()
    rows = c.execute(sa.text("select id, text, raised_by from red_flags")).all()
    for row in rows:
        raised = row.raised_by or []
        answer = raised[0].get("answer") if raised else None
        c.execute(
            sa.text("update red_flags set item_text = :item, text = :text where id = :id"),
            {"item": row.text, "text": problem_text(row.text, answer), "id": row.id},
        )
    items = c.execute(
        sa.text(
            "select id, run_id, paper_id, snapshot from library_items where snapshot -> 'panel' is not null"
        )
    ).all()
    for item in items:
        known = dict(
            c.execute(
                sa.text(
                    "select f.item_text, f.text from red_flags f join paper_reviews r on r.id = f.paper_review_id "
                    "where r.run_id = :run and r.paper_id = :paper"
                ),
                {"run": item.run_id, "paper": item.paper_id},
            ).all()
        )
        snapshot = rewrite_snapshot(item.snapshot, known)
        if snapshot is not None:
            c.execute(
                sa.text("update library_items set snapshot = cast(:s as jsonb) where id = :id"),
                {"s": json.dumps(snapshot), "id": item.id},
            )


def downgrade():
    op.execute("update red_flags set text = item_text where item_text is not null")
    op.drop_column("red_flags", "item_text")
