"""Import a finished eval run (`evals/<name>/` + its gold file) into PostgreSQL, one transaction per run."""

import json
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import delete, select

from ...eval.metrics import cascade_decision
from ...eval.report import ReportError, load_run
from ...jev import JevError, JevThresholds, decide_from_probabilities
from ..callstore import CallIndex, CallStoreError, read_call
from ..db.models import (
    CriterionScore,
    EvalReport,
    EvidenceClaim,
    GoldLabel,
    GoldSet,
    Review,
    Run,
    Screening,
)
from .common import (
    ImportFailed,
    ImportResult,
    clear_run,
    criterion,
    file_sha256,
    get_or_create_field,
    upsert_paper,
)

THRESHOLDS = JevThresholds()  # the shipped defaults: what `report` calls "cascade"


def import_eval_run(db, folder, created_by=None, gold_dir=None):
    folder = Path(folder).resolve()
    metrics_path, manifest_path = folder / "metrics.json", folder / "manifest.json"
    if not manifest_path.is_file():
        raise ImportFailed(f"{folder}: no manifest.json (run `research-eval screen` first)")
    if not metrics_path.is_file():
        raise ImportFailed(f"{folder}: no metrics.json (run `research-eval report` first)")
    agreement_path = folder / "agreement.json"
    files = [manifest_path, metrics_path] + ([agreement_path] if agreement_path.is_file() else [])
    digest = file_sha256(*files)
    run = db.scalar(select(Run).where(Run.folder == str(folder)))
    if run is not None and run.source_sha256 == digest:
        return ImportResult(run.id, "unchanged")
    try:
        manifest = json.loads(manifest_path.read_text())
        gold_path = Path(manifest["gold_path"])
        if not gold_path.is_file() and gold_dir is not None:
            gold_path = Path(gold_dir) / gold_path.name
        _m, gold, records, versions = load_run(folder, allow_mixed=True, gold_path=gold_path)
    except (OSError, ValueError, KeyError, TypeError, ReportError, JevError) as exc:
        raise ImportFailed(f"{folder}: cannot read the eval run ({type(exc).__name__}: {exc})") from exc
    try:
        with db.begin_nested():  # all-or-nothing: a failure leaves the database as it was
            return _import(db, folder, digest, run, manifest, gold, records, versions, created_by)
    except (KeyError, ValueError, TypeError) as exc:
        raise ImportFailed(f"{folder}: unexpected eval run content ({type(exc).__name__}: {exc})") from exc


def _gold_set(db, gold):
    row = db.scalar(select(GoldSet).where(GoldSet.name == gold.name))
    if row is not None and row.sha256 != gold.content_sha256:
        raise ImportFailed(
            f"gold set '{gold.name}' changed since it was imported (hash differs); import it under a new name"
        )
    if row is None:
        row = GoldSet(name=gold.name, citation=gold.citation, sha256=gold.content_sha256)
        db.add(row)
        db.flush()
    return row


def _review_row(run, paper, role, review, call_key, **extra):
    detail = {
        k: review[k] for k in ("strengths", "weaknesses", "assessment", "takeaways") if k in review
    } | extra
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


