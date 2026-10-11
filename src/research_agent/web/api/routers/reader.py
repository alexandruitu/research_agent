"""The Reader: a paper's text with the run's quotes, AI help on it (worker job `reader_ask`) and saved notes."""

import uuid

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select

from ... import reader as svc
from ... import related
from ...db.models import Job, LibraryItem, Paper, ReaderNote, Run, Screening, User
from ...jobs import enqueue
from ...papers import PaperQuery, _filtered
from ..deps import get_db, get_settings, require_role
from ..errors import ApiError
from ..schemas import JobOut, ReaderAskIn, ReaderNoteIn, ReaderNoteOut, ReaderOut, ReaderRelatedIn
from .runs import check_active_cap, job_out

router = APIRouter(tags=["reader"])


def _run_paper(db, run_id, paper_id):
    run, paper = db.get(Run, run_id), db.get(Paper, paper_id)
    if run is None or paper is None:
        raise ApiError(404, "not_found", "No such run or paper")
    if (
        db.scalar(select(Screening.id).where(Screening.run_id == run.id, Screening.paper_id == paper.id))
        is None
    ):
        raise ApiError(404, "not_found", "This paper is not part of the run")
    return run, paper


def _group(db, run, paper):
    stmt, quality = _filtered(run, PaperQuery())
    return db.scalar(stmt.with_only_columns(quality, maintain_column_froms=True).where(Paper.id == paper.id))


@router.get("/runs/{run_id}/papers/{paper_id}/reader", response_model=ReaderOut)
def get_reader(
    run_id: uuid.UUID,
    paper_id: uuid.UUID,
    user=Depends(require_role("viewer")),
    db=Depends(get_db),
    settings=Depends(get_settings),
):
    """The paper's text by sections (full text when we have it, else the abstract) and the run's quotes."""
    run, paper = _run_paper(db, run_id, paper_id)
    text = svc.paper_text(db, settings, run, paper)
    return {
        "paper": paper,
        "run_id": run.id,
        "run_name": run.name,
        "group": _group(db, run, paper),
        "text": {k: text[k] for k in ("kind", "source", "licence", "truncated", "sections")},
        "highlights": svc.highlights(db, run, paper),
        "max_selection": svc.MAX_SELECTION,
    }


@router.post("/runs/{run_id}/papers/{paper_id}/reader/ask", response_model=JobOut, status_code=202)
def ask(
    run_id: uuid.UUID,
    paper_id: uuid.UUID,
    body: ReaderAskIn,
    user=Depends(require_role("member")),
    db=Depends(get_db),
    settings=Depends(get_settings),
):
    """Queue one Reader call. The worker reads the paper's text itself; the answer arrives in the job's
    `progress.result`. Demo runs get deterministic demo answers (no model, no key)."""
    run, paper = _run_paper(db, run_id, paper_id)
    if body.tool == "ask" and not body.question.strip():
        raise ApiError(422, "nothing_to_ask", "Write a question first")
    if body.tool == "background" and not (body.selection.strip() or body.question.strip()):
        raise ApiError(422, "nothing_to_explain", "Select a passage or write the concept to explain")
    check_active_cap(db, user, settings)
    # The run id is under `reader_run_id`, never `run_id`: a failed Reader job must not fail the run.
    payload = {
        "reader_run_id": str(run.id),
        "paper_id": str(paper.id),
        "tool": body.tool,
        "selection": body.selection,
        "question": body.question.strip(),
        "mode": svc.run_mode(run),
    }
    job, _ = enqueue(db, "reader_ask", payload, user.id)
    db.commit()
    return job_out(job)


