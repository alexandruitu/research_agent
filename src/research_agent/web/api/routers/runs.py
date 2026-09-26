import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select

from ...db.models import Field, GoldLabel, GoldSet, Run, Screening
from ..deps import get_db, require_role
from ..errors import ApiError
from ..schemas import RunCounts, RunDetailOut, RunOut

router = APIRouter(prefix="/runs", tags=["runs"])

NOT_SCREENED = "rule"  # eval candidates without an abstract: a row in the table, but never screened


def _run_out(db, run, cls=RunOut, **extra):
    field = db.get(Field, run.field_id)
    gold = db.get(GoldSet, run.gold_set_id) if run.gold_set_id else None
    paper_count = db.scalar(select(func.count()).select_from(Screening).where(Screening.run_id == run.id))
    models = {k: v for k, v in (run.manifest.get("models") or {}).items() if isinstance(v, str)}
    return cls(
        id=run.id,
        field_id=run.field_id,
        field_name=field.name,
        kind=run.kind,
        status=run.status,
        finished_at=run.finished_at,
        created_at=run.created_at,
        gold_set_name=gold.name if gold else None,
        paper_count=paper_count,
        error=run.error,
        models=models,
        **extra,
    )


def counts_for(db, run):
    """Screened/kept/dropped/escalated leave out `rule` rows so they equal the eval report's numbers;
    `in_sr` counts every SR-included paper in the run (what the paper table's "in the SR" filter shows)."""
    rows = db.execute(
        select(Screening.decision, Screening.jev_decision).where(
            Screening.run_id == run.id, Screening.tier != NOT_SCREENED
        )
    ).all()
    in_sr = 0
    if run.gold_set_id:
        in_sr = db.scalar(
            select(func.count())
            .select_from(GoldLabel)
            .join(Screening, Screening.paper_id == GoldLabel.paper_id)
            .where(
                Screening.run_id == run.id,
                GoldLabel.gold_set_id == run.gold_set_id,
                GoldLabel.label == "include",
            )
        )
    kept = sum(1 for decision, _ in rows if decision != "exclude")
    return RunCounts(
        screened=len(rows),
        kept=kept,
        dropped=len(rows) - kept,
        escalated=sum(1 for _, jev in rows if jev == "escalate"),
        in_sr=in_sr,
    )


@router.get("", response_model=list[RunOut])
def list_runs(
    kind: str | None = Query(None, pattern="^(research|eval)$"),
    field_id: uuid.UUID | None = None,
    user=Depends(require_role("viewer")),
    db=Depends(get_db),
):
    stmt = select(Run).order_by(Run.created_at.desc())
    if kind:
        stmt = stmt.where(Run.kind == kind)
    if field_id:
        stmt = stmt.where(Run.field_id == field_id)
    return [_run_out(db, r) for r in db.scalars(stmt)]


@router.get("/{run_id}", response_model=RunDetailOut)
def get_run(run_id: uuid.UUID, user=Depends(require_role("viewer")), db=Depends(get_db)):
    run = db.get(Run, run_id)
    if run is None:
        raise ApiError(404, "not_found", "No such run")
    return _run_out(db, run, RunDetailOut, manifest=run.manifest, counts=counts_for(db, run))
