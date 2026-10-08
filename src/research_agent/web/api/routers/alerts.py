"""Field alerts: the alert of a field, run now, following, and the digests inbox."""

import time
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, Header, Query, Response
from sqlalchemy import and_, func, select

from ... import alerts as svc
from ...db.models import Alert, AlertSubscription, Digest, DigestRead, Field, Run
from ..deps import get_db, get_settings, require_role
from ..errors import ApiError
from ..schemas import (
    AlertIn,
    AlertOut,
    AlertRunIn,
    DigestListOut,
    DigestOut,
    StartRunOut,
    SubscriptionOut,
)
from .runs import _existing, check_active_cap, job_out

router = APIRouter(tags=["alerts"])

DEFAULTS = AlertIn()


def _field(db, field_id):
    field = db.get(Field, field_id)
    if field is None:
        raise ApiError(404, "not_found", "No such field")
    return field


def _alert(db, alert_id):
    alert = db.get(Alert, alert_id)
    if alert is None:
        raise ApiError(404, "not_found", "No such alert")
    return alert


def _can_edit(user, alert):
    return user.role == "admin" or alert is None or alert.created_by == user.id


def alert_out(db, settings, user, field, alert):
    values = alert if alert is not None else DEFAULTS
    last = db.get(Run, alert.last_run_id) if alert and alert.last_run_id else None
    subscribers = (
        db.scalar(
            select(func.count()).select_from(AlertSubscription).where(AlertSubscription.alert_id == alert.id)
        )
        if alert
        else 0
    )
    subscribed = bool(alert) and db.get(AlertSubscription, (alert.id, user.id)) is not None
    return AlertOut(
        exists=alert is not None,
        id=alert.id if alert else None,
        field_id=field.id,
        enabled=values.enabled if alert else False,
        cadence=values.cadence,
        weekday=values.weekday,
        hour=values.hour,
        timezone=time.strftime("%Z") or "local",
        max_new=values.max_new,
        effective_max_new=min(values.max_new, settings.max_papers_cap),
        min_group=values.min_group,
        years_back=values.years_back,
        next_run_at=alert.next_run_at if alert else None,
        last_run_id=last.id if last else None,
        last_run_status=last.status if last else None,
        failures=alert.failures if alert else 0,
        paused_reason=alert.paused_reason if alert else None,
        deferred_at=alert.deferred_at if alert else None,
        subscribed=subscribed,
        subscriber_count=subscribers or 0,
        created_by=alert.created_by if alert else None,
        can_edit=_can_edit(user, alert) and user.role in ("member", "admin"),
    )


def _field_alert(db, field_id):
    return db.scalar(select(Alert).where(Alert.field_id == field_id))


@router.get("/fields/{field_id}/alert", response_model=AlertOut)
def get_alert(
    field_id: uuid.UUID,
    user=Depends(require_role("viewer")),
    db=Depends(get_db),
    settings=Depends(get_settings),
):
    field = _field(db, field_id)
    return alert_out(db, settings, user, field, _field_alert(db, field.id))


@router.put("/fields/{field_id}/alert", response_model=AlertOut)
def put_alert(
    field_id: uuid.UUID,
    body: AlertIn,
    user=Depends(require_role("member")),
    db=Depends(get_db),
    settings=Depends(get_settings),
):
    field = _field(db, field_id)
    if field.archived_at is not None:
        raise ApiError(409, "archived", "This field is archived; restore it first")
    alert = _field_alert(db, field.id)
    if not _can_edit(user, alert):
        raise ApiError(403, "forbidden", "Only the alert's creator or an admin can change it")
    if alert is None:
        alert = Alert(field_id=field.id, created_by=user.id, failures=0)
        db.add(alert)
        db.flush()
        svc.subscribe(db, alert.id, user.id)  # the creator follows by default
    schedule = (alert.cadence, alert.weekday, alert.hour)
    was_enabled = bool(alert.enabled) and alert.next_run_at is not None
    for name, value in body.model_dump().items():
        setattr(alert, name, value)
    if not body.enabled:
        alert.next_run_at = None
    elif not was_enabled or schedule != (body.cadence, body.weekday, body.hour):
        alert.next_run_at = svc.next_run_of(alert, datetime.now().astimezone())
        alert.failures, alert.paused_reason = 0, None  # switching it (back) on clears a pause
    db.commit()
    return alert_out(db, settings, user, field, alert)


