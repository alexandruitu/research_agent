import uuid

from fastapi import APIRouter, Depends
from sqlalchemy import select

from ...db.models import Criterion, Field
from ..deps import get_db, require_role
from ..errors import ApiError
from ..schemas import CriterionOut, FieldOut

router = APIRouter(prefix="/fields", tags=["fields"])


def field_out(db, field):
    latest = {}
    rows = db.scalars(
        select(Criterion)
        .where(Criterion.field_id == field.id)
        .order_by(Criterion.position, Criterion.version.desc())
    )
    for row in rows:
        latest.setdefault(row.key, row)  # newest version of each key
    return FieldOut(
        id=field.id,
        name=field.name,
        topic=field.topic,
        criteria=[CriterionOut.model_validate(c) for c in sorted(latest.values(), key=lambda c: c.position)],
    )


@router.get("", response_model=list[FieldOut])
def list_fields(user=Depends(require_role("viewer")), db=Depends(get_db)):
    return [field_out(db, f) for f in db.scalars(select(Field).order_by(Field.name))]


@router.get("/{field_id}", response_model=FieldOut)
def get_field(field_id: uuid.UUID, user=Depends(require_role("viewer")), db=Depends(get_db)):
    field = db.get(Field, field_id)
    if field is None:
        raise ApiError(404, "not_found", "No such field")
    return field_out(db, field)
