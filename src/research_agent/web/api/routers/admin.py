"""Settings: sources (enable, limits, connection check), the contact email, and the worker's key status."""

from fastapi import APIRouter, Depends
from sqlalchemy import select

from ...db.models import SourceRow, WorkerStatus
from ...fields import SOURCE_NAMES, settings_row
from ..deps import get_db, require_role
from ..errors import ApiError
from ..schemas import SettingsOut, SettingsPatch, SourceOut, SourcePatch, WorkerStatusOut

router = APIRouter(tags=["settings"])
LABELS = {"europepmc": "Europe PMC", "openalex": "OpenAlex", "arxiv": "arXiv"}


def source_out(row):
    return SourceOut(
        name=row.name,
        label=LABELS.get(row.name, row.name),
        enabled=row.enabled,
        max_results=row.max_results,
        last_check_at=row.last_check_at,
        last_check_ok=row.last_check_ok,
        last_check_ms=row.last_check_ms,
        last_check_error=row.last_check_error,
    )


def load_source(db, name):
    row = db.get(SourceRow, name) if name in SOURCE_NAMES else None
    if row is None:
        raise ApiError(404, "not_found", "No such source")
    return row


@router.get("/sources", response_model=list[SourceOut])
def list_sources(user=Depends(require_role("viewer")), db=Depends(get_db)):
    rows = {row.name: row for row in db.scalars(select(SourceRow))}
    return [source_out(rows[name]) for name in SOURCE_NAMES if name in rows]


@router.patch("/sources/{name}", response_model=SourceOut)
def patch_source(name: str, body: SourcePatch, user=Depends(require_role("admin")), db=Depends(get_db)):
    row = load_source(db, name)
    if body.enabled is not None:
        row.enabled = body.enabled
    if body.max_results is not None:
        row.max_results = body.max_results
    db.commit()
    return source_out(row)


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