@router.post("/fields/{field_id}/alert/run-now", response_model=StartRunOut, status_code=202)
def run_now(
    field_id: uuid.UUID,
    response: Response,
    body: AlertRunIn | None = None,
    idempotency_key: str | None = Header(None, max_length=100),
    user=Depends(require_role("member")),
    db=Depends(get_db),
    settings=Depends(get_settings),
):
    field = _field(db, field_id)
    alert = _field_alert(db, field.id)
    if alert is None:
        raise ApiError(404, "not_found", "This field has no alert yet")
    mode = (body or AlertRunIn()).mode
    if mode == "demo" and not settings.allow_demo:
        raise ApiError(422, "validation_error", "demo mode is disabled on this deployment")
    if (existing := _existing(db, user, idempotency_key, response)) is not None:
        return existing
    check_active_cap(db, user, settings)
    try:
        job, run, created = svc.create_alert_run(
            db, settings, alert, user_id=user.id, mode=mode, idempotency_key=idempotency_key
        )
    except svc.AlertError as exc:
        db.rollback()
        raise ApiError(exc.status, exc.code, exc.message) from None
    if not created:
        response.status_code = 200
    db.commit()
    return StartRunOut(job=job_out(job), run_id=run.id)


@router.post("/alerts/{alert_id}/subscription", response_model=SubscriptionOut)
def follow(alert_id: uuid.UUID, user=Depends(require_role("member")), db=Depends(get_db)):
    alert = _alert(db, alert_id)
    svc.subscribe(db, alert.id, user.id)
    db.commit()
    return SubscriptionOut(alert_id=alert.id, subscribed=True)


@router.delete("/alerts/{alert_id}/subscription", response_model=SubscriptionOut)
def unfollow(alert_id: uuid.UUID, user=Depends(require_role("member")), db=Depends(get_db)):
    alert = _alert(db, alert_id)
    row = db.get(AlertSubscription, (alert.id, user.id))
    if row is not None:
        db.delete(row)
    db.commit()
    return SubscriptionOut(alert_id=alert.id, subscribed=False)


def _digest_out(db, digest, read):
    alert = db.get(Alert, digest.alert_id)
    field = db.get(Field, alert.field_id)
    return DigestOut(
        id=digest.id,
        alert_id=digest.alert_id,
        field_id=field.id,
        field_name=field.name,
        run_id=digest.run_id,
        status=digest.status,
        reason=digest.reason,
        counts=digest.counts or {},
        items=digest.items or [],
        created_at=digest.created_at,
        read=read,
    )


def _followed(user):
    return select(AlertSubscription.alert_id).where(AlertSubscription.user_id == user.id)


def _read_rows(user):
    return and_(DigestRead.digest_id == Digest.id, DigestRead.user_id == user.id)


@router.get("/digests", response_model=DigestListOut)
def list_digests(
    unread: bool = False,
    scope: str = Query("following", pattern="^(following|all)$"),
    limit: int = Query(50, ge=1, le=200),
    user=Depends(require_role("viewer")),
    db=Depends(get_db),
):
    """Newest first. `scope=following` (default): digests of the alerts the user follows; `all`: admins only.
    `unread` (the nav badge) always counts the followed alerts' unread digests."""
    if scope == "all" and user.role != "admin":
        raise ApiError(403, "forbidden", "Only admins can see every alert's digests")
    is_read = select(DigestRead.digest_id).where(_read_rows(user)).exists()
    stmt = select(Digest, is_read).order_by(Digest.created_at.desc(), Digest.id.desc())
    if scope == "following":
        stmt = stmt.where(Digest.alert_id.in_(_followed(user)))
    if unread:
        stmt = stmt.where(~is_read)
    rows = db.execute(stmt.limit(limit)).all()
    unread_count = db.scalar(
        select(func.count()).select_from(Digest).where(Digest.alert_id.in_(_followed(user)), ~is_read)
    )
    return DigestListOut(unread=unread_count, digests=[_digest_out(db, d, bool(r)) for d, r in rows])


@router.get("/digests/{digest_id}", response_model=DigestOut)
def get_digest(digest_id: uuid.UUID, user=Depends(require_role("viewer")), db=Depends(get_db)):
    digest = db.get(Digest, digest_id)
    if digest is None:
        raise ApiError(404, "not_found", "No such digest")
    return _digest_out(db, digest, db.get(DigestRead, (digest.id, user.id)) is not None)


@router.post("/digests/{digest_id}/read", response_model=DigestOut)
def mark_read(digest_id: uuid.UUID, user=Depends(require_role("viewer")), db=Depends(get_db)):
    digest = db.get(Digest, digest_id)
    if digest is None:
        raise ApiError(404, "not_found", "No such digest")
    if db.get(DigestRead, (digest.id, user.id)) is None:
        db.add(DigestRead(digest_id=digest.id, user_id=user.id))
    db.commit()
    return _digest_out(db, digest, True)
