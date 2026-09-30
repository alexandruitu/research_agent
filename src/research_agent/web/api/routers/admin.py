"""Settings: sources (enable, limits, connection check), the contact email, and the worker's key status."""

from fastapi import APIRouter, Depends
from sqlalchemy import select

from ....sources import REGISTRY
from ...db.models import SourceRow, WorkerStatus
from ...fields import settings_row
from ...jobs import enqueue
from ..deps import get_db, get_settings, require_role
from ..errors import ApiError
from ..schemas import JobOut, SettingsOut, SettingsPatch, SourceOut, SourcePatch, WorkerStatusOut
from .runs import check_active_cap, job_out

router = APIRouter(tags=["settings"])


def missing_key(info, row):
    """The first required variable the worker did not report present; None when nothing is missing."""
    if info.auth != "required" or row.key_present:
        return None
    return info.env[0]


def source_out(row):
    info = REGISTRY[row.name]
    return SourceOut(
        name=row.name,
        label=info.label,
        group=info.group,
        covers=info.covers,
        auth=info.auth,
        env=list(info.env),
        capabilities=list(info.capabilities),
        rps=info.rps,
        rps_keyed=info.rps_keyed,
        rps_in_use=info.rps_keyed if row.key_present and info.auth != "none" else info.rps,
        key_present=row.key_present,
        key_accepted=row.key_accepted,
        key_detail=row.key_detail or "",
        key_checked_at=row.key_checked_at,
        enabled=row.enabled,
        max_results=row.max_results,
        last_check_at=row.last_check_at,
        last_check_ok=row.last_check_ok,
        last_check_ms=row.last_check_ms,
        last_check_error=row.last_check_error,
    )


def load_source(db, name):
    row = db.get(SourceRow, name) if name in REGISTRY else None
    if row is None:
        raise ApiError(404, "not_found", "No such source")
    return row


@router.get("/sources", response_model=list[SourceOut])
def list_sources(user=Depends(require_role("viewer")), db=Depends(get_db)):
    rows = {row.name: row for row in db.scalars(select(SourceRow))}
    return [source_out(rows[name]) for name in REGISTRY if name in rows]


@router.patch("/sources/{name}", response_model=SourceOut)
def patch_source(name: str, body: SourcePatch, user=Depends(require_role("admin")), db=Depends(get_db)):
    row = load_source(db, name)
    if body.enabled and not row.enabled:
        variable = missing_key(REGISTRY[name], row)
        if variable:
            raise ApiError(422, "key_missing", f"Set {variable} in the worker environment first")
    if body.enabled is not None:
        row.enabled = body.enabled
    if body.max_results is not None:
        row.max_results = body.max_results
    db.commit()
    return source_out(row)


@router.post("/sources/{name}/check", response_model=JobOut, status_code=202)
def check_source(
    name: str, user=Depends(require_role("admin")), db=Depends(get_db), settings=Depends(get_settings)
):
    """Queue a connection check (the worker searches for one result and records the outcome)."""
    load_source(db, name)
    if "search" not in REGISTRY[name].capabilities:
        raise ApiError(422, "not_searchable", "This source only provides full text; it has no search to test")
    check_active_cap(db, user, settings)
    job, _ = enqueue(db, "source_check", {"name": name}, user.id)
    db.commit()
    return job_out(job)


@router.get("/settings", response_model=SettingsOut)
def get_settings_row(user=Depends(require_role("viewer")), db=Depends(get_db)):
    return SettingsOut(contact_email=settings_row(db).contact_email)


@router.patch("/settings", response_model=SettingsOut)
def patch_settings(body: SettingsPatch, user=Depends(require_role("admin")), db=Depends(get_db)):
    row = settings_row(db)
    if "contact_email" in body.model_fields_set:  # an explicit null clears it; an absent key keeps it
        row.contact_email = body.contact_email
    db.commit()
    return SettingsOut(contact_email=row.contact_email)


@router.get("/workers/status", response_model=list[WorkerStatusOut])
def worker_status(user=Depends(require_role("viewer")), db=Depends(get_db)):
    return [
        WorkerStatusOut.model_validate(row)
        for row in db.scalars(select(WorkerStatus).order_by(WorkerStatus.role))
    ]
