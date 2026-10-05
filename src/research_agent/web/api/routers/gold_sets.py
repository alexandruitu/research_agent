"""Gold sets: the frozen SR reference sets evaluations run on; new ones are built by a worker job."""

from fastapi import APIRouter, Depends, Header, Response
from sqlalchemy import select

from ... import evals as svc
from ...db.models import GoldSet, Job
from ...jobs import enqueue
from ..deps import get_db, get_settings, require_role
from ..errors import ApiError
from ..schemas import GoldSetOut, GoldSetRequest, JobOut
from .runs import check_active_cap, job_out

router = APIRouter(prefix="/gold-sets", tags=["evals"])


@router.get("", response_model=list[GoldSetOut])
def list_gold_sets(user=Depends(require_role("viewer")), db=Depends(get_db), settings=Depends(get_settings)):
    rows = db.scalars(select(GoldSet).order_by(GoldSet.created_at.desc()))
    return [GoldSetOut(**svc.gold_set_out(settings, row)) for row in rows]


@router.post("", response_model=JobOut, status_code=202)
def build_gold_set(
    body: GoldSetRequest,
    response: Response,
    idempotency_key: str | None = Header(None, max_length=100),
    user=Depends(require_role("member")),
    db=Depends(get_db),
    settings=Depends(get_settings),
):
    """Job `gold_build`: resolves the included studies on Europe PMC (public API, no key) and freezes the
    gold file; its result names the new gold set."""
    if idempotency_key:
        existing = db.scalar(
            select(Job).where(Job.created_by == user.id, Job.idempotency_key == idempotency_key)
        )
        if existing is not None:
            response.status_code = 200
            return job_out(existing)
    taken = db.scalar(select(GoldSet).where(GoldSet.name == body.name)) is not None
    if taken or (settings.gold_dir / f"{body.name}.json").exists():
        raise ApiError(409, "name_taken", f"A gold set named '{body.name}' already exists")
    check_active_cap(db, user, settings)
    payload = {
        "spec": svc.gold_spec(body),
        "max_candidates": body.max_candidates,
        "sr_reference": body.sr_reference,
    }
    job, _created = enqueue(db, "gold_build", payload, user.id, idempotency_key)
    db.commit()
    return job_out(job)
