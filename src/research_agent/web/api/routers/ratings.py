"""Human reference ratings: rating samples of a panel eval, blind rating, reveal after submitting.

Blindness: `next` and the sample's progress never carry a model's answer; `reveal` answers only for a paper
this user has submitted. Item wording and reviewer versions come from the panel's frozen review.json."""

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy import func, select

from ....storage import Store
from ... import evals as svc
from ...db.models import EvalReport, HumanRatingRow, Job, RatingSample
from ...jobs import enqueue
from ..deps import get_db, require_role
from ..errors import ApiError
from ..schemas import (
    RatingNextOut,
    RatingSampleOut,
    RatingSampleRequest,
    RatingSubmitIn,
    RatingSubmitOut,
    RevealOut,
)
from .runs import job_out

router = APIRouter(tags=["ratings"])
RATERS_NEEDED = 2  # per paper, recommended by the spec


def _sample(db, sample_id):
    sample = db.get(RatingSample, sample_id)
    if sample is None:
        raise ApiError(404, "not_found", "No such rating sample")
    return sample


def _files(db, sample):
    report = db.get(EvalReport, sample.eval_report_id)
    try:
        return svc.panel_files(db, report)
    except (OSError, ValueError):
        raise ApiError(409, "eval_folder_missing", "The panel eval's folder is not on the server") from None


def _rated(db, sample, user_id=None):
    """{paper id: {rater ids}} (or only this user's papers)."""
    query = select(HumanRatingRow.paper_id, HumanRatingRow.rater_id).where(
        HumanRatingRow.sample_id == sample.id
    )
    if user_id is not None:
        query = query.where(HumanRatingRow.rater_id == user_id)
    out = {}
    for paper_id, rater in db.execute(query.distinct()):
        out.setdefault(paper_id, set()).add(rater)
    return out


def _sample_out(db, sample, user):
    _folder, _review, data = _files(db, sample)
    raters = _rated(db, sample)
    latest = db.scalar(
        select(EvalReport.id)
        .where(EvalReport.kind == "human", EvalReport.config["rating_sample_id"].astext == str(sample.id))
        .order_by(EvalReport.created_at.desc())
        .limit(1)
    )
    papers = [
        {
            "paper_id": pid,
            "title": data["papers"][pid]["title"],
            "score": data["papers"][pid].get("score"),
            "raters": len(raters.get(pid, ())),
            "rated_by_me": user.id in raters.get(pid, ()),
        }
        for pid in sample.paper_ids
    ]
    return RatingSampleOut(
        id=sample.id,
        eval_id=sample.eval_report_id,
        size=sample.size,
        seed=sample.seed,
        created_at=sample.created_at,
        raters_needed=RATERS_NEEDED,
        papers=papers,
        complete_papers=sum(p["raters"] >= RATERS_NEEDED for p in papers),
        my_rated=sum(p["rated_by_me"] for p in papers),
        latest_human_eval_id=latest,
    )


def _reviewers(review):
    return [
        {
            "key": r["key"],
            "name": r.get("name") or r["key"],
            "version": int(r.get("version") or 1),
            "items": [{"key": i["key"], "text": i["text"]} for i in r["items"]],
        }
        for r in review["panel"]
    ]


@router.post("/evals/{eval_id}/rating-samples", response_model=RatingSampleOut, status_code=201)
def create_sample(
    eval_id: uuid.UUID, body: RatingSampleRequest, user=Depends(require_role("admin")), db=Depends(get_db)
):
    report = db.get(EvalReport, eval_id)
    if report is None:
        raise ApiError(404, "not_found", "No such eval report")
    if report.kind not in svc.PANEL_KINDS:
        raise ApiError(422, "wrong_kind", "Rating samples are drawn from a panel evaluation")
    try:
        folder, _review, data = svc.panel_files(db, report)
    except (OSError, ValueError):
        raise ApiError(409, "eval_folder_missing", "The panel eval's folder is not on the server") from None
    ids = svc.stratified_sample(data["papers"], body.size, body.seed)
    sample = RatingSample(
        eval_report_id=report.id,
        folder=str(folder),
        size=len(ids),
        seed=body.seed,
        paper_ids=ids,
        created_by=user.id,
    )
    db.add(sample)
    db.commit()
    return _sample_out(db, sample, user)


@router.get("/rating-samples/{sample_id}", response_model=RatingSampleOut)
def get_sample(sample_id: uuid.UUID, user=Depends(require_role("viewer")), db=Depends(get_db)):
    return _sample_out(db, _sample(db, sample_id), user)


