"""Import a finished research run (`runs/<id>/report.json`) into PostgreSQL, one transaction per run."""

import json
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select

from ..callstore import CallIndex, CallStoreError
from ..db.models import (
    CriterionScore,
    EvidenceClaim,
    PanelReport,
    PaperReview,
    Ranking,
    RedFlag,
    Review,
    ReviewerProfile,
    ReviewerVersion,
    Run,
    RunReviewer,
    Screening,
)
from ..fields import legacy_version, version_for_domain
from ..review import link_review
from .common import (
    ImportFailed,
    ImportResult,
    clear_run,
    criterion,
    file_sha256,
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


def decided_by(screen):
    """The criterion that dropped the paper. Reports written before slice 2 lack the key; for them (legacy
    runs, one topic question) it is `topic_match` on an exclusion, as the pipeline now records it."""
    if "decided_by" in screen:
        return screen["decided_by"]
    return "topic_match" if screen.get("decision") == "exclude" else None


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
    domain = state["contract"].get("domain")  # a field run (domain.json); None: a legacy topic run
    if domain:
        field_row, version_row = version_for_domain(db, domain, created_by)
    else:
        field_row, version_row = legacy_version(db, state["contract"]["topic"], created_by)
    status = "updated" if run is not None else "created"
    if run is None:
        run = Run(
            field_id=field_row.id, kind="research", status="done", folder=str(folder), created_by=created_by
        )
        db.add(run)
    else:
        clear_run(db, run.id)
    run.field_id = field_row.id  # a re-import may name another topic
    run.field_version_id = version_row.id
    run.manifest, run.source_sha256, run.status, run.error = manifest, digest, "done", None
    run.finished_at = _finished_at(folder)
    run.search_warnings = state.get("search_warnings") if domain else None
    db.flush()
    try:
        calls = CallIndex(folder)
    except CallStoreError as exc:
        raise ImportFailed(f"{folder}: {exc}") from exc
    if calls.empty:
        warnings.append("no raw calls found (research.sqlite missing or empty); the drawer cannot show them")

    papers = {
        p["id"]: upsert_paper(db, p["id"], p.get("doi"), p["title"], p.get("abstract"), p.get("year"))
        for p in state["papers"]
    }
    found_by = {p["id"]: sorted(p.get("sources") or []) for p in state["papers"]}

    for pid, screen in state["screens"].items():
        if pid not in papers:
            raise ImportFailed(f"{folder}: screen for unknown paper {pid}")
        paper, tier = papers[pid], screen.get("tier", "llm")
        jev = screen.get("jev") or {}
        key = None
        if tier == "llm":
            key = (calls.key("screen_criteria", pid) if domain else None) or calls.key("screen", pid)
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
            decided_by=decided_by(screen),
            sources=found_by.get(pid, []),
        )
        db.add(row)
        db.flush()
        if domain:  # per criterion: Jev p, LLM answer, quote (rows with nothing in them are skipped)
            for name, cell in (screen.get("criteria") or {}).items():
                if all(cell.get(k) is None for k in ("jev_p", "llm", "quote")):
                    continue
                db.add(
                    CriterionScore(
                        screening_id=row.id,
                        criterion_id=criterion(db, field_row, name, version_row).id,
                        probability=cell.get("jev_p"),
                        llm_answer=cell.get("llm"),
                        quote=cell.get("quote"),
                        jev_version=jev.get("model_version", ""),
                    )
                )
        else:
            for name, probability in (jev.get("probabilities") or {}).items():
                db.add(
                    CriterionScore(
                        screening_id=row.id,
                        criterion_id=criterion(db, field_row, name, version_row).id,
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
    if state["contract"].get("review"):
        _import_panel(db, run, state, papers, calls, warnings, created_by)
    for position, row in enumerate(state["ranking"], start=1):
        db.add(
            Ranking(run_id=run.id, paper_id=papers[row["paper_id"]].id, score=row["score"], position=position)
        )
    db.flush()
    return ImportResult(run.id, status, warnings)


def _panel_versions(db, run, review, created_by):
    """{reviewer key: ReviewerVersion} of a panel run. A run started by the web app is linked at start;
    an imported one is linked by content (see `review.link_review`)."""
    linked = db.scalars(
        select(RunReviewer).where(RunReviewer.run_id == run.id).order_by(RunReviewer.position)
    ).all()
    if run.settings_version_id is None or not linked:
        settings_row, versions = link_review(db, review, created_by)
        run.settings_version_id = settings_row.id
        for link in linked:
            db.delete(link)
        db.flush()
        for position, version in enumerate(versions):
            db.add(RunReviewer(run_id=run.id, position=position, reviewer_version_id=version.id))
        db.flush()
    rows = db.execute(
        select(ReviewerProfile.key, ReviewerVersion)
        .join(ReviewerVersion, ReviewerVersion.profile_id == ReviewerProfile.id)
        .join(RunReviewer, RunReviewer.reviewer_version_id == ReviewerVersion.id)
        .where(RunReviewer.run_id == run.id)
    )
    return {key: version for key, version in rows}


def _import_panel(db, run, state, papers, calls, warnings, created_by):
    review = state["contract"]["review"]
    versions = _panel_versions(db, run, review, created_by)
    order = [entry["key"] for entry in review["panel"]]
    for pid, result in (state.get("review") or {}).items():
        if pid not in papers:
            raise ImportFailed(f"panel review for unknown paper {pid}")
        editor = result.get("editor") or {}
        flags = result.get("red_flags") or []
        row = PaperReview(
            run_id=run.id,
            paper_id=papers[pid].id,
            text_source=result["text_source"],
            text_licence=result.get("text_licence"),  # absent in reports before slice 5
            text_reason=result.get("text_reason"),
            text_origin=result.get("text_origin"),
            text_sections=list(result.get("text_sections") or []),
            text_truncated=bool(result.get("text_truncated")),
            text_chars=result.get("text_chars"),
            editor_verdict=editor.get("verdict"),
            editor_reason=editor.get("reason", ""),
            disagreements=list(editor.get("disagreements") or []),
            editor_call_key=calls.key("editor", pid),
            score=result.get("score"),
            coverage=result.get("coverage"),
            red_flag_count=len(flags),
        )
        db.add(row)
        db.flush()
        if editor and row.editor_call_key is None and not calls.empty:
            warnings.append(f"{pid}: raw call for the editor not found")
        reports = result.get("reviews") or {}
        for key in sorted(reports, key=lambda k: (order.index(k) if k in order else len(order), k)):
            report = reports[key]
            call_key = calls.key(f"review:{key}", pid)
            if call_key is None and not calls.empty:
                warnings.append(f"{pid}: raw call for reviewer {key} not found")
            version = versions.get(key)
            db.add(
                PanelReport(
                    paper_review_id=row.id,
                    position=order.index(key) if key in order else len(order),
                    reviewer_key=key,
                    reviewer_version_id=version.id if version else None,
                    name=report.get("name") or key,
                    version=report.get("version") or 1,
                    verdict=report["verdict"],
                    strengths=list(report.get("strengths") or []),
                    weaknesses=list(report.get("weaknesses") or []),
                    summary=report.get("summary", ""),
                    score=report.get("score"),
                    coverage=report.get("coverage"),
                    answers=list(report.get("answers") or []),
                    call_key=call_key,
                )
            )
        for position, flag in enumerate(flags):
            db.add(
                RedFlag(
                    paper_review_id=row.id,
                    position=position,
                    text=flag["text"],
                    source=flag.get("source"),
                    raised_by=list(flag.get("raised_by") or []),
                )
            )
    db.flush()
