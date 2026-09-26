"""PostgreSQL-backed job queue. Callers commit; claims use FOR UPDATE SKIP LOCKED.

heartbeat, set_progress, complete, fail and release change a job only while the given worker owns it
(status running, locked_by == worker_id) and return whether they did.

Heartbeats are stamped and compared with the database clock (`now()`), so workers on hosts whose clocks
disagree cannot take live jobs from each other. `now=` overrides it (tests)."""

from datetime import timedelta

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm.attributes import set_committed_value

from .db.models import Job, Run

STALE_ERROR = "the worker stopped responding and no attempts are left"


def _now(now):
    return func.now() if now is None else now


def enqueue(db, kind, payload, created_by, idempotency_key=None):
    """Returns (job, created). The same (user, idempotency key) always yields the same job."""
    if idempotency_key:
        existing = db.scalar(
            select(Job).where(Job.created_by == created_by, Job.idempotency_key == idempotency_key)
        )
        if existing is not None:
            return existing, False
    job = Job(
        kind=kind, payload=payload, status="queued", created_by=created_by, idempotency_key=idempotency_key
    )
    try:
        with db.begin_nested():
            db.add(job)
            db.flush()
    except IntegrityError:  # a concurrent identical request won the race
        existing = db.scalar(
            select(Job).where(Job.created_by == created_by, Job.idempotency_key == idempotency_key)
        )
        if existing is None:
            raise
        return existing, False
    return job, True


def claim(db, worker_id, now=None):
    job = db.scalar(
        select(Job)
        .where(Job.status == "queued")
        .order_by(Job.created_at, Job.id)
        .with_for_update(skip_locked=True)
        .limit(1)
        .execution_options(populate_existing=True)  # the locked row, not a stale copy held by this session
    )
    if job is None:
        return None
    job.status, job.locked_by, job.heartbeat_at, job.attempts = (
        "running",
        worker_id,
        _now(now),
        job.attempts + 1,
    )
    db.flush()
    return job


def _update_owned(db, job, worker_id, **values):
    """Apply `values` only while `worker_id` still holds the running job; returns whether it did.

    A worker whose job was requeued as stale (and perhaps claimed by another worker) must not
    overwrite it, so the ownership check is part of the UPDATE, not a read of a possibly stale copy."""
    row = db.execute(
        update(Job)
        .where(Job.id == job.id, Job.status == "running", Job.locked_by == worker_id)
        .values(**values)
        .returning(*(getattr(Job, name) for name in values))
        .execution_options(synchronize_session=False)
    ).first()
    if row is None:
        return False
    for name, value in zip(values, row, strict=True):  # mirror the row without marking the object dirty
        set_committed_value(job, name, value)
    return True


def _set_run(db, job, **values):
    """Mirror a research job's state onto its run."""
    run_id = (job.payload or {}).get("run_id")
    if job.kind == "research" and run_id and (run := db.get(Run, run_id)) is not None:
        for name, value in values.items():
            setattr(run, name, value)


def heartbeat(db, job, now=None, *, worker_id):
    return _update_owned(db, job, worker_id, heartbeat_at=_now(now))


def set_progress(db, job, progress, now=None, *, worker_id):
    return _update_owned(db, job, worker_id, progress=progress, heartbeat_at=_now(now))


def complete(db, job, progress=None, *, worker_id):
    values = {"status": "done", "locked_by": None}
    if progress is not None:
        values["progress"] = progress
    return _update_owned(db, job, worker_id, **values)


def fail(db, job, error, *, worker_id):
    return _update_owned(db, job, worker_id, status="failed", locked_by=None, error=error)


def release(db, job, *, worker_id):
    """Give a job back to the queue without counting the attempt (the worker is stopping, or the run
    folder is busy); a research job's run is queued again."""
    if not _update_owned(db, job, worker_id, status="queued", locked_by=None, attempts=Job.attempts - 1):
        return False
    _set_run(db, job, status="queued")
    db.flush()
    return True


def requeue_stale(db, stale_after_seconds, max_attempts, now=None):
    """Running jobs whose heartbeat stopped go back to the queue, or fail once attempts are spent.
    A research job's run follows it: queued again, or failed with the same message."""
    cutoff = _now(now) - timedelta(seconds=stale_after_seconds)
    stale = db.scalars(
        select(Job)
        .where(Job.status == "running", Job.heartbeat_at < cutoff)
        .with_for_update(skip_locked=True)
        .execution_options(populate_existing=True)  # attempts must come from the locked row
    ).all()
    for job in stale:
        job.locked_by = None
        if job.attempts < max_attempts:
            job.status = "queued"
            _set_run(db, job, status="queued")
        else:
            job.status, job.error = "failed", STALE_ERROR
            _set_run(db, job, status="failed", error=STALE_ERROR)
    db.flush()
    return stale
