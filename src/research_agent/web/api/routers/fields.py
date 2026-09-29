import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select

from ... import fields as svc
from ...db.models import Field, FieldVersion, Run, User
from ..deps import get_db, require_role
from ..errors import ApiError
from ..schemas import (
    CriterionOut,
    CriterionText,
    FieldCreate,
    FieldOut,
    FieldRunRef,
    FieldSave,
    FieldVersionOut,
    FieldVersionSummary,
    Years,
)

router = APIRouter(prefix="/fields", tags=["fields"])


def _author(db, user_id):
    user = db.get(User, user_id) if user_id else None
    return user.name if user else None


def _run_count(db, version):
    return db.scalar(select(func.count()).select_from(Run).where(Run.field_version_id == version.id))


def version_out(db, version):
    grouped = svc.criteria_of(db, version)
    stored = version.sources or {}
    years = stored.get("years") or svc.NO_YEARS

    def texts(kind):
        return [CriterionText(key=c.key, text=c.question) for c in grouped[kind]]

    return FieldVersionOut(
        version=version.version,
        name=version.name,
        topic=version.topic,
        include=texts("include"),
        exclude=texts("exclude"),
        legacy=texts("legacy"),
        sources=stored.get("names", []),
        years=Years(start=years.get("from"), end=years.get("to")),
        note=version.note,
        imported=version.note == "imported",
        created_by_name=_author(db, version.created_by),
        created_at=version.created_at,
        run_count=_run_count(db, version),
    )


def _last_run(db, field):
    run = db.scalar(select(Run).where(Run.field_id == field.id).order_by(Run.created_at.desc()).limit(1))
    if run is None:
        return None
    version = db.get(FieldVersion, run.field_version_id) if run.field_version_id else None
    return FieldRunRef(
        id=run.id,
        kind=run.kind,
        status=run.status,
        created_at=run.created_at,
        field_version=version.version if version else None,
    )


def field_out(db, field, detail=False):
    version = svc.get_version(db, field)
    criteria = []
    if version is not None:
        grouped = svc.criteria_of(db, version)
        criteria = [
            CriterionOut.model_validate(c) for kind in svc.KINDS for c in grouped[kind]
        ]  # include, exclude, then legacy; each in saved order
    versions = []
    if detail:
        for v in db.scalars(
            select(FieldVersion)
            .where(FieldVersion.field_id == field.id)
            .order_by(FieldVersion.version.desc())
        ):
            grouped = svc.criteria_of(db, v)
            versions.append(
                FieldVersionSummary(
                    version=v.version,
                    note=v.note,
                    imported=v.note == "imported",
                    created_by_name=_author(db, v.created_by),
                    created_at=v.created_at,
                    run_count=_run_count(db, v),
                    include_count=len(grouped["include"]),
                    exclude_count=len(grouped["exclude"]),
                )
            )
    return FieldOut(
        id=field.id,
        name=field.name,
        topic=field.topic,
        criteria=criteria,
        current_version=field.current_version,
        archived_at=field.archived_at,
        current=version_out(db, version) if version is not None else None,
        last_run=_last_run(db, field),
        versions=versions,
    )


def load_field(db, field_id):
    field = db.get(Field, field_id)
    if field is None:
        raise ApiError(404, "not_found", "No such field")
    return field


def conflict(exc):
    return ApiError(exc.status, exc.code, exc.message)


@router.get("", response_model=list[FieldOut])
def list_fields(
    archived: bool = Query(False, description="true: also list archived fields"),
    user=Depends(require_role("viewer")),
    db=Depends(get_db),
):
    stmt = select(Field).order_by(Field.name, Field.id)
    if not archived:
        stmt = stmt.where(Field.archived_at.is_(None))
    return [field_out(db, f) for f in db.scalars(stmt)]


@router.get("/{field_id}", response_model=FieldOut)
def get_field(field_id: uuid.UUID, user=Depends(require_role("viewer")), db=Depends(get_db)):
    return field_out(db, load_field(db, field_id), detail=True)


@router.get("/{field_id}/versions/{number}", response_model=FieldVersionOut)
def get_field_version(
    field_id: uuid.UUID, number: int, user=Depends(require_role("viewer")), db=Depends(get_db)
):
    version = svc.get_version(db, load_field(db, field_id), number) if number >= 1 else None
    if version is None:
        raise ApiError(404, "not_found", "No such version")
    return version_out(db, version)


@router.post("", response_model=FieldOut, status_code=201)
def create_field(body: FieldCreate, user=Depends(require_role("member")), db=Depends(get_db)):
    field = svc.create_field(db, body, user.id)
    db.commit()
    return field_out(db, field, detail=True)


@router.post("/{field_id}/versions", response_model=FieldOut, status_code=201)
def save_version(
    field_id: uuid.UUID, body: FieldSave, user=Depends(require_role("member")), db=Depends(get_db)
):
    field = load_field(db, field_id)
    try:
        svc.save_version(db, field, body, body.base_version, user.id)
    except svc.FieldConflict as exc:
        db.rollback()
        raise conflict(exc) from None
    db.commit()
    return field_out(db, field, detail=True)


@router.post("/{field_id}/archive", response_model=FieldOut)
def archive_field(field_id: uuid.UUID, user=Depends(require_role("admin")), db=Depends(get_db)):
    field = svc.set_archived(db, load_field(db, field_id), True)
    db.commit()
    return field_out(db, field, detail=True)


@router.post("/{field_id}/unarchive", response_model=FieldOut)
def unarchive_field(field_id: uuid.UUID, user=Depends(require_role("admin")), db=Depends(get_db)):
    field = svc.set_archived(db, load_field(db, field_id), False)
    db.commit()
    return field_out(db, field, detail=True)
