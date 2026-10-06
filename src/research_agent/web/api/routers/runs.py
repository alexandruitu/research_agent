import uuid
from datetime import date, datetime, time, timedelta
from pathlib import PurePosixPath
from typing import Literal

from fastapi import APIRouter, Depends, Header, Query, Response
from sqlalchemy import func, or_, select, update

from ... import fields as svc
from ... import review as review_svc
from ... import runs as runs_svc
from ...db.models import (
    Field,
    FieldVersion,
    GoldLabel,
    GoldSet,
    Job,
    Run,
    RunReviewer,
    Screening,
    SettingsVersion,
    SourceRow,
)
from ...jobs import active_research_job, enqueue, request_cancel
from ..deps import get_db, get_settings, require_role
from ..errors import ApiError
from ..schemas import (
    BulkDeleteOut,
    BulkIds,
    CallsSummaryOut,
    CancelOut,
    DeleteOut,
    JobOut,
    RerunRequest,
    RunCompareOut,
    RunCounts,
    RunDetailOut,
    RunLogOut,
    RunOut,
    RunPatch,
    RunRequest,
    StartRunOut,
)

router = APIRouter(prefix="/runs", tags=["runs"])

NOT_SCREENED = "rule"  # eval candidates without an abstract: a row in the table, but never screened


def conflict(exc):
    return ApiError(exc.status, exc.code, exc.message)


def get_run_or_404(db, run_id):
    run = db.get(Run, run_id)
    if run is None:
        raise ApiError(404, "not_found", "No such run")
    return run


def require_manage(user, run):
    try:
        runs_svc.require_manage(user, run)
    except runs_svc.RunConflict as exc:
        raise conflict(exc) from None


def _topic(run):
    manifest = run.manifest or {}
    return (
        (manifest.get("domain_request") or {}).get("topic") or (manifest.get("contract") or {}).get("topic")
    ) or ""


def search_warnings(run):
    """The run's skipped sources; a malformed entry (hand-edited report) is left out rather than failing."""
    rows = run.search_warnings
    if rows is None:
        return None
    keys = ("source", "error_type", "reason", "detail")
    return [
        {k: str(row.get(k) or "") for k in keys} for row in rows if isinstance(row, dict) and row.get("source")
    ]


def _run_out(db, run, cls=RunOut, names=None, **extra):
    field = db.get(Field, run.field_id)
    gold = db.get(GoldSet, run.gold_set_id) if run.gold_set_id else None
    paper_count = db.scalar(select(func.count()).select_from(Screening).where(Screening.run_id == run.id))
    models = {k: v for k, v in (run.manifest.get("models") or {}).items() if isinstance(v, str)}
    version = db.get(FieldVersion, run.field_version_id) if run.field_version_id else None
    review = db.get(SettingsVersion, run.settings_version_id) if run.settings_version_id else None
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
        field_version=version.version if version else None,
        settings_version=review.version if review else None,
        name=run.name,
        note=run.note or "",
        pinned=bool(run.pinned),
        created_by=run.created_by,
        created_by_name=(names if names is not None else runs_svc.user_names(db, [run.created_by])).get(
            run.created_by
        ),
        topic=_topic(run) or (field.topic if field else ""),
        started_at=run.started_at,
        search_warnings=search_warnings(run),
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


SORTS = {"created": Run.created_at, "status": Run.status}


