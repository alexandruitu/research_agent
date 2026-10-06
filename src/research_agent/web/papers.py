"""The paper table: one run's papers joined with every stage, filtered, sorted and paged in SQL."""

from collections import defaultdict
from dataclasses import dataclass
from types import SimpleNamespace

from sqlalchemy import String, and_, case, cast, exists, func, literal, or_, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import aliased

from ..agents import validate_evidence
from .db.models import (
    Criterion,
    CriterionScore,
    EvidenceClaim,
    GoldLabel,
    LibraryItem,
    PanelReport,
    Paper,
    PaperReview,
    Ranking,
    RedFlag,
    Review,
    ReviewerVersion,
    Screening,
)

NOT_SCREENED = "rule"  # candidates without an abstract: a row in the table, but never screened


@dataclass
class PaperQuery:
    page: int = 1
    page_size: int = 50
    sort: str = "title"
    direction: str = "asc"
    decision: str | None = None
    tier: str | None = None
    escalated: bool | None = None
    in_sr: bool | None = None
    criterion: str | None = None
    p_min: float | None = None
    p_max: float | None = None
    decided_by: str | None = None
    source: str | None = None
    has_red_flags: bool | None = None
    group_by: str = "quality"
    group: str | None = None


QUALITY_GROUPS = (
    ("read_first", "Read first", "Kept by screening, editor verdict include and 0 red flags."),
    (
        "worth_a_look",
        "Worth a look",
        (
            "Kept, verdict include or uncertain and at most 1 red flag "
            "(legacy A/B runs: red flags were not checked)."
        ),
    ),
    ("has_problems", "Has problems", "Kept, but 2 or more red flags or verdict exclude."),
    ("not_relevant", "Not relevant", "Dropped by screening; each row names the criterion that dropped it."),
    (
        "not_reviewed",
        "Not reviewed",
        "Kept (or never screened: no abstract) but without a review verdict.",
    ),
)


def quality_expr(ra, rb, rj):
    """The quality group of a row, first match wins. The verdict is the panel editor's; in legacy A/B runs
    the adjudicator's, else A's when A and B agree, else uncertain when they disagree. Red flags are null
    when no panel reviewed the paper (not checked), so such a paper never qualifies for read_first."""
    legacy = case(
        (rj.verdict.is_not(None), rj.verdict),
        (and_(ra.verdict.is_not(None), ra.verdict == rb.verdict), ra.verdict),
        (and_(ra.verdict.is_not(None), rb.verdict.is_not(None)), literal("uncertain")),
    )
    verdict = case((PaperReview.id.is_not(None), PaperReview.editor_verdict), else_=legacy)
    flags = PaperReview.red_flag_count
    return case(
        (and_(Screening.decision == "exclude", Screening.tier != NOT_SCREENED), literal("not_relevant")),
        (or_(flags >= 2, verdict == "exclude"), literal("has_problems")),
        (and_(verdict == "include", flags == 0), literal("read_first")),
        (
            and_(verdict.in_(["include", "uncertain"]), or_(flags.is_(None), flags <= 1)),
            literal("worth_a_look"),
        ),
        else_=literal("not_reviewed"),
    )


def _criterion_probability(key):
    return (
        select(CriterionScore.probability)
        .join(Criterion, Criterion.id == CriterionScore.criterion_id)
        .where(CriterionScore.screening_id == Screening.id, Criterion.key == key)
        .limit(1)
        .scalar_subquery()
    )


def expects_downstream(run, screening, reviewed):
    """Research runs: extraction and reviews are expected for papers the screen kept that had an abstract.
    Eval runs: they are expected exactly for the agreement sample (the papers that have review rows)."""
    if run.kind == "eval":
        return reviewed
    return run.kind == "research" and screening.decision != "exclude" and screening.tier != NOT_SCREENED


def quotes_verified(quotes, abstract):
    """The pipeline's own check (`validate_evidence`): every quote is an exact span of the stored abstract."""
    try:
        validate_evidence(SimpleNamespace(claims=[SimpleNamespace(quote=q) for q in quotes]), abstract)
    except ValueError:
        return False
    return True


def reviews_cell(verdicts, adjudication_expected, expected):
    """{a, b, adjudicated, adjudicator}; when any expected part (A, B, or an adjudicator the run says
    was needed) is absent, the whole cell is {"missing": true} so an absent side never reads as null."""
    a, b, adjudicator = verdicts
    if a is None and b is None and adjudicator is None:
        return {"missing": True} if expected else None
    adjudicated = adjudication_expected or adjudicator is not None
    if a is None or b is None or (adjudicated and adjudicator is None):
        return {"missing": True}
    return {"a": a, "b": b, "adjudicated": adjudicated, "adjudicator": adjudicator}


