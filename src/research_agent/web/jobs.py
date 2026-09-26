"""PostgreSQL-backed job queue. Callers commit; claims use FOR UPDATE SKIP LOCKED."""

from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from .auth import utcnow
from .db.models import Job


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
    now = now or utcnow()
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
    job.status, job.locked_by, job.heartbeat_at, job.attempts = "running", worker_id, now, job.attempts + 1
    db.flush()
    return job


def heartbeat(db, job, now=None):
    job.heartbeat_at = now or utcnow()
    db.flush()


def set_progress(db, job, progress, now=None):
    job.progress = progress
    job.heartbeat_at = now or utcnow()
    db.flush()


def complete(db, job, progress=None):
    job.status, job.locked_by = "done", None
    if progress is not None:
        job.progress = progress
    db.flush()


def fail(db, job, error):
    job.status, job.locked_by, job.error = "failed", None, error
    db.flush()


def requeue_stale(db, stale_after_seconds, max_attempts, now=None):
    """Running jobs whose heartbeat stopped go back to the queue, or fail once attempts are spent."""
    now = now or utcnow()
    cutoff = now - timedelta(seconds=stale_after_seconds)
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
        else:
            job.status, job.error = "failed", "the worker stopped responding and no attempts are left"
    db.flush()
    return stale
