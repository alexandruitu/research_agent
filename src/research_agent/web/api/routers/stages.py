from fastapi import APIRouter, Depends
from sqlalchemy import select

from ...db.models import EvalReport
from ...stages import evaluate_stages, load_catalog, merge_metrics
from ..deps import get_db, get_settings, require_role
from ..schemas import StageOut

router = APIRouter(prefix="/stages", tags=["stages"])


@router.get("", response_model=list[StageOut])
def list_stages(user=Depends(require_role("viewer")), db=Depends(get_db), settings=Depends(get_settings)):
    reports = [r.metrics for r in db.scalars(select(EvalReport).order_by(EvalReport.created_at.desc()))]
    return evaluate_stages(load_catalog(settings.stages_path), merge_metrics(reports))
