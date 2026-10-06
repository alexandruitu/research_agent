"""Evaluations: list, detail, compare, cost estimate, start (worker job `eval_run`)."""

import uuid

from fastapi import APIRouter, Depends, Header, Query, Response
from sqlalchemy import select

from ... import evals as svc
from ...db.models import EvalReport, GoldSet, Job, RatingSample, Run
from ...jobs import enqueue
from ..deps import get_db, get_settings, require_role
from ..errors import ApiError
from ..schemas import (
    CompareOut,
    EstimateOut,
    EvalDetailOut,
    EvalHeadline,
    EvalJobOut,
    EvalRequest,
    EvalSummaryOut,
    GoldSetOut,
    JobOut,
)
from .runs import check_active_cap, job_out, search_warnings

router = APIRouter(prefix="/evals", tags=["evals"])
ACTIVE_JOBS_LISTED = 20


def headline(metrics):  # kept for callers of the screening headline
    return EvalHeadline(**svc.headline(metrics, "screening"))


def _gold(db, settings, report):
    row = db.get(GoldSet, report.gold_set_id) if report.gold_set_id else None
    return (GoldSetOut(**svc.gold_set_out(settings, row)), row.name) if row else (None, None)


def summary(db, settings, report):
    gold, name = _gold(db, settings, report)
    return EvalSummaryOut(
        id=report.id,
        gold_set=gold,
        run_id=report.run_id,
        created_at=report.created_at,
        headline=EvalHeadline(**svc.headline(report)),
        kind=report.kind,
        status="done",
        parent_id=report.parent_id,
        chips=svc.chips(report, name),
    )


def _run_dirs(value):
    if isinstance(value, dict):
        for key, item in value.items():
            if key == "run_dir" and isinstance(item, str):
                yield item
            else:
                yield from _run_dirs(item)
    elif isinstance(value, list):
        for item in value:
            yield from _run_dirs(item)


def source_search_warnings(db, report):
    """Warnings of the research run a report was built from (`run_dir` in its frozen config), if any."""
    for folder in _run_dirs(report.config or {}):
        run = db.scalar(select(Run).where(Run.folder == folder))
        if run is not None and (warnings := search_warnings(run)):
            return warnings
    return None


def _pending(db):
    jobs = db.scalars(
        select(Job)
        .where(Job.kind == "eval_run", Job.status.in_(("queued", "running", "failed")))
        .order_by(Job.created_at.desc())
        .limit(ACTIVE_JOBS_LISTED)
    )
    return [
        EvalJobOut(
            kind=job.payload.get("kind", "screening"),
            parent_id=uuid.UUID(job.payload["parent_id"]) if job.payload.get("parent_id") else None,
            chips=[c for c in (job.payload.get("mode"),) if c],
            job=job_out(job),
        )
        for job in jobs
    ]


def _raise(exc):
    raise ApiError(exc.status, exc.code, exc.message) from None


@router.get("", response_model=list[EvalSummaryOut])
def list_evals(
    kind: str | None = Query(None, pattern="^(screening|panel|ablation|human)$"),
    user=Depends(require_role("viewer")),
    db=Depends(get_db),
    settings=Depends(get_settings),
):
    """Finished reports, newest first."""
    query = select(EvalReport).order_by(EvalReport.created_at.desc())
    if kind:
        query = query.where(EvalReport.kind == kind)
    return [summary(db, settings, r) for r in db.scalars(query)]


@router.get("/jobs", response_model=list[EvalJobOut])
def list_eval_jobs(user=Depends(require_role("viewer")), db=Depends(get_db)):
    """Evaluations without a report yet (queued, running, failed), newest first, at most 20."""
    return _pending(db)


@router.get("/compare", response_model=CompareOut)
def compare_evals(
    ids: str = Query(..., max_length=200),
    user=Depends(require_role("viewer")),
    db=Depends(get_db),
    settings=Depends(get_settings),
):
    try:
        wanted = list(dict.fromkeys(uuid.UUID(part.strip()) for part in ids.split(",") if part.strip()))
    except ValueError:
        raise ApiError(422, "validation_error", "ids must be report ids separated by commas") from None
    if not 2 <= len(wanted) <= 3:
        raise ApiError(422, "validation_error", "Compare 2 or 3 reports")
    reports = [db.get(EvalReport, i) for i in wanted]
    if any(r is None for r in reports):
        raise ApiError(404, "not_found", "No such eval report")
    try:
        family, metrics, config = svc.compare(reports)
    except svc.EvalConflict as exc:
        _raise(exc)
    return CompareOut(
        family=family, reports=[summary(db, settings, r) for r in reports], metrics=metrics, config=config
    )


@router.post("/estimate", response_model=EstimateOut)
def estimate_eval(
    body: EvalRequest,
    user=Depends(require_role("member")),
    db=Depends(get_db),
    settings=Depends(get_settings),
):
    try:
        return svc.estimate(db, settings, body)
    except svc.EvalConflict as exc:
        _raise(exc)


@router.post("", response_model=JobOut, status_code=202)
def start_eval(
    body: EvalRequest,
    response: Response,
    idempotency_key: str | None = Header(None, max_length=100),
    user=Depends(require_role("member")),
    db=Depends(get_db),
    settings=Depends(get_settings),
):
    if idempotency_key:
        existing = db.scalar(
            select(Job).where(Job.created_by == user.id, Job.idempotency_key == idempotency_key)
        )
        if existing is not None:
            response.status_code = 200
            return job_out(existing)
    try:
        payload = svc.build_payload(db, settings, body)
    except svc.EvalConflict as exc:
        _raise(exc)
    check_active_cap(db, user, settings)
    job, created = enqueue(db, "eval_run", payload, user.id, idempotency_key)
    if not created:
        response.status_code = 200
    db.commit()
    return job_out(job)


@router.get("/{eval_id}", response_model=EvalDetailOut)
def get_eval(
    eval_id: uuid.UUID,
    user=Depends(require_role("viewer")),
    db=Depends(get_db),
    settings=Depends(get_settings),
):
    report = db.get(EvalReport, eval_id)
    if report is None:
        raise ApiError(404, "not_found", "No such eval report")
    gold, name = _gold(db, settings, report)
    samples = db.scalars(select(RatingSample.id).where(RatingSample.eval_report_id == report.id))
    return EvalDetailOut(
        id=report.id,
        gold_set=gold,
        run_id=report.run_id,
        created_at=report.created_at,
        metrics=report.metrics,
        agreement=report.agreement,
        kind=report.kind,
        parent_id=report.parent_id,
        config=svc.public(report.config or {}),
        chips=svc.chips(report, name),
        headline=EvalHeadline(**svc.headline(report)),
        children=[
            {"id": c.id, "kind": c.kind, "created_at": c.created_at}
            for c in svc.latest_children(db, report.id)
        ],
        rating_sample_ids=list(samples),
        source_search_warnings=source_search_warnings(db, report),
    )
