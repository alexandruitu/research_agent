import uuid

from fastapi import APIRouter, Depends

from ...db.models import Job
from ..deps import get_db, require_role
from ..errors import ApiError
from ..schemas import JobOut
from .runs import job_out

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.get("/{job_id}", response_model=JobOut)
def get_job(job_id: uuid.UUID, user=Depends(require_role("member")), db=Depends(get_db)):
    job = db.get(Job, job_id)
    if job is None or (job.created_by != user.id and user.role != "admin"):
        raise ApiError(404, "not_found", "No such job")  # other people's jobs look exactly like missing ones
    return job_out(job)