PANEL_COLUMNS = ("score", "coverage", "red_flag_count", "text_source", "text_licence")


def build_row(
    run, screening, paper, cells, quotes, verdicts, adjudication_expected, rank, label, panel=None, group=None
):
    expected = expects_downstream(run, screening, any(v is not None for v in verdicts))
    if quotes:
        extract = {"claims": len(quotes), "quotes_verified": quotes_verified(quotes, paper.abstract)}
    else:
        extract = {"missing": True} if expected else None
    reviews = reviews_cell(verdicts, adjudication_expected, expected)
    return {
        "paper": {
            "id": paper.id,
            "source_id": paper.source_id,
            "title": paper.title,
            "year": paper.year,
            "doi": paper.doi,
        },
        "found_by": screening.found_by,
        "sources": list(screening.sources or []),
        "in_sr": None if run.gold_set_id is None else label == "include",
        "screen": {
            "tier": screening.tier,
            "decision": screening.decision,
            "jev_decision": screening.jev_decision,
            "llm_decision": screening.llm_decision,
            "criteria": {k: c["jev_p"] for k, c in cells.items() if c["jev_p"] is not None},
            "decided_by": screening.decided_by,
            "cells": cells,
        },
        "extract": extract,
        "reviews": reviews,
        "rank": {"score": rank[0], "position": rank[1]} if rank[0] is not None else None,
        "group": group,
        **dict(zip(PANEL_COLUMNS, panel or (None,) * len(PANEL_COLUMNS), strict=True)),
    }


def _sort_key(sort):
    """`sort` is validated by the router; anything else is refused here too (never raw input into ORDER BY)."""
    if sort == "title":
        return func.lower(Paper.title)
    if sort == "year":
        return Paper.year
    if sort == "score":  # a panel run's score for every reviewed paper; the ranking score otherwise
        return func.coalesce(PaperReview.score, Ranking.score)
    if sort.startswith("criterion:"):
        return _criterion_probability(sort.split(":", 1)[1])  # a bound parameter, not SQL text
    raise ValueError(f"unknown sort {sort!r}")


def _filtered(run, q):
    """The run's rows with every filter applied: (statement, quality expression)."""
    ra, rb, rj, gl = aliased(Review), aliased(Review), aliased(Review), aliased(GoldLabel)
    quality = quality_expr(ra, rb, rj)

    def review_join(alias, role):
        return and_(
            alias.run_id == Screening.run_id, alias.paper_id == Screening.paper_id, alias.role == role
        )

    stmt = (
        select(
            Screening,
            Paper,
            ra.verdict,
            rb.verdict,
            rj.verdict,
            ra.detail,
            rb.detail,
            Ranking.score,
            Ranking.position,
            gl.label,
            PaperReview.score,
            PaperReview.coverage,
            PaperReview.red_flag_count,
            PaperReview.text_source,
            PaperReview.text_licence,
            quality,
        )
        .join(Paper, Paper.id == Screening.paper_id)
        .outerjoin(ra, review_join(ra, "a"))
        .outerjoin(rb, review_join(rb, "b"))
        .outerjoin(rj, review_join(rj, "adjudicator"))
        .outerjoin(Ranking, and_(Ranking.run_id == Screening.run_id, Ranking.paper_id == Screening.paper_id))
        .outerjoin(gl, and_(gl.gold_set_id == run.gold_set_id, gl.paper_id == Screening.paper_id))
        .outerjoin(
            PaperReview,
            and_(PaperReview.run_id == Screening.run_id, PaperReview.paper_id == Screening.paper_id),
        )
        .outerjoin(LibraryItem, LibraryItem.paper_id == Screening.paper_id)
        .where(Screening.run_id == run.id)
    )
    if q.decision:
        # Never-screened rows carry decision "uncertain" but are not a screening outcome: the decision
        # filter matches the run counts (kept = include + uncertain, dropped = exclude), which leave them out.
        stmt = stmt.where(Screening.decision == q.decision, Screening.tier != NOT_SCREENED)
    if q.tier:
        stmt = stmt.where(Screening.tier == q.tier)
    if q.escalated is True:
        stmt = stmt.where(Screening.jev_decision == "escalate")
    elif q.escalated is False:
        stmt = stmt.where(or_(Screening.jev_decision.is_(None), Screening.jev_decision != "escalate"))
    if q.in_sr is True:
        stmt = stmt.where(gl.label == "include")
    elif q.in_sr is False:
        stmt = stmt.where(or_(gl.label.is_(None), gl.label != "include"))
    if q.decided_by:
        stmt = stmt.where(Screening.decided_by == q.decided_by)
    if q.source:
        stmt = stmt.where(Screening.sources.contains([q.source]))
    if q.has_red_flags is True:
        stmt = stmt.where(PaperReview.red_flag_count > 0)
    elif q.has_red_flags is False:
        stmt = stmt.where(or_(PaperReview.id.is_(None), PaperReview.red_flag_count == 0))
    if q.criterion:
        conditions = [CriterionScore.screening_id == Screening.id, Criterion.key == q.criterion]
        if q.p_min is not None:
            conditions.append(CriterionScore.probability >= q.p_min)
        if q.p_max is not None:
            conditions.append(CriterionScore.probability <= q.p_max)
        stmt = stmt.where(
            exists().where(CriterionScore.criterion_id == Criterion.id, *conditions).correlate(Screening)
        )
    if q.group is not None:
        stmt = stmt.where(group_key(q.group_by, quality, q.group))
    return stmt, quality