@router.post("/runs/{run_id}/papers/{paper_id}/reader/related", response_model=JobOut, status_code=202)
def find_related(
    run_id: uuid.UUID,
    paper_id: uuid.UUID,
    body: ReaderRelatedIn,
    request: Request,
    user=Depends(require_role("member")),
    db=Depends(get_db),
    settings=Depends(get_settings),
):
    """Queue Find related / Earlier work for the selection (else the paper's title). The query is built by code
    (key terms, no model) and sent to the enabled sources (at most 10 results each) plus the team library and
    the papers seen in runs. Shares the field preview's budget: at most 10 searches per user per minute."""
    run, paper = _run_paper(db, run_id, paper_id)
    if related.search_keywords(body.selection, paper) is None:
        raise ApiError(
            422, "no_terms", "The selection has no key terms to search for; select a longer passage"
        )
    limiter, key = request.app.state.preview_limiter, f"preview:{user.id}"
    if not limiter.allowed(key):
        raise ApiError(429, "rate_limited", "Too many searches; try again in a minute")
    check_active_cap(db, user, settings)
    limiter.record_failure(key)  # counts every accepted search
    # The run id is under `reader_run_id`, never `run_id`: a failed Reader job must not fail the run.
    payload = {
        "reader_run_id": str(run.id),
        "paper_id": str(paper.id),
        "selection": body.selection,
        "mode": body.mode,
        "search_mode": svc.run_mode(run),
    }
    job, _ = enqueue(db, "reader_related", payload, user.id)
    db.commit()
    return job_out(job)


def _note_out(db, note):
    author = db.get(User, note.created_by) if note.created_by else None
    answer = note.answer or {}
    return {
        "id": note.id,
        "paper_id": note.paper_id,
        "run_id": note.run_id,
        "library_item_id": note.library_item_id,
        "selection": note.selection,
        "tool": note.tool,
        "question": note.question,
        "answer": answer.get("answer", ""),
        "not_in_paper": bool(answer.get("not_in_paper")),
        "general": bool(answer.get("general")),
        "quotes": note.quotes or [],
        "model": note.model,
        "created_by_name": author.name if author else None,
        "created_at": note.created_at,
    }


@router.get("/papers/{paper_id}/notes", response_model=list[ReaderNoteOut])
def list_notes(paper_id: uuid.UUID, user=Depends(require_role("viewer")), db=Depends(get_db)):
    """The team's Reader notes on a paper, newest first (shown in the Reader and the Library item)."""
    if db.get(Paper, paper_id) is None:
        raise ApiError(404, "not_found", "No such paper")
    notes = db.scalars(
        select(ReaderNote)
        .where(ReaderNote.paper_id == paper_id)
        .order_by(ReaderNote.created_at.desc(), ReaderNote.id)
    )
    return [_note_out(db, n) for n in notes]


@router.post("/runs/{run_id}/papers/{paper_id}/notes", response_model=ReaderNoteOut, status_code=201)
def save_note(
    run_id: uuid.UUID,
    paper_id: uuid.UUID,
    body: ReaderNoteIn,
    user=Depends(require_role("member")),
    db=Depends(get_db),
):
    """Save a finished Reader answer of this user as a note on the paper (the answer as the worker checked it)."""
    run, paper = _run_paper(db, run_id, paper_id)
    job = db.get(Job, body.job_id)
    payload = (job.payload or {}) if job else {}
    if (
        job is None
        or job.kind != "reader_ask"
        or job.created_by != user.id
        or payload.get("paper_id") != str(paper.id)
        or payload.get("reader_run_id") != str(run.id)
    ):
        raise ApiError(404, "not_found", "No such Reader answer")
    result = (job.progress or {}).get("result")
    if job.status != "done" or not result:
        raise ApiError(409, "not_ready", "This answer is not finished")
    item = db.scalar(select(LibraryItem).where(LibraryItem.paper_id == paper.id))
    note = ReaderNote(
        paper_id=paper.id,
        run_id=run.id,
        library_item_id=item.id if item else None,
        selection=result.get("selection", ""),
        tool=result["tool"],
        question=result.get("question", ""),
        answer={k: result.get(k) for k in ("answer", "not_in_paper", "general")},
        quotes=result.get("statements") or [],
        model=result.get("model") or "",
        created_by=user.id,
    )
    db.add(note)
    db.commit()
    db.refresh(note)
    return _note_out(db, note)