@router.get("/rating-samples/{sample_id}/next", response_model=RatingNextOut)
def next_paper(sample_id: uuid.UUID, user=Depends(require_role("member")), db=Depends(get_db)):
    """The paper this user should rate next: not yet rated by them, fewest raters first, then sample order."""
    sample = _sample(db, sample_id)
    folder, review, data = _files(db, sample)
    raters, mine = _rated(db, sample), _rated(db, sample, user.id)
    open_ids = [pid for pid in sample.paper_ids if pid not in mine]
    base = {"reviewers": _reviewers(review), "position": len(mine), "total": len(sample.paper_ids)}
    if not open_ids:
        return RatingNextOut(done=True, paper=None, **base)
    pid = min(open_ids, key=lambda p: (len(raters.get(p, ())), sample.paper_ids.index(p)))
    paper = data["papers"][pid]
    try:
        content = Store(folder).raw_payload(paper["text_sha256"])["fulltext"]
    except (KeyError, TypeError, OSError):
        raise ApiError(
            409, "text_missing", "The text this paper was reviewed on is not in the eval folder"
        ) from None
    return RatingNextOut(
        done=False,
        paper={
            "paper_id": pid,
            "title": paper["title"],
            "year": str(paper.get("year") or ""),
            "text": {"source": paper["text_source"], "content": content, "chars": len(content)},
        },
        **base,
    )


def _queued_human_job(db, sample):
    return db.scalar(
        select(Job).where(
            Job.kind == "eval_run",
            Job.status == "queued",
            Job.payload["rating_sample_id"].astext == str(sample.id),
        )
    )


@router.post("/rating-samples/{sample_id}/ratings", response_model=RatingSubmitOut, status_code=201)
def submit_ratings(
    sample_id: uuid.UUID, body: RatingSubmitIn, user=Depends(require_role("member")), db=Depends(get_db)
):
    """All items of all reviewers for one paper, once per rater; then a human-reference recompute is queued."""
    sample = _sample(db, sample_id)
    if body.paper_id not in sample.paper_ids:
        raise ApiError(404, "not_found", "This paper is not in the rating sample")
    _folder, review, _data = _files(db, sample)
    expected = {(r["key"], i["key"]): (r, i) for r in _reviewers(review) for i in r["items"]}
    given = {(a.reviewer, a.item): a for a in body.answers}
    if len(given) != len(body.answers) or set(given) != set(expected):
        raise ApiError(422, "validation_error", "Answer every checklist item of every reviewer exactly once")
    already = db.scalar(
        select(func.count())
        .select_from(HumanRatingRow)
        .where(
            HumanRatingRow.sample_id == sample.id,
            HumanRatingRow.paper_id == body.paper_id,
            HumanRatingRow.rater_id == user.id,
        )
    )
    if already:
        raise ApiError(409, "already_rated", "You have already rated this paper")
    for (reviewer_key, item_key), answer in given.items():
        reviewer, item = expected[(reviewer_key, item_key)]
        db.add(
            HumanRatingRow(
                sample_id=sample.id,
                paper_id=body.paper_id,
                rater_id=user.id,
                reviewer=reviewer_key,
                reviewer_version=reviewer["version"],
                item=item_key,
                item_text=item["text"],
                answer=answer.answer,
                quote=answer.quote.strip(),
            )
        )
    db.flush()
    job = None
    if _queued_human_job(db, sample) is None:
        payload = {
            "kind": "human",
            "folder": f"human-{uuid.uuid4().hex[:12]}",
            "mode": "demo",  # offline: no model calls in a human recompute
            "rating_sample_id": str(sample.id),
            "parent_id": str(sample.eval_report_id),
        }
        job, _created = enqueue(db, "eval_run", payload, user.id)
    db.commit()
    return RatingSubmitOut(paper_id=body.paper_id, saved=len(given), job=job_out(job) if job else None)


@router.get("/rating-samples/{sample_id}/papers/{paper_id}/reveal", response_model=RevealOut)
def reveal(sample_id: uuid.UUID, paper_id: str, user=Depends(require_role("member")), db=Depends(get_db)):
    sample = _sample(db, sample_id)
    if paper_id not in sample.paper_ids:
        raise ApiError(404, "not_found", "This paper is not in the rating sample")
    mine = {
        (r.reviewer, r.item): r
        for r in db.scalars(
            select(HumanRatingRow).where(
                HumanRatingRow.sample_id == sample.id,
                HumanRatingRow.paper_id == paper_id,
                HumanRatingRow.rater_id == user.id,
            )
        )
    }
    if not mine:
        raise ApiError(409, "not_rated", "Submit your ratings for this paper first")
    _folder, review, data = _files(db, sample)
    paper = data["papers"][paper_id]
    items, agreed, compared = [], 0, 0
    for reviewer in _reviewers(review):
        answers = {a["key"]: a for a in (paper["reviews"].get(reviewer["key"]) or {}).get("answers", [])}
        for item in reviewer["items"]:
            own = mine.get((reviewer["key"], item["key"]))
            if own is None:
                continue
            model = answers.get(item["key"])
            agree = None if model is None else model["answer"] == own.answer
            compared += agree is not None
            agreed += bool(agree)
            items.append(
                {
                    "reviewer": reviewer["key"],
                    "item": item["key"],
                    "text": own.item_text,
                    "mine": {"answer": own.answer, "quote": own.quote},
                    "model": {
                        "answer": model["answer"],
                        "quote": model.get("quote", ""),
                        "section": model.get("section", ""),
                    }
                    if model
                    else None,
                    "agree": agree,
                }
            )
    return RevealOut(paper_id=paper_id, title=paper["title"], items=items, agreed=agreed, compared=compared)