GROUP_RULES = {
    "source": "Grouped by the source that found the paper; a paper found by several is in each of their groups.",
    "year": "Grouped by publication year.",
    "decided_by": "Dropped papers grouped by the criterion that dropped them; kept papers together.",
    "library": "Grouped by the paper's status in the team library.",
}
SPECIAL_LABELS = {
    ("source", "none"): "No source search (eval candidates)",
    ("year", "none"): "Year unknown",
    ("decided_by", "kept"): "Kept by screening",
    ("decided_by", "not_screened"): "Not screened (no abstract)",
    ("decided_by", "unattributed"): "Dropped, no single criterion",
    ("library", "not_saved"): "Not in the library",
}


def _no_sources():
    return func.jsonb_array_length(func.coalesce(Screening.sources, literal([], JSONB))) == 0


def dimension_expr(by, quality):
    """The group key of a row for every dimension except source (a paper can have several sources)."""
    if by == "quality":
        return quality
    if by == "year":
        return func.coalesce(cast(Paper.year, String), literal("none"))
    if by == "decided_by":
        return case(
            (Screening.tier == NOT_SCREENED, literal("not_screened")),
            (Screening.decision == "exclude", func.coalesce(Screening.decided_by, literal("unattributed"))),
            else_=literal("kept"),
        )
    if by == "library":
        return func.coalesce(LibraryItem.status, literal("not_saved"))
    raise ValueError(f"unknown grouping {by!r}")


def group_key(by, quality, key):
    """The condition "the row is in group `key` of dimension `by`"."""
    if by == "source":
        return _no_sources() if key == "none" else Screening.sources.contains([key])
    return dimension_expr(by, quality) == key


def paper_groups(db, run, q, by):
    """[{key, label, count, rule}] for the filtered rows of a run (`q.group` is ignored)."""
    q = PaperQuery(**{**q.__dict__, "group": None})
    stmt, quality = _filtered(run, q)
    if by == "source":
        ids = stmt.with_only_columns(Screening.id, Screening.sources, maintain_column_froms=True).subquery()
        names = select(func.jsonb_array_elements_text(ids.c.sources).label("value")).subquery()
        counts = dict(db.execute(select(names.c.value, func.count()).group_by(names.c.value)).all())
        empty = db.scalar(
            select(func.count())
            .select_from(ids)
            .where(func.jsonb_array_length(func.coalesce(ids.c.sources, literal([], JSONB))) == 0)
        )
        if empty:
            counts["none"] = empty
    else:
        keyed = stmt.with_only_columns(
            dimension_expr(by, quality).label("key"), maintain_column_froms=True
        ).subquery()
        counts = dict(db.execute(select(keyed.c.key, func.count()).group_by(keyed.c.key)).all())
    if by == "quality":
        return [
            {"key": k, "label": label, "count": counts.get(k, 0), "rule": rule}
            for k, label, rule in QUALITY_GROUPS
            if k != "not_reviewed" or counts.get(k)
        ]
    order = sorted(counts, key=lambda k: (k in ("none", "not_saved", "kept"), str(k)))
    if by == "year":
        order = sorted(counts, key=lambda k: (k == "none", -int(k) if k != "none" else 0))
    return [
        {"key": k, "label": SPECIAL_LABELS.get((by, k), k), "count": counts[k], "rule": GROUP_RULES[by]}
        for k in order
    ]