@router.get("", response_model=list[RunOut])
def list_runs(
    kind: str | None = Query(None, pattern="^(research|eval)$"),
    field_id: uuid.UUID | None = None,
    status: str | None = Query(None, pattern="^(queued|running|done|failed|cancelled)$"),
    mine: bool = False,
    created_from: date | None = None,
    created_to: date | None = None,
    q: str | None = Query(None, max_length=200),
    sort: Literal["created", "name", "status", "papers"] = "created",
    direction: Literal["asc", "desc"] = "desc",
    user=Depends(require_role("viewer")),
    db=Depends(get_db),
):
    """Pinned runs first, then by `sort`. `q` matches the run's name, topic or field name."""
    papers = (
        select(func.count())
        .select_from(Screening)
        .where(Screening.run_id == Run.id)
        .correlate(Run)
        .scalar_subquery()
    )
    label = func.lower(func.coalesce(Run.name, Field.name))
    key = {"papers": papers, "name": label}.get(sort, SORTS.get(sort, Run.created_at))
    order = key.asc() if direction == "asc" else key.desc()
    stmt = select(Run).join(Field, Field.id == Run.field_id).order_by(Run.pinned.desc(), order, Run.id)
    if kind:
        stmt = stmt.where(Run.kind == kind)
    if field_id:
        stmt = stmt.where(Run.field_id == field_id)
    if status:
        stmt = stmt.where(Run.status == status)
    if mine:
        stmt = stmt.where(Run.created_by == user.id)
    if created_from:
        stmt = stmt.where(Run.created_at >= datetime.combine(created_from, time.min).astimezone())
    if created_to:
        stmt = stmt.where(
            Run.created_at < datetime.combine(created_to + timedelta(days=1), time.min).astimezone()
        )
    if q and q.strip():
        like = f"%{q.strip().lower()}%"
        stmt = stmt.where(
            or_(
                func.lower(func.coalesce(Run.name, "")).like(like),
                func.lower(Field.name).like(like),
                func.lower(func.coalesce(Run.manifest["contract"]["topic"].astext, "")).like(like),
                func.lower(func.coalesce(Run.manifest["domain_request"]["topic"].astext, "")).like(like),
            )
        )
    rows = db.scalars(stmt).all()
    names = runs_svc.user_names(db, [r.created_by for r in rows])
    return [_run_out(db, r, names=names) for r in rows]


def parse_ids(ids, minimum=1, maximum=200):
    try:
        parsed = list(dict.fromkeys(uuid.UUID(x.strip()) for x in ids.split(",") if x.strip()))
    except ValueError:
        raise ApiError(422, "validation_error", "ids must be run ids separated by commas") from None
    if not minimum <= len(parsed) <= maximum:
        raise ApiError(422, "validation_error", f"Give {minimum} to {maximum} distinct runs")
    return parsed


def download(body, media, name):
    return Response(
        content=body if isinstance(body, bytes) else body.encode("utf-8"),
        media_type=media,
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )


EXPORT_RESPONSES = {200: {"content": {"text/csv": {}, "application/x-bibtex": {}, "application/zip": {}}}}


@router.get("/compare", response_model=RunCompareOut)
def compare_runs(
    ids: str = Query(..., max_length=100),
    user=Depends(require_role("viewer")),
    db=Depends(get_db),
    settings=Depends(get_settings),
):
    """Two runs side by side: configuration rows and the papers whose outcome differs."""
    a_id, b_id = parse_ids(ids, 2, 2)
    a, b = get_run_or_404(db, a_id), get_run_or_404(db, b_id)
    names = runs_svc.user_names(db, [a.created_by, b.created_by])
    return {"runs": [_run_out(db, a, names=names), _run_out(db, b, names=names)]} | runs_svc.compare(
        db, settings, a, b
    )


@router.get("/export", response_class=Response, responses=EXPORT_RESPONSES)
def export_runs(
    ids: str = Query(..., max_length=8000),
    format: Literal["csv", "bibtex"] = "csv",
    user=Depends(require_role("viewer")),
    db=Depends(get_db),
):
    """Several runs in one file: CSV (a `run` column) or BibTeX of their kept papers."""
    runs = [get_run_or_404(db, run_id) for run_id in parse_ids(ids)]
    if format == "csv":
        return download(runs_svc.to_csv(db, runs), "text/csv; charset=utf-8", "runs.csv")
    return download(runs_svc.to_bibtex(db, runs), "application/x-bibtex; charset=utf-8", "runs.bib")


@router.get("/{run_id}/export", response_class=Response, responses=EXPORT_RESPONSES)
def export_run(
    run_id: uuid.UUID,
    format: Literal["csv", "bibtex", "bundle"] = "csv",
    user=Depends(require_role("viewer")),
    db=Depends(get_db),
    settings=Depends(get_settings),
):
    """One run: CSV of its papers, BibTeX of its kept papers, or a zip bundle of its reports and frozen
    requests (never the call cache, checkpoints, uploads, logs or keys)."""
    run = get_run_or_404(db, run_id)
    stem = f"run-{run.id.hex[:8]}"
    if format == "csv":
        return download(runs_svc.to_csv(db, [run]), "text/csv; charset=utf-8", f"{stem}.csv")
    if format == "bibtex":
        return download(runs_svc.to_bibtex(db, [run]), "application/x-bibtex; charset=utf-8", f"{stem}.bib")
    return download(runs_svc.bundle(settings, run), "application/zip", f"{stem}.zip")


