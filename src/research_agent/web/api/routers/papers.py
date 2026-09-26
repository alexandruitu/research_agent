import uuid
from typing import Literal

from fastapi import APIRouter, Depends, Query

from ...db.models import Run
from ...papers import PaperQuery, paper_table
from ..deps import get_db, get_settings, require_role
from ..errors import ApiError
from ..schemas import PaperPage

router = APIRouter(prefix="/runs", tags=["papers"])


@router.get("/{run_id}/papers", response_model=PaperPage)
def list_papers(
    run_id: uuid.UUID,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1),
    sort: str = Query("title", pattern=r"^(title|year|score|criterion:[a-z0-9_]+)$"),
    direction: Literal["asc", "desc"] = "asc",
    decision: Literal["include", "exclude", "uncertain"] | None = None,
    tier: Literal["jev", "llm", "rule"] | None = None,
    escalated: bool | None = None,
    in_sr: bool | None = None,
    criterion: str | None = Query(None, pattern=r"^[a-z0-9_]+$"),
    p_min: float | None = Query(None, ge=0, le=1),
    p_max: float | None = Query(None, ge=0, le=1),
    user=Depends(require_role("viewer")),
    db=Depends(get_db),
    settings=Depends(get_settings),
):
    if page_size > settings.max_page_size:
        raise ApiError(422, "validation_error", f"page_size must be at most {settings.max_page_size}")
    run = db.get(Run, run_id)
    if run is None:
        raise ApiError(404, "not_found", "No such run")
    query = PaperQuery(
        page, page_size, sort, direction, decision, tier, escalated, in_sr, criterion, p_min, p_max
    )
    items, total = paper_table(db, run, query)
    return PaperPage(items=items, total=total, page=page, page_size=page_size)