def paper_table(db, run, q):
    stmt, _quality = _filtered(run, q)
    total = db.scalar(
        select(func.count()).select_from(
            stmt.with_only_columns(Screening.id, maintain_column_froms=True).subquery()
        )
    )
    key = _sort_key(q.sort)
    ordering = key.desc().nulls_last() if q.direction == "desc" else key.asc().nulls_last()
    rows = db.execute(
        stmt.order_by(ordering, Paper.source_id).limit(q.page_size).offset((q.page - 1) * q.page_size)
    ).all()

    cells, quotes = defaultdict(dict), defaultdict(list)
    ids = [r[0].id for r in rows]
    if ids:
        for paper_id, quote in db.execute(
            select(EvidenceClaim.paper_id, EvidenceClaim.quote).where(
                EvidenceClaim.run_id == run.id, EvidenceClaim.paper_id.in_([r[1].id for r in rows])
            )
        ):
            quotes[paper_id].append(quote)
        for screening_id, name, kind, probability, llm, quote in db.execute(
            select(
                CriterionScore.screening_id,
                Criterion.key,
                Criterion.kind,
                CriterionScore.probability,
                CriterionScore.llm_answer,
                CriterionScore.quote,
            )
            .join(Criterion, Criterion.id == CriterionScore.criterion_id)
            .where(CriterionScore.screening_id.in_(ids))
            .order_by(Criterion.position, Criterion.key)
        ):
            cells[screening_id][name] = {"kind": kind, "jev_p": probability, "llm": llm, "quote": quote}
    from .library import library_refs  # the library builds on this module

    refs = library_refs(db, [r[1].id for r in rows])
    items = [
        build_row(
            run,
            s,
            p,
            cells[s.id],
            quotes[p.id],
            (va, vb, vj),
            any((d or {}).get("adjudicated") is True for d in (da, db_)),
            (score, position),
            label,
            panel[:-1],
            panel[-1],
        )
        for s, p, va, vb, vj, da, db_, score, position, label, *panel in rows
    ]
    for item in items:
        item["library"] = refs.get(item["paper"]["id"])
    return items, total


ROLE_ORDER = {"a": 0, "b": 1, "adjudicator": 2}


def criteria_table(db, run, screening):
    """Every criterion of the run's field version (scored or not, e.g. a paper without an abstract), plus
    any scored criterion outside it, with Jev p, the LLM answer and quote, and which one decided."""
    score = aliased(CriterionScore)
    scored = (
        select(Criterion, score)
        .join(score, score.criterion_id == Criterion.id)
        .where(score.screening_id == screening.id)
    )
    rows = {c.id: (c, s) for c, s in db.execute(scored)}
    if run.field_version_id:
        for c in db.scalars(select(Criterion).where(Criterion.field_version_id == run.field_version_id)):
            rows.setdefault(c.id, (c, None))
    ordered = sorted(rows.values(), key=lambda cs: (cs[0].position, cs[0].key))
    return [
        {
            "key": c.key,
            "kind": c.kind,
            "text": c.question,
            "jev_p": s.probability if s else None,
            "llm": s.llm_answer if s else None,
            "quote": s.quote if s else None,
            "decided": c.key == screening.decided_by,
        }
        for c, s in ordered
    ]


