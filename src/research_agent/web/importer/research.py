"""Import a finished research run (`runs/<id>/report.json`) into PostgreSQL, one transaction per run."""

import json
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select

from ..callstore import CallIndex
from ..db.models import CriterionScore, EvidenceClaim, Ranking, Review, Run, Screening
from .common import (
    ImportFailed,
    ImportResult,
    clear_run,
    criterion,
    file_sha256,
    get_or_create_field,
    upsert_paper,
)


def _finished_at(folder):
    try:
        text = json.loads((folder / "progress.json").read_text())["updated_at"]
        return datetime.fromisoformat(text)
    except (OSError, ValueError, KeyError):
        return datetime.now(UTC)


def _review_row(run, paper, role, review, call_key, **detail_extra):
    detail = {k: review[k] for k in ("strengths", "weaknesses", "assessment", "takeaways")} | detail_extra
    return Review(
        run_id=run.id,
        paper_id=paper.id,
        role=role,
        verdict=review["verdict"],
        relevance=review["relevance"],
        methods=review["methods"],
        support=review["support"],
        detail=detail,
        call_key=call_key,
    )


def import_research_run(db, folder, created_by=None):
    folder = Path(folder).resolve()
    report_path = folder / "report.json"
    if not report_path.is_file():
        raise ImportFailed(f"{folder}: no report.json (is the run finished?)")
    digest = file_sha256(report_path)
    run = db.scalar(select(Run).where(Run.folder == str(folder)))
    if run is not None and run.source_sha256 == digest:
        return ImportResult(run.id, "unchanged")
    try:
        data = json.loads(report_path.read_text())
        state, manifest = data["state"], data["manifest"]
        with db.begin_nested():  # all-or-nothing: a failure leaves the database as it was
            return _import(db, folder, digest, run, state, manifest, created_by)
    except (KeyError, ValueError, TypeError) as exc:
        raise ImportFailed(f"{folder}: unexpected report.json content ({type(exc).__name__}: {exc})") from exc


def _import(db, folder, digest, run, state, manifest, created_by):
    warnings = []
    field_row = get_or_create_field(db, state["contract"]["topic"], created_by)
    status = "updated" if run is not None else "created"
    if run is None:
        run = Run(
            field_id=field_row.id, kind="research", status="done", folder=str(folder), created_by=created_by
        )
        db.add(run)
    else:
        clear_run(db, run.id)
    run.manifest, run.source_sha256, run.status, run.error = manifest, digest, "done", None
    run.finished_at = _finished_at(folder)
    db.flush()
    calls = CallIndex(folder)
    if calls.empty:
        warnings.append("no raw calls found (research.sqlite missing or empty); the drawer cannot show them")

    papers = {
        p["id"]: upsert_paper(db, p["id"], p.get("doi"), p["title"], p.get("abstract"), p.get("year"))
        for p in state["papers"]
    }

    for pid, screen in state["screens"].items():
        if pid not in papers:
            raise ImportFailed(f"{folder}: screen for unknown paper {pid}")
        paper, tier = papers[pid], screen.get("tier", "llm")
        jev = screen.get("jev") or {}
        key = None
        if tier == "llm":
            key = calls.key("screen", pid)
        elif tier == "jev":
            key = calls.jev_key(paper.title, paper.abstract)
        if key is None and tier != "rule" and not calls.empty:
            warnings.append(f"{pid}: raw call for the {tier} screen not found")
        row = Screening(
            run_id=run.id,
            paper_id=paper.id,
            found_by="query",
            tier=tier,
            decision=screen["decision"],
            jev_decision=jev.get("decision"),
            llm_decision=screen["decision"] if tier == "llm" else None,
            reason=screen.get("reason", ""),
            call_key=key,
        )
        db.add(row)
        db.flush()
        for name, probability in (jev.get("probabilities") or {}).items():
            db.add(
                CriterionScore(
                    screening_id=row.id,
                    criterion_id=criterion(db, field_row, name).id,
                    probability=probability,
                    jev_version=jev.get("model_version", ""),
                )
            )
        if screen["decision"] != "exclude" and tier != "rule" and pid not in state["evidence"]:
            warnings.append(f"{pid}: kept by the screen but has no evidence (expected extraction)")

    for pid, evidence in state["evidence"].items():
        for claim in evidence["claims"]:
            db.add(
                EvidenceClaim(
                    run_id=run.id,
                    paper_id=papers[pid].id,
                    statement=claim["statement"],
                    quote=claim["quote"],
                    call_key=calls.key("extract", pid),
                )
            )
    for role, field_name, call_role in (("a", "reviews_a", "review_a"), ("b", "reviews_b", "review_b")):
        for pid, review in state[field_name].items():
            db.add(_review_row(run, papers[pid], role, review, calls.key(call_role, pid)))
    for pid, decision in state["decisions"].items():
        if decision["adjudicated"]:
            db.add(
                _review_row(
                    run,
                    papers[pid],
                    "adjudicator",
                    decision["review"],
                    calls.key("adjudicate", pid),
                    reason=decision["reason"],
                )
            )
    for position, row in enumerate(state["ranking"], start=1):
        db.add(
            Ranking(run_id=run.id, paper_id=papers[row["paper_id"]].id, score=row["score"], position=position)
        )
    db.flush()
    return ImportResult(run.id, status, warnings)