@router.get("/{run_id}", response_model=RunDetailOut)
def get_run(
    run_id: uuid.UUID,
    user=Depends(require_role("viewer")),
    db=Depends(get_db),
    settings=Depends(get_settings),
):
    run = get_run_or_404(db, run_id)
    line = runs_svc.timeline(settings, run)
    active = active_research_job(db, run.id)
    return _run_out(
        db,
        run,
        RunDetailOut,
        manifest=public_manifest(run.manifest),
        counts=counts_for(db, run),
        config=runs_svc.frozen_config(db, settings, run),
        timeline=line,
        wall_seconds=runs_svc.wall_seconds(run, line),
        resume=runs_svc.resume_state(settings, run),
        links={
            "papers": f"/?run={run.id}",
            "evals": runs_svc.evals_from(db, run),
            "library_count": runs_svc.library_count(db, run),
        },
        can_manage=runs_svc.can_manage(user, run),
        active_job_id=active.id if active else None,
    )


@router.patch("/{run_id}", response_model=RunOut)
def patch_run(run_id: uuid.UUID, body: RunPatch, user=Depends(require_role("member")), db=Depends(get_db)):
    """Rename, annotate or pin a run (its creator or an admin). A blank name removes it."""
    run = get_run_or_404(db, run_id)
    require_manage(user, run)
    sent = body.model_fields_set
    if "name" in sent:
        run.name = (body.name or "").strip() or None
    if "note" in sent:
        run.note = (body.note or "").strip()
    if "pinned" in sent and body.pinned is not None:
        run.pinned = body.pinned
    db.commit()
    return _run_out(db, run)


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


def check_active_cap(db, user, settings):
    active = db.scalar(
        select(func.count())
        .select_from(Job)
        .where(Job.created_by == user.id, Job.status.in_(("queued", "running")))
    )
    if active >= settings.max_active_jobs_per_user:
        raise ApiError(429, "too_many_active_runs", "You already have the maximum number of active runs")


def _existing(db, user, idempotency_key, response):
    if not idempotency_key:
        return None
    existing = db.scalar(select(Job).where(Job.created_by == user.id, Job.idempotency_key == idempotency_key))
    if existing is None:
        return None
    response.status_code = 200
    return StartRunOut(job=job_out(existing), run_id=uuid.UUID(existing.payload["run_id"]))


def _current_requests(db, field):
    """(field version, domain request or None, review request, review settings, reviewer versions) for a new run
    from the field's current version and the current review settings."""
    version = svc.get_version(db, field)
    domain = None
    if version is None or svc.is_legacy(db, version):
        # A legacy field (one topic question): today's positional-topic run, which searches Europe PMC.
        europepmc = db.get(SourceRow, "europepmc")
        if europepmc is None or not europepmc.enabled:
            raise ApiError(422, "no_enabled_source", "None of this field's sources is enabled")
    else:
        try:
            domain = svc.domain_for_version(db, field, version)
        except svc.FieldConflict as exc:
            raise ApiError(exc.status, exc.code, exc.message) from None
    try:  # every new run is a panel run: the current review settings and default panel, frozen
        review, review_settings, reviewers = review_svc.review_for_run(db)
    except review_svc.ReviewConflict as exc:
        raise ApiError(exc.status, exc.code, exc.message) from None
    return version, domain, review, review_settings.id, [r.id for r in reviewers]


def _create_run(db, user, settings, response, idempotency_key, field, plan):
    """Queue a new research run. `plan` = {field_version_id, settings_version_id, reviewer_version_ids, domain,
    review, topic, max_papers, mode}."""
    domain, review = plan["domain"], plan["review"]
    contract = {"topic": plan["topic"] if domain is None else domain["topic"]}
    contract |= {"max_papers": plan["max_papers"], "mode": plan["mode"]}
    manifest = {"contract": contract} | ({"domain_request": domain} if domain else {})
    if review:
        manifest["review_request"] = review
    run = Run(
        field_id=field.id,
        field_version_id=plan["field_version_id"],
        settings_version_id=plan["settings_version_id"],
        kind="research",
        status="queued",
        manifest=manifest,
        created_by=user.id,
    )
    db.add(run)
    db.flush()
    for position, reviewer_version_id in enumerate(plan["reviewer_version_ids"]):
        db.add(RunReviewer(run_id=run.id, position=position, reviewer_version_id=reviewer_version_id))
    run.folder = str(settings.runs_dir / run.id.hex)
    payload = {"run_id": str(run.id), "field_id": str(field.id), **contract, "resume": False}
    if domain:
        payload["domain"] = domain
    if review:
        payload["review"] = review
    job, created = enqueue(db, "research", payload, user.id, idempotency_key)
    if not created:  # lost a race with an identical request: drop the run we just made
        db.delete(run)
        db.commit()
        response.status_code = 200
        return StartRunOut(job=job_out(job), run_id=uuid.UUID(job.payload["run_id"]))
    db.commit()
    return StartRunOut(job=job_out(job), run_id=run.id)


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
    if (existing := _existing(db, user, idempotency_key, response)) is not None:
        return existing
    if field.archived_at is not None:
        raise ApiError(409, "archived", "This field is archived; restore it first")
    version, domain, review, settings_id, reviewer_ids = _current_requests(db, field)
    check_active_cap(db, user, settings)
    plan = {
        "field_version_id": version.id if version else None,
        "settings_version_id": settings_id,
        "reviewer_version_ids": reviewer_ids,
        "domain": domain,
        "review": review,
        "topic": field.topic,
        "max_papers": body.max_papers,
        "mode": body.mode,
    }
    return _create_run(db, user, settings, response, idempotency_key, field, plan)