def paper_drawer(db, run, paper):
    screening = db.scalar(select(Screening).where(Screening.run_id == run.id, Screening.paper_id == paper.id))
    if screening is None:
        return None
    scores = db.execute(
        select(Criterion.key, Criterion.question, CriterionScore.probability, CriterionScore.jev_version)
        .join(CriterionScore, CriterionScore.criterion_id == Criterion.id)
        .where(CriterionScore.screening_id == screening.id, CriterionScore.probability.is_not(None))
        .order_by(Criterion.position, Criterion.key)
    ).all()
    table = criteria_table(db, run, screening)
    label = (
        db.scalar(
            select(GoldLabel).where(GoldLabel.gold_set_id == run.gold_set_id, GoldLabel.paper_id == paper.id)
        )
        if run.gold_set_id
        else None
    )
    claims = db.scalars(
        select(EvidenceClaim)
        .where(EvidenceClaim.run_id == run.id, EvidenceClaim.paper_id == paper.id)
        .order_by(EvidenceClaim.created_at, EvidenceClaim.id)
    )
    reviews = sorted(
        db.scalars(select(Review).where(Review.run_id == run.id, Review.paper_id == paper.id)),
        key=lambda r: ROLE_ORDER[r.role],
    )
    rank = db.scalar(select(Ranking).where(Ranking.run_id == run.id, Ranking.paper_id == paper.id))
    return {
        "panel": panel_drawer(db, run, paper),
        "paper": {
            "id": paper.id,
            "source_id": paper.source_id,
            "title": paper.title,
            "abstract": paper.abstract,
            "year": paper.year,
            "doi": paper.doi,
        },
        "found_by": screening.found_by,
        "sources": list(screening.sources or []),
        "in_sr": None if run.gold_set_id is None else (label is not None and label.label == "include"),
        "label_source": label.label_source if label else None,
        "screening": {
            "tier": screening.tier,
            "decision": screening.decision,
            "jev_decision": screening.jev_decision,
            "llm_decision": screening.llm_decision,
            "reason": screening.reason,
            "call_key": screening.call_key,
            "criteria": [
                {"key": k, "question": q, "probability": p, "jev_version": v} for k, q, p, v in scores
            ],
            "decided_by": screening.decided_by,
            "criteria_table": table,
        },
        "claims": [{"statement": c.statement, "quote": c.quote, "call_key": c.call_key} for c in claims],
        "reviews": [
            {
                "role": r.role,
                "verdict": r.verdict,
                "relevance": r.relevance,
                "methods": r.methods,
                "support": r.support,
                "detail": r.detail,
                "call_key": r.call_key,
            }
            for r in reviews
        ],
        "rank": {"score": rank.score, "position": rank.position} if rank else None,
    }


def _answer(item, answer):
    """A reviewer's answer with the item it answers (text, source, weight from the reviewer version)."""
    item = item or {}
    return {
        "key": answer["key"],
        "text": item.get("text"),
        "source": item.get("source"),
        "weight": item.get("weight"),
        "answer": answer["answer"],
        "quote": answer.get("quote", ""),
        "section": answer.get("section", ""),
        "red_flag": item.get("red_flag_if") is not None and answer["answer"] == item.get("red_flag_if"),
    }


def panel_drawer(db, run, paper):
    """The panel review of one paper in one run (null for legacy runs and papers the panel did not review)."""
    review = db.scalar(
        select(PaperReview).where(PaperReview.run_id == run.id, PaperReview.paper_id == paper.id)
    )
    if review is None:
        return None
    reports = []
    for report in db.scalars(
        select(PanelReport)
        .where(PanelReport.paper_review_id == review.id)
        .order_by(PanelReport.position, PanelReport.reviewer_key)
    ):
        version = db.get(ReviewerVersion, report.reviewer_version_id) if report.reviewer_version_id else None
        items = {item["key"]: item for item in (version.items if version else [])}
        reports.append(
            {
                "key": report.reviewer_key,
                "name": report.name,
                "version": report.version,
                "verdict": report.verdict,
                "score": report.score,
                "coverage": report.coverage,
                "strengths": report.strengths,
                "weaknesses": report.weaknesses,
                "summary": report.summary,
                "call_key": report.call_key,
                "answers": [_answer(items.get(a["key"]), a) for a in report.answers],
            }
        )
    flags = db.scalars(select(RedFlag).where(RedFlag.paper_review_id == review.id).order_by(RedFlag.position))
    return {
        "text_source": review.text_source,
        "text_licence": review.text_licence,
        "text_reason": review.text_reason,
        "text_origin": review.text_origin,
        "text_sections": review.text_sections,
        "text_truncated": review.text_truncated,
        "text_chars": review.text_chars,
        "editor": {
            "verdict": review.editor_verdict,
            "reason": review.editor_reason,
            "disagreements": review.disagreements,
            "call_key": review.editor_call_key,
        },
        "reviews": reports,
        "red_flags": [
            {
                "text": f.text,
                "source": f.source,
                "raised_by": [
                    {k: r.get(k, "") for k in ("reviewer", "item", "answer", "quote", "section")}
                    for r in f.raised_by
                ],
            }
            for f in flags
        ],
        "score": review.score,
        "coverage": review.coverage,
        "red_flag_count": review.red_flag_count,
    }
