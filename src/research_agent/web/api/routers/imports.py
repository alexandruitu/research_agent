from fastapi import APIRouter, Depends

from ...jobs import enqueue
from ..deps import get_db, get_settings, require_role
from ..errors import ApiError
from ..schemas import ImportRequest, JobOut
from .runs import job_out

router = APIRouter(prefix="/imports", tags=["imports"])


@router.post("", response_model=JobOut, status_code=202)
def request_import(
    body: ImportRequest,
    user=Depends(require_role("admin")),
    db=Depends(get_db),
    settings=Depends(get_settings),
):
    root = (settings.runs_dir if body.kind == "research" else settings.evals_dir).resolve()
    # The name is regex-validated (no separators, no leading dot); resolving also refuses a symlink
    # that points outside the root. The worker repeats this check before it reads anything.
    folder = (root / body.name).resolve()
    if not folder.is_relative_to(root) or not folder.is_dir():
        raise ApiError(404, "not_found", f"No {body.kind} folder named {body.name}")
    job, _ = enqueue(db, "import", {"kind": body.kind, "name": body.name}, user.id)
    db.commit()
    return job_out(job)
