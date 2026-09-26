"""The paper table: one run's papers joined with every stage, filtered, sorted and paged in SQL."""

from collections import defaultdict
from dataclasses import dataclass

from sqlalchemy import and_, exists, func, or_, select
from sqlalchemy.orm import aliased

from .db.models import (
    Criterion,
    CriterionScore,
    EvidenceClaim,
    GoldLabel,
    Paper,
    Ranking,
    Review,
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


def _criterion_probability(key):
    return (
        select(CriterionScore.probability)
        .join(Criterion, Criterion.id == CriterionScore.criterion_id)
        .where(CriterionScore.screening_id == Screening.id, Criterion.key == key)
        .limit(1)
        .scalar_subquery()
    )


def expects_downstream(run, screening):
    """Extraction and reviews are expected only in research runs, for papers that were kept and had an abstract."""
    return run.kind == "research" and screening.decision != "exclude" and screening.tier != NOT_SCREENED


def build_row(run, screening, paper, scores, claims, verdicts, rank, label):
    a, b, adjudicator = verdicts
    expected = expects_downstream(run, screening)
    if claims:
        extract = {"claims": claims, "quotes_verified": True}
    else:
        extract = {"missing": True} if expected else None
    if a is not None or b is not None:
        reviews = {"a": a, "b": b, "adjudicated": adjudicator is not None, "adjudicator": adjudicator}
    else:
        reviews = {"missing": True} if expected else None
    return {
        "paper": {
            "id": paper.id,
            "source_id": paper.source_id,
            "title": paper.title,
            "year": paper.year,
            "doi": paper.doi,
        },
        "found_by": screening.found_by,
        "in_sr": None if run.gold_set_id is None else label == "include",
        "screen": {
            "tier": screening.tier,
            "decision": screening.decision,
            "jev_decision": screening.jev_decision,
            "llm_decision": screening.llm_decision,
            "criteria": scores,
        },
        "extract": extract,
        "reviews": reviews,
        "rank": {"score": rank[0], "position": rank[1]} if rank[0] is not None else None,
    }


def _sort_key(sort):
    """`sort` is validated by the router; anything else is refused here too (never raw input into ORDER BY)."""
    if sort == "title":
        return func.lower(Paper.title)
    if sort == "year":
        return Paper.year
    if sort == "score":
        return Ranking.score
    if sort.startswith("criterion:"):
        return _criterion_probability(sort.split(":", 1)[1])  # a bound parameter, not SQL text
    raise ValueError(f"unknown sort {sort!r}")


def paper_table(db, run, q):
    ra, rb, rj, gl = aliased(Review), aliased(Review), aliased(Review), aliased(GoldLabel)
    claims = (
        select(EvidenceClaim.paper_id.label("paper_id"), func.count().label("n"))
        .where(EvidenceClaim.run_id == run.id)
        .group_by(EvidenceClaim.paper_id)
        .subquery()
    )

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
            claims.c.n,
            Ranking.score,
            Ranking.position,
            gl.label,
        )
        .join(Paper, Paper.id == Screening.paper_id)
        .outerjoin(ra, review_join(ra, "a"))
        .outerjoin(rb, review_join(rb, "b"))
        .outerjoin(rj, review_join(rj, "adjudicator"))
        .outerjoin(claims, claims.c.paper_id == Screening.paper_id)
        .outerjoin(Ranking, and_(Ranking.run_id == Screening.run_id, Ranking.paper_id == Screening.paper_id))
        .outerjoin(gl, and_(gl.gold_set_id == run.gold_set_id, gl.paper_id == Screening.paper_id))
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
    if q.criterion:
        conditions = [CriterionScore.screening_id == Screening.id, Criterion.key == q.criterion]
        if q.p_min is not None:
            conditions.append(CriterionScore.probability >= q.p_min)
        if q.p_max is not None:
            conditions.append(CriterionScore.probability <= q.p_max)
        stmt = stmt.where(
            exists().where(CriterionScore.criterion_id == Criterion.id, *conditions).correlate(Screening)
        )

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

    scores = defaultdict(dict)
    ids = [r[0].id for r in rows]
    if ids:
        for screening_id, name, probability in db.execute(
            select(CriterionScore.screening_id, Criterion.key, CriterionScore.probability)
            .join(Criterion, Criterion.id == CriterionScore.criterion_id)
            .where(CriterionScore.screening_id.in_(ids))
        ):
            scores[screening_id][name] = probability
    items = [
        build_row(run, s, p, scores[s.id], n or 0, (va, vb, vj), (score, position), label)
        for s, p, va, vb, vj, n, score, position, label in rows
    ]
    return items, total


ROLE_ORDER = {"a": 0, "b": 1, "adjudicator": 2}


def paper_drawer(db, run, paper):
    screening = db.scalar(select(Screening).where(Screening.run_id == run.id, Screening.paper_id == paper.id))
    if screening is None:
        return None
    scores = db.execute(
        select(Criterion.key, Criterion.question, CriterionScore.probability, CriterionScore.jev_version)
        .join(CriterionScore, CriterionScore.criterion_id == Criterion.id)
        .where(CriterionScore.screening_id == screening.id)
        .order_by(Criterion.position, Criterion.key)
    ).all()
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
        "paper": {
            "id": paper.id,
            "source_id": paper.source_id,
            "title": paper.title,
            "abstract": paper.abstract,
            "year": paper.year,
            "doi": paper.doi,
        },
        "found_by": screening.found_by,
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
