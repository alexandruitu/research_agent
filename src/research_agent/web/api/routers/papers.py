import uuid
from typing import Literal

from fastapi import APIRouter, Depends, Query

from ...callstore import HEX64, CallStoreError, read_call, safe_folder
from ...db.models import Paper, Run
from ...library import library_refs
from ...papers import PaperQuery, paper_drawer, paper_groups, paper_table
from ..deps import get_db, get_settings, require_role
from ..errors import ApiError
from ..schemas import CallOut, DrawerOut, PaperGroupOut, PaperPage, SourceName
from .files import files_of

router = APIRouter(prefix="/runs", tags=["papers"])
GroupBy = Literal["quality", "source", "year", "decided_by", "library"]
MAX_PAGE = 100_000  # keeps (page - 1) * page_size far inside a SQL bigint offset


def paper_filters(
    run_id: uuid.UUID,
    page: int = Query(1, ge=1, le=MAX_PAGE),
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
    decided_by: str | None = Query(None, pattern=r"^[a-z0-9_]+$", max_length=100),
    source: SourceName | Literal["demo"] | None = None,
    has_red_flags: bool | None = None,
    provisional: bool | None = None,
    group_by: GroupBy = "quality",
    group: str | None = Query(None, pattern=r"^[a-z0-9_]+$", max_length=100),
    user=Depends(require_role("viewer")),
    db=Depends(get_db),
    settings=Depends(get_settings),
):
    """The run and its validated paper filters (shared by the table and its groups)."""
    if page_size > settings.max_page_size:
        raise ApiError(422, "validation_error", f"page_size must be at most {settings.max_page_size}")
    if (p_min is not None or p_max is not None) and criterion is None:
        raise ApiError(422, "validation_error", "p_min and p_max need a criterion")
    if p_min is not None and p_max is not None and p_min > p_max:
        raise ApiError(422, "validation_error", "p_min must not exceed p_max")
    run = db.get(Run, run_id)
    if run is None:
        raise ApiError(404, "not_found", "No such run")
    if in_sr is not None and run.gold_set_id is None:
        raise ApiError(422, "validation_error", "in_sr needs a run with a gold set (an eval run)")
    query = PaperQuery(
        page,
        page_size,
        sort,
        direction,
        decision,
        tier,
        escalated,
        in_sr,
        criterion,
        p_min,
        p_max,
        decided_by,
        source,
        has_red_flags,
        group_by,
        group,
        provisional,
    )
    return run, query


@router.get("/{run_id}/papers", response_model=PaperPage)
def list_papers(filters=Depends(paper_filters), db=Depends(get_db)):
    run, query = filters
    items, total = paper_table(db, run, query)
    return PaperPage(items=items, total=total, page=query.page, page_size=query.page_size)


@router.get("/{run_id}/papers/groups", response_model=list[PaperGroupOut])
def list_paper_groups(by: GroupBy = "quality", filters=Depends(paper_filters), db=Depends(get_db)):
    """The groups of a run's papers under the active filters: key, label, count and the rule that forms them."""
    run, query = filters
    return paper_groups(db, run, query, by)


@router.get("/{run_id}/papers/{paper_id}", response_model=DrawerOut)
def get_paper(
    run_id: uuid.UUID, paper_id: uuid.UUID, user=Depends(require_role("viewer")), db=Depends(get_db)
):
    run, paper = db.get(Run, run_id), db.get(Paper, paper_id)
    if run is None or paper is None:
        raise ApiError(404, "not_found", "No such run or paper")
    drawer = paper_drawer(db, run, paper)
    if drawer is None:
        raise ApiError(404, "not_found", "This paper is not part of the run")
    return drawer | {
        "files": files_of(db, user, paper.id),
        "library": library_refs(db, [paper.id]).get(paper.id),
    }


@router.get("/{run_id}/calls/{call_key}", response_model=CallOut)
def get_call(
    run_id: uuid.UUID,
    call_key: str,
    user=Depends(require_role("member")),
    db=Depends(get_db),
    settings=Depends(get_settings),
):
    run = db.get(Run, run_id)
    if run is None:
        raise ApiError(404, "not_found", "No such run")
    if not HEX64.fullmatch(call_key):
        raise ApiError(422, "invalid_call_key", "call key must be 64 lowercase hex characters")
    roots = [settings.runs_dir, settings.evals_dir]
    try:
        if not run.folder:  # "" would resolve to the server's working directory
            raise CallStoreError("run has no folder")
        folder = safe_folder(run.folder, roots)
        # The store itself must not be a symlink out of the roots.
        safe_folder(folder / "research.sqlite", roots)
        return read_call(folder, call_key)
    except CallStoreError as exc:
        if str(exc) == "call not found":  # exact: other messages carry the folder path
            raise ApiError(404, "call_not_found", "No such call in this run's audit trail") from None
        raise ApiError(409, "no_audit_trail", "This run's audit trail is not available") from None
