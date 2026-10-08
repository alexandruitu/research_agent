"""Field alerts (spec 2026-10-08): schedule, seen set, alert runs and their digests. All decided in code.

Times: an alert's weekday/hour are the server's local time; next_run_at is stored as an aware timestamp."""

import re
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select, union

from ..seen import SEEN_FILE, write_seen
from .db.models import (
    Alert,
    AlertSubscription,
    Digest,
    Field,
    LibraryItem,
    Paper,
    PaperReview,
    Run,
    RunReviewer,
    Screening,
)
from .fields import settings_row
from .jobs import enqueue

CADENCES = ("weekly", "daily")
MIN_GROUPS = {"read_first": ("read_first",), "worth_a_look": ("read_first", "worth_a_look")}
GROUP_ORDER = {"read_first": 0, "worth_a_look": 1}
MAX_FAILURES = 3
MAX_NEW = 200
MAX_WHY = 300


class AlertError(Exception):
    """An alert run cannot start; the message is safe to show (it goes into a failed digest)."""

    def __init__(self, message, status=422, code="alert_error"):
        super().__init__(message)
        self.message, self.status, self.code = message, status, code


# --- schedule ----------------------------------------------------------------------------------------------------


def next_slot(cadence, weekday, hour, after):
    """The first slot strictly after `after` (aware), in server local time; DST-correct (local wall clock)."""
    local = after.astimezone().replace(tzinfo=None)
    slot = local.replace(hour=hour, minute=0, second=0, microsecond=0)
    if cadence == "daily":
        if slot <= local:
            slot += timedelta(days=1)
    else:
        slot += timedelta(days=(weekday - slot.weekday()) % 7)
        if slot <= local:
            slot += timedelta(days=7)
    return slot.astimezone()  # a naive local time -> aware


def next_run_of(alert, after):
    return next_slot(alert.cadence, alert.weekday, alert.hour, after)


def local_day_start(now):
    return (
        now.astimezone().replace(tzinfo=None).replace(hour=0, minute=0, second=0, microsecond=0).astimezone()
    )


def runs_today(db, now):
    """Alert runs created since local midnight of `now` (the daily budget counts these)."""
    return db.scalar(
        select(func.count())
        .select_from(Run)
        .where(Run.trigger == "alert", Run.created_at >= local_day_start(now), Run.created_at <= now)
    )


def alert_years(years, years_back, this_year):
    """The alert's search window (this year - years_back .. this year) within the field's own range."""
    start, end = this_year - years_back, this_year
    if years.get("from"):
        start = max(start, years["from"])
    if years.get("to"):
        end = min(end, years["to"])
    if start > end:
        raise AlertError("The field's year range ends before the alert's window; nothing new can be found")
    return {"from": start, "to": end}


# --- seen set ----------------------------------------------------------------------------------------------------


def seen_records(db, field_id):
    """Papers screened in any finished run of the field (any version) plus the team library."""
    finished = select(Run.id).where(Run.field_id == field_id, Run.status == "done")
    columns = (Paper.doi, Paper.source_id, Paper.title, Paper.year)
    screened = (
        select(*columns).join(Screening, Screening.paper_id == Paper.id).where(Screening.run_id.in_(finished))
    )
    library = select(*columns).join(LibraryItem, LibraryItem.paper_id == Paper.id)
    rows = db.execute(union(screened, library)).all()
    return [{"doi": r.doi or "", "source_id": r.source_id, "title": r.title, "year": r.year} for r in rows]


def write_seen_file(db, run_dir, field_id, max_new):
    return write_seen(run_dir / SEEN_FILE, seen_records(db, field_id), max_new)


# --- runs ----------------------------------------------------------------------------------------------------------


def create_alert_run(
    db, settings, alert, *, user_id, mode="live", idempotency_key=None, now=None, deferred=False
):
    """Queue one alert run of the field's current version. Returns (job, run, created). Raises AlertError."""
    from .api.errors import ApiError
    from .api.routers.runs import _current_requests

    field = db.get(Field, alert.field_id)
    if field is None or field.archived_at is not None:
        raise AlertError("The field is archived; restore it to run its alert", 409, "archived")
    try:
        version, domain, review, settings_id, reviewer_ids = _current_requests(db, field)
    except ApiError as exc:
        raise AlertError(exc.message, exc.status, exc.code) from None
    if domain is None:
        raise AlertError("Alerts need a field with criteria and sources (a field version)")
    now = now or datetime.now().astimezone()
    domain = {
        **domain,
        "years": alert_years(domain.get("years") or {}, alert.years_back, now.astimezone().year),
    }
    contract = {"topic": domain["topic"], "max_papers": settings.max_papers_cap, "mode": mode}
    manifest = {"contract": contract, "domain_request": domain}
    if review:
        manifest["review_request"] = review
    run = Run(
        field_id=field.id,
        field_version_id=version.id if version else None,
        settings_version_id=settings_id,
        kind="research",
        status="queued",
        trigger="alert",
        manifest=manifest,
        created_by=user_id,
        created_at=now,
    )
    db.add(run)
    db.flush()
    for position, reviewer_version_id in enumerate(reviewer_ids):
        db.add(RunReviewer(run_id=run.id, position=position, reviewer_version_id=reviewer_version_id))
    run.folder = str(settings.runs_dir / run.id.hex)
    payload = {
        "run_id": str(run.id),
        "field_id": str(field.id),
        "alert_id": str(alert.id),
        "max_new": alert.max_new,
        **contract,
        "resume": False,
        "domain": domain,
    }
    if deferred:
        payload["deferred"] = True
    if review:
        payload["review"] = review
    job, created = enqueue(db, "research", payload, user_id, idempotency_key)
    if not created:
        db.delete(run)
        db.flush()
        return job, db.get(Run, uuid.UUID(job.payload["run_id"])), False
    alert.last_run_id = run.id
    db.flush()
    return job, run, True


