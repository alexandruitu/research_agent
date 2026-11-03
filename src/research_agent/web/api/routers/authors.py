"""Authors: the typeahead over stored authors, one author, and the OpenAlex backfill (Settings → Sources)."""

import uuid
from typing import Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select

from ... import authors as svc
from ...db.models import Job, Run
from ...jobs import enqueue
from ..deps import get_db, get_settings, require_role
from ..errors import ApiError
from ..schemas import AuthorLookupRequest, AuthorSuggestionOut, BackfillStatusOut, JobOut
from .runs import check_active_cap, job_out

router = APIRouter(prefix="/authors", tags=["authors"])
BACKFILL = "authors_backfill"


@router.get("", response_model=list[AuthorSuggestionOut])
def suggest_authors(
    q: str = Query(..., min_length=1, max_length=200, description="words of the author's name"),
    run_id: uuid.UUID | None = Query(None, description="count (and list) only papers of this run"),
    library: bool = Query(False, description="count (and list) only papers in your libraries"),
    scope: Literal["personal", "company"] | None = Query(
        None, description="with library: only this library (company, or personal: your own)"
    ),
    limit: int = Query(10, ge=1, le=50),
    user=Depends(require_role("viewer")),
    db=Depends(get_db),
):
    """Stored authors whose name contains every typed word: identified ones first, then by paper count."""
    if run_id is not None and db.get(Run, run_id) is None:
        raise ApiError(404, "not_found", "No such run")
    return svc.suggest(db, q, run_id=run_id, library=library, limit=limit, viewer=user, scope=scope)


@router.get("/backfill", response_model=BackfillStatusOut)
def backfill_status(user=Depends(require_role("admin")), db=Depends(get_db)):
    """How many papers still lack authors (with a DOI), and the latest backfill job with its summary."""
    job = db.scalar(select(Job).where(Job.kind == BACKFILL).order_by(Job.created_at.desc()).limit(1))
    return {"candidates": len(svc.backfill_candidates(db)), "job": job_out(job) if job else None}


@router.post("/backfill", response_model=JobOut, status_code=202)
def start_backfill(user=Depends(require_role("admin")), db=Depends(get_db), settings=Depends(get_settings)):
    """Queue the backfill (one at a time: an active one is returned instead of a second)."""
    active = db.scalar(
        select(Job)
        .where(Job.kind == BACKFILL, Job.status.in_(("queued", "running")))
        .order_by(Job.created_at.desc())
        .limit(1)
    )
    if active is not None:
        return job_out(active)
    check_active_cap(db, user, settings)
    job, _ = enqueue(db, BACKFILL, {}, user.id)
    db.commit()
    return job_out(job)


@router.post("/lookup", response_model=JobOut, status_code=202)
def author_lookup(
    body: AuthorLookupRequest,
    user=Depends(require_role("member")),
    db=Depends(get_db),
    settings=Depends(get_settings),
):
    """Queue an `author_lookup` job (topic editor, Researcher tab): OpenAlex candidates for a name, or the
    co-authors (with shared works) and institutions of the picked people. Payload keys never include run_id."""
    if body.mode == "demo" and not settings.allow_demo:
        raise ApiError(422, "validation_error", "demo mode is disabled on this deployment")
    check_active_cap(db, user, settings)
    payload = {"step": body.step, "mode": body.mode}
    if body.step == "search":
        payload["name"] = " ".join(body.name.split())
    else:
        payload["people"] = [p.model_dump() for p in body.people]
    job, _ = enqueue(db, "author_lookup", payload, user.id)
    db.commit()
    return job_out(job)


@router.get("/{author_id}", response_model=AuthorSuggestionOut)
def get_author(author_id: uuid.UUID, user=Depends(require_role("viewer")), db=Depends(get_db)):
    found = svc.author_detail(db, author_id)
    if found is None:
        raise ApiError(404, "not_found", "No such author")
    return found
