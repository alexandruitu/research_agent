import uuid

from fastapi import APIRouter, Depends
from sqlalchemy import select

from ...db.models import EvalReport, GoldSet
from ..deps import get_db, require_role
from ..errors import ApiError
from ..schemas import EvalDetailOut, EvalHeadline, EvalSummaryOut, GoldSetOut

router = APIRouter(prefix="/evals", tags=["evals"])


def _ratio(rate):
    return {"k": rate["k"], "n": rate["n"]} if rate else None


def headline(metrics):
    recommended = metrics.get("recommended")
    agreement = metrics.get("agreement") or {}
    return EvalHeadline(
        retrieval_recall=_ratio(metrics.get("retrieval_recall")),
        cascade_recall=_ratio(((metrics.get("strategies") or {}).get("cascade") or {}).get("recall")),
        recommended=(
            {
                "min_confidence": recommended["min_confidence"],
                "exclude_min_confidence": recommended["exclude_min_confidence"],
            }
            if recommended
            else None
        ),
        kappa=(agreement.get("verdict") or {}).get("kappa"),
        same_family=agreement.get("same_family"),
        screened=(metrics.get("counts") or {}).get("screened"),
    )


def _gold(db, report):
    return GoldSetOut.model_validate(db.get(GoldSet, report.gold_set_id))


@router.get("", response_model=list[EvalSummaryOut])
def list_evals(user=Depends(require_role("viewer")), db=Depends(get_db)):
    return [
        EvalSummaryOut(
            id=r.id,
            gold_set=_gold(db, r),
            run_id=r.run_id,
            created_at=r.created_at,
            headline=headline(r.metrics),
        )
        for r in db.scalars(select(EvalReport).order_by(EvalReport.created_at.desc()))
    ]


@router.get("/{eval_id}", response_model=EvalDetailOut)
def get_eval(eval_id: uuid.UUID, user=Depends(require_role("viewer")), db=Depends(get_db)):
    report = db.get(EvalReport, eval_id)
    if report is None:
        raise ApiError(404, "not_found", "No such eval report")
    return EvalDetailOut(
        id=report.id,
        gold_set=_gold(db, report),
        run_id=report.run_id,
        created_at=report.created_at,
        metrics=report.metrics,
        agreement=report.agreement,
    )