@router.post("/{run_id}/rerun", response_model=StartRunOut, status_code=202)
def rerun(
    run_id: uuid.UUID,
    body: RerunRequest,
    response: Response,
    idempotency_key: str | None = Header(None, max_length=100),
    user=Depends(require_role("member")),
    db=Depends(get_db),
    settings=Depends(get_settings),
):
    """A new run from this one: `same` reuses its frozen domain and review requests (field version, review
    settings, panel versions) exactly; `current` uses the field's current version and the current review
    settings. Both keep its max_papers and mode; the new run belongs to the caller."""
    source = get_run_or_404(db, run_id)
    if source.kind != "research":
        raise ApiError(409, "conflict", "Only a research run can be run again")
    if (existing := _existing(db, user, idempotency_key, response)) is not None:
        return existing
    field = db.get(Field, source.field_id)
    if field.archived_at is not None:
        raise ApiError(409, "archived", "This field is archived; restore it first")
    contract = (source.manifest or {}).get("contract") or {}
    mode = contract.get("mode") or "live"
    if mode == "demo" and not settings.allow_demo:
        raise ApiError(422, "validation_error", "demo mode is disabled on this deployment")
    max_papers = min(int(contract.get("max_papers") or settings.max_papers_cap), settings.max_papers_cap)
    if body.config == "same":
        plan = {
            "field_version_id": source.field_version_id,
            "settings_version_id": source.settings_version_id,
            "reviewer_version_ids": list(
                db.scalars(
                    select(RunReviewer.reviewer_version_id)
                    .where(RunReviewer.run_id == source.id)
                    .order_by(RunReviewer.position)
                )
            ),
            "domain": (source.manifest or {}).get("domain_request"),
            "review": (source.manifest or {}).get("review_request"),
            "topic": contract.get("topic") or field.topic,
        }
    else:
        version, domain, review, settings_id, reviewer_ids = _current_requests(db, field)
        plan = {
            "field_version_id": version.id if version else None,
            "settings_version_id": settings_id,
            "reviewer_version_ids": reviewer_ids,
            "domain": domain,
            "review": review,
            "topic": field.topic,
        }
    check_active_cap(db, user, settings)
    plan |= {"max_papers": max_papers, "mode": mode}
    return _create_run(db, user, settings, response, idempotency_key, field, plan)


@router.post("/{run_id}/resume", response_model=StartRunOut, status_code=202)
def resume_run(
    run_id: uuid.UUID,
    user=Depends(require_role("member")),
    db=Depends(get_db),
    settings=Depends(get_settings),
):
    run = get_run_or_404(db, run_id)
    refused = ApiError(409, "conflict", "Only a failed or cancelled research run can be resumed")
    if run.kind != "research":
        raise refused
    require_manage(user, run)
    state = runs_svc.resume_state(settings, run)
    if state["code"] == "prompt_version_changed":
        raise ApiError(409, state["code"], state["reason"])
    check_active_cap(db, user, settings)
    active = db.scalar(
        select(func.count())
        .select_from(Job)
        .where(Job.status.in_(("queued", "running")), Job.payload["run_id"].astext == str(run.id))
    )
    if active:
        raise refused
    # Check and act in one statement: of two concurrent resumes only one UPDATE finds the row resumable
    # (the other waits for its row lock, then re-reads the row as `queued`).
    flipped = db.execute(
        update(Run)
        .where(Run.id == run.id, Run.kind == "research", Run.status.in_(runs_svc.RESUMABLE))
        .values(status="queued", error=None, finished_at=None)
        .execution_options(synchronize_session=False)
    ).rowcount
    if flipped != 1:
        raise refused
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
    if run.manifest.get("domain_request"):  # started again from scratch when it has no manifest yet
        payload["domain"] = run.manifest["domain_request"]
    if run.manifest.get("review_request"):
        payload["review"] = run.manifest["review_request"]
    job, _ = enqueue(db, "research", payload, user.id)
    db.commit()
    return StartRunOut(job=job_out(job), run_id=run.id)


