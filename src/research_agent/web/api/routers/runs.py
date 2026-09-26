import uuid
from pathlib import PurePosixPath

from fastapi import APIRouter, Depends, Header, Query, Response
from sqlalchemy import func, select, update

from ...db.models import Field, GoldLabel, GoldSet, Job, Run, Screening
from ...jobs import enqueue
from ..deps import get_db, get_settings, require_role
from ..errors import ApiError
from ..schemas import JobOut, RunCounts, RunDetailOut, RunOut, RunRequest, StartRunOut

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
    in_sr = None  # no gold set: "in the SR" does not apply
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
    return _run_out(db, run, RunDetailOut, manifest=public_manifest(run.manifest), counts=counts_for(db, run))


def public_manifest(value):
    """The manifest without server layout: every absolute path (e.g. `gold_path`) becomes its basename."""
    if isinstance(value, dict):
        return {k: public_manifest(v) for k, v in value.items()}
    if isinstance(value, list):
        return [public_manifest(v) for v in value]
    if isinstance(value, str) and PurePosixPath(value).is_absolute():
        return PurePosixPath(value).name
    return value


def job_out(job):
    run_id = (job.payload or {}).get("run_id")
    return JobOut(
        id=job.id,
        kind=job.kind,
        status=job.status,
        progress=job.progress or {},
        error=job.error,
        run_id=uuid.UUID(run_id) if run_id else None,
        attempts=job.attempts,
        created_at=job.created_at,
    )


def _check_active_cap(db, user, settings):
    active = db.scalar(
        select(func.count())
        .select_from(Job)
        .where(Job.created_by == user.id, Job.status.in_(("queued", "running")))
    )
    if active >= settings.max_active_jobs_per_user:
        raise ApiError(429, "too_many_active_runs", "You already have the maximum number of active runs")


@router.post("", response_model=StartRunOut, status_code=202)
def start_run(
    body: RunRequest,
    response: Response,
    idempotency_key: str | None = Header(None, max_length=100),
    user=Depends(require_role("member")),
    db=Depends(get_db),
    settings=Depends(get_settings),
):
    field = db.get(Field, body.field_id)
    if field is None:
        raise ApiError(404, "not_found", "No such field")
    if body.max_papers > settings.max_papers_cap:
        raise ApiError(422, "validation_error", f"max_papers must be at most {settings.max_papers_cap}")
    if body.mode == "demo" and not settings.allow_demo:
        raise ApiError(422, "validation_error", "demo mode is disabled on this deployment")
    if idempotency_key:
        existing = db.scalar(
            select(Job).where(Job.created_by == user.id, Job.idempotency_key == idempotency_key)
        )
        if existing is not None:
            response.status_code = 200
            return StartRunOut(job=job_out(existing), run_id=uuid.UUID(existing.payload["run_id"]))
    _check_active_cap(db, user, settings)
    contract = {"topic": field.topic, "max_papers": body.max_papers, "mode": body.mode}
    run = Run(
        field_id=field.id,
        kind="research",
        status="queued",
        manifest={"contract": contract},
        created_by=user.id,
    )
    db.add(run)
    db.flush()
    run.folder = str(settings.runs_dir / run.id.hex)
    payload = {"run_id": str(run.id), "field_id": str(field.id), **contract, "resume": False}
    job, created = enqueue(db, "research", payload, user.id, idempotency_key)
    if not created:  # lost a race with an identical request: drop the run we just made
        db.delete(run)
        db.commit()
        response.status_code = 200
        return StartRunOut(job=job_out(job), run_id=uuid.UUID(job.payload["run_id"]))
    db.commit()
    return StartRunOut(job=job_out(job), run_id=run.id)


@router.post("/{run_id}/resume", response_model=StartRunOut, status_code=202)
def resume_run(
    run_id: uuid.UUID,
    user=Depends(require_role("member")),
    db=Depends(get_db),
    settings=Depends(get_settings),
):
    run = db.get(Run, run_id)
    if run is None:
        raise ApiError(404, "not_found", "No such run")
    conflict = ApiError(409, "conflict", "Only a failed research run can be resumed")
    if run.kind != "research":
        raise conflict
    _check_active_cap(db, user, settings)
    active = db.scalar(
        select(func.count())
        .select_from(Job)
        .where(Job.status.in_(("queued", "running")), Job.payload["run_id"].astext == str(run.id))
    )
    if active:
        raise conflict
    # Check and act in one statement: of two concurrent resumes only one UPDATE finds the row `failed`
    # (the other waits for its row lock, then re-reads the row as `queued`).
    flipped = db.execute(
        update(Run)
        .where(Run.id == run.id, Run.kind == "research", Run.status == "failed")
        .values(status="queued", error=None)
        .execution_options(synchronize_session=False)
    ).rowcount
    if flipped != 1:
        raise conflict
    db.refresh(run)
    contract = run.manifest.get("contract") or {}
    field = db.get(Field, run.field_id)
    payload = {
        "run_id": str(run.id),
        "field_id": str(run.field_id),
        "topic": contract.get("topic", field.topic),
        "max_papers": contract.get("max_papers", 12),
        "mode": contract.get("mode", "live"),
        "resume": True,
    }
    job, _ = enqueue(db, "research", payload, user.id)
    db.commit()
    return StartRunOut(job=job_out(job), run_id=run.id)