def schedule_due(db, settings, now):
    """One scheduler pass (worker tick): every enabled alert whose slot has come, locked with SKIP LOCKED,
    gets one research job (idempotency key alert:<id>:<slot>) and its next slot. A missed slot runs once; the
    daily budget defers the rest to the next day. Returns the alert ids that got a run. Caller commits."""
    due = db.scalars(
        select(Alert)
        .where(Alert.enabled.is_(True), Alert.next_run_at <= now)
        .order_by(Alert.deferred_at.is_(None), Alert.next_run_at, Alert.id)  # deferred ones first
        .with_for_update(skip_locked=True)
        .execution_options(populate_existing=True)
    ).all()
    if not due:
        return []
    budget = settings_row(db).alerts_max_runs_per_day
    used = runs_today(db, now)
    started = []
    for alert in due:
        slot = alert.next_run_at
        if used >= budget:
            tomorrow = local_day_start(now).replace(tzinfo=None) + timedelta(days=1)
            alert.next_run_at = tomorrow.replace(hour=alert.hour).astimezone()
            alert.deferred_at = alert.deferred_at or now
            continue
        key = f"alert:{alert.id}:{slot.astimezone(UTC).isoformat()}"  # one spelling per slot
        try:
            with db.begin_nested():
                _job, _run, created = create_alert_run(
                    db,
                    settings,
                    alert,
                    user_id=alert.created_by,
                    idempotency_key=key,
                    now=now,
                    deferred=alert.deferred_at is not None,
                )
        except AlertError as exc:
            record_failure(db, alert, None, exc.message)
            created = False
        if created:
            used += 1
            alert.deferred_at = None
            started.append(alert.id)
        alert.next_run_at = next_run_of(alert, now)  # from now, not the old slot: no backlog
    db.flush()
    return started


# --- digests -------------------------------------------------------------------------------------------------------


def one_sentence(text):
    text = " ".join((text or "").split())
    match = re.match(r"(.+?[.!?])(\s|$)", text)
    text = match.group(1) if match else text
    return text if len(text) <= MAX_WHY else text[: MAX_WHY - 1] + "…"


def digest_items(db, run, min_group):
    """[{paper_id, group, why, title, year}] of the run's papers at or above `min_group` (papers.QUALITY_GROUPS
    rules, via papers.quality_expr)."""
    from .papers import PaperQuery, _filtered

    stmt, _quality = _filtered(run, PaperQuery())
    wanted = MIN_GROUPS[min_group]
    items = []
    for row in db.execute(stmt).all():
        screening, paper, quality = row[0], row[1], row[-1]
        if quality not in wanted:
            continue
        review = db.scalar(
            select(PaperReview).where(PaperReview.run_id == run.id, PaperReview.paper_id == paper.id)
        )
        why = (review.editor_reason if review else "") or screening.reason
        items.append(
            {
                "paper_id": str(paper.id),
                "group": quality,
                "why": one_sentence(why),
                "title": paper.title,
                "year": paper.year,
                "score": review.score if review else None,
            }
        )
    items.sort(key=lambda i: (GROUP_ORDER[i["group"]], -(i["score"] or 0), i["title"].casefold()))
    return [{k: v for k, v in item.items() if k != "score"} for item in items]


def record_failure(db, alert, run_id, reason):
    """A failed digest (silence never means "nothing new"); 3 failures in a row pause the alert."""
    digest = Digest(alert_id=alert.id, run_id=run_id, status="failed", reason=reason, counts={}, items=[])
    db.add(digest)
    alert.failures = (alert.failures or 0) + 1
    if alert.failures >= MAX_FAILURES:
        alert.enabled = False
        alert.paused_reason = f"Paused after {MAX_FAILURES} failed runs in a row. Last error: {reason}"
    db.flush()
    return digest


def finish_alert_run(db, run, payload, skip_counts=None):
    """Called by the worker when an alert run ends (done or failed). Idempotent per run. Caller commits."""
    alert_id = (payload or {}).get("alert_id")
    alert = db.get(Alert, uuid.UUID(alert_id)) if alert_id else None
    if alert is None or db.scalar(select(Digest.id).where(Digest.run_id == run.id)) is not None:
        return None
    if run.status != "done":
        return record_failure(db, alert, run.id, run.error or "The run did not finish")
    items = digest_items(db, run, alert.min_group)
    reviewed = db.scalar(select(func.count()).select_from(PaperReview).where(PaperReview.run_id == run.id))
    skip = skip_counts or {}
    counts = {
        "found": skip.get("found"),
        "already_seen": skip.get("already_seen"),
        "new": skip.get("new"),
        "over_cap": skip.get("over_cap", 0),
        "reviewed": reviewed,
        "in_digest": len(items),
    }
    if payload.get("deferred"):
        counts["deferred"] = True
    digest = Digest(alert_id=alert.id, run_id=run.id, status="done", counts=counts, items=items)
    db.add(digest)
    alert.failures = 0
    db.flush()
    return digest


def subscribe(db, alert_id, user_id):
    if db.get(AlertSubscription, (alert_id, user_id)) is None:
        db.add(AlertSubscription(alert_id=alert_id, user_id=user_id))
        db.flush()