@router.post("/delete", response_model=BulkDeleteOut)
def delete_runs(
    body: BulkIds,
    user=Depends(require_role("member")),
    db=Depends(get_db),
    settings=Depends(get_settings),
):
    """Delete several runs; each is checked on its own and refusals are listed, not raised."""
    deleted, refused = [], []
    for run_id in dict.fromkeys(body.ids):
        run = db.get(Run, run_id)
        if run is None:
            refused.append({"id": run_id, "code": "not_found", "message": "No such run"})
            continue
        try:
            runs_svc.check_deletable(db, user, run)
        except runs_svc.RunConflict as exc:
            refused.append({"id": run_id, "code": exc.code, "message": exc.message})
            continue
        runs_svc.delete_run(db, settings, user, run)
        db.commit()  # each folder move follows its own committed delete
        deleted.append(run_id)
    return BulkDeleteOut(deleted=deleted, refused=refused)


@router.post("/{run_id}/cancel", response_model=CancelOut)
def cancel_run(
    run_id: uuid.UUID, response: Response, user=Depends(require_role("member")), db=Depends(get_db)
):
    """Queued: cancelled now (200). Running: its worker stops the child at the next poll (202); the run then
    shows `cancelled` and can be resumed from its checkpoint."""
    run = get_run_or_404(db, run_id)
    require_manage(user, run)
    outcome = request_cancel(db, run.id) if run.kind == "research" else None
    if outcome is None:
        raise ApiError(409, "not_active", "Only a queued or running research run can be cancelled")
    db.commit()
    if outcome == "requested":
        response.status_code = 202
        return CancelOut(status="cancelling")
    return CancelOut(status="cancelled")


@router.delete("/{run_id}", response_model=DeleteOut)
def delete_run(
    run_id: uuid.UUID,
    user=Depends(require_role("member")),
    db=Depends(get_db),
    settings=Depends(get_settings),
):
    """Delete a finished, failed or cancelled research run (its creator or an admin). Library items keep their
    snapshot; the folder moves to the trash under the runs directory (never deleted)."""
    run = get_run_or_404(db, run_id)
    try:
        runs_svc.check_deletable(db, user, run)
    except runs_svc.RunConflict as exc:
        raise conflict(exc) from None
    db.commit()
    folder = runs_svc.delete_run(db, settings, user, run)
    db.commit()
    return DeleteOut(id=run_id, folder=folder)


@router.get(
    "/{run_id}/log",
    response_model=RunLogOut,
    responses={200: {"content": {"text/plain": {}}}},
)
def run_log(
    run_id: uuid.UUID,
    lines: int = Query(200, ge=1, le=runs_svc.LOG_MAX_LINES),
    download: bool = False,
    user=Depends(require_role("member")),
    db=Depends(get_db),
    settings=Depends(get_settings),
):
    """The tail of the run's worker.log with every secret value replaced by ***, the failed stage and reason,
    and the model retry lines. `download=true` returns the tail read (at most 256 KiB) as a text file."""
    run = get_run_or_404(db, run_id)
    tail = runs_svc.log_tail(settings, run, lines)
    if download:
        return Response(
            content=tail["full"].encode("utf-8"),
            media_type="text/plain; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="run-{run.id.hex[:8]}-worker.log"'},
        )
    return RunLogOut(**{k: v for k, v in tail.items() if k != "full"})


@router.get("/{run_id}/calls", response_model=CallsSummaryOut)
def run_calls(
    run_id: uuid.UUID,
    user=Depends(require_role("member")),
    db=Depends(get_db),
    settings=Depends(get_settings),
):
    """Model calls of the run per role and model, with an estimated cost (approximate list prices)."""
    return runs_svc.calls_summary(settings, get_run_or_404(db, run_id))