def _import(db, folder, digest, run, manifest, gold, records, versions, created_by):
    warnings = []
    field_row = get_or_create_field(db, gold.topic, created_by)
    gold_row = _gold_set(db, gold)
    status = "updated" if run is not None else "created"
    if run is None:
        run = Run(
            field_id=field_row.id, kind="eval", status="done", folder=str(folder), created_by=created_by
        )
        db.add(run)
    else:
        clear_run(db, run.id)
    run.manifest = {**manifest, "jev_model_versions": versions}
    run.source_sha256, run.status, run.error, run.gold_set_id = digest, "done", None, gold_row.id
    run.finished_at = datetime.now(UTC)
    db.flush()

    try:
        calls = CallIndex(folder)
    except CallStoreError as exc:
        raise ImportFailed(f"{folder}: {exc}") from exc
    if calls.empty:
        warnings.append("no raw calls found (research.sqlite missing or empty); the drawer cannot show them")
    papers = {c.id: upsert_paper(db, c.id, c.doi, c.title, c.abstract, c.year) for c in gold.candidates}
    db.execute(delete(GoldLabel).where(GoldLabel.gold_set_id == gold_row.id))
    for c in gold.candidates:
        db.add(
            GoldLabel(
                gold_set_id=gold_row.id,
                paper_id=papers[c.id].id,
                label=c.label,
                label_source=c.label_source,
                via=c.via,
            )
        )
    version = versions[0] if len(versions) == 1 else ""

    by_id = {r["id"]: r for r in records}
    for c in gold.candidates:
        paper, record = papers[c.id], by_id.get(c.id)
        if record is None:  # no abstract: never screened, kept for completeness
            db.add(
                Screening(
                    run_id=run.id,
                    paper_id=paper.id,
                    found_by=c.via,
                    tier="rule",
                    decision="uncertain",
                    reason="No abstract available; not screened",
                )
            )
            continue
        probabilities, llm = record["probabilities"], record["llm"]
        decision, tier = cascade_decision(probabilities, llm, THRESHOLDS)
        jev_decision = decide_from_probabilities(probabilities, THRESHOLDS)
        key = calls.jev_key(paper.title, paper.abstract) if tier == "jev" else calls.key("screen", c.id)
        if key is None and not calls.empty:
            warnings.append(f"{c.id}: raw call for the {tier} screen not found")
        shown = ", ".join(f"{k}={p:.2f}" for k, p in probabilities.items())
        why = "decided by Jev" if tier == "jev" else "Jev was not confident, so the LLM decided"
        row = Screening(
            run_id=run.id,
            paper_id=paper.id,
            found_by=c.via,
            tier=tier,
            decision=decision,
            jev_decision=jev_decision,
            llm_decision=llm,
            reason=f"Jev {shown} ({why}); LLM screen: {llm}",
            call_key=key,
        )
        db.add(row)
        db.flush()
        for name, probability in probabilities.items():
            db.add(
                CriterionScore(
                    screening_id=row.id,
                    criterion_id=criterion(db, field_row, name).id,
                    probability=probability,
                    jev_version=version,
                )
            )

    agreement_path = folder / "agreement.json"
    agreement = json.loads(agreement_path.read_text())["papers"] if agreement_path.is_file() else {}
    for pid, entry in agreement.items():
        if pid not in papers:
            raise ImportFailed(f"{folder}: agreement.json names an unknown paper {pid}")
        paper = papers[pid]
        db.add(_review_row(run, paper, "a", entry["review_a"], calls.key("review_a", pid)))
        db.add(_review_row(run, paper, "b", entry["review_b"], calls.key("review_b", pid)))
        try:
            extract = read_call(folder, calls.key("extract", pid) or "")["output"]
            for claim in extract["claims"]:
                db.add(
                    EvidenceClaim(
                        run_id=run.id,
                        paper_id=paper.id,
                        statement=claim["statement"],
                        quote=claim["quote"],
                        call_key=calls.key("extract", pid),
                    )
                )
            if entry["adjudicated"]:
                adjudication = read_call(folder, calls.key("adjudicate", pid) or "")["output"]
                db.add(
                    _review_row(
                        run,
                        paper,
                        "adjudicator",
                        adjudication["review"],
                        calls.key("adjudicate", pid),
                        reason=adjudication["reason"],
                    )
                )
        except CallStoreError:
            warnings.append(f"{pid}: extraction or adjudication call missing from the run's audit trail")

    metrics = json.loads((folder / "metrics.json").read_text())
    db.add(
        EvalReport(
            gold_set_id=gold_row.id, run_id=run.id, metrics=metrics, agreement=metrics.get("agreement")
        )
    )
    db.flush()
    return ImportResult(run.id, status, warnings)
