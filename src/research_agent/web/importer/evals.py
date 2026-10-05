"""Import a finished eval run (`evals/<name>/` + its gold file) into PostgreSQL, one transaction per run."""

import json
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import delete, select

from ...eval.gold import GoldIntegrityError, load_gold
from ...eval.human import RATINGS_FILE
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
from ..fields import legacy_version
from ..review import link_review
from .common import (
    ImportFailed,
    ImportResult,
    clear_run,
    criterion,
    file_sha256,
    upsert_paper,
)

THRESHOLDS = JevThresholds()  # the shipped defaults: what `report` calls "cascade"


EVAL_KINDS = ("panel", "ablation")  # folders written by `research-eval panel` / `ablation`
SCREENING_CONFIG = ("gold_sha256", "mode", "models", "jev_model", "prompt_version", "domain_sha256", "topic")


def import_eval_run(
    db, folder, created_by=None, gold_dir=None, *, kind=None, parent_id=None, extra_config=None
):
    """Import an eval folder: a screening run (gold + screen + report) or a panel / ablation eval. `kind`
    overrides the report kind (the worker's `human` job imports a panel folder as kind `human`)."""
    folder = Path(folder).resolve()
    metrics_path, manifest_path = folder / "metrics.json", folder / "manifest.json"
    if not manifest_path.is_file():
        raise ImportFailed(f"{folder}: no manifest.json (run `research-eval screen` first)")
    try:
        manifest_kind = json.loads(manifest_path.read_text()).get("kind")
    except (OSError, ValueError) as exc:
        raise ImportFailed(f"{folder}: cannot read the eval run (manifest.json: {type(exc).__name__})") from exc
    if manifest_kind in EVAL_KINDS:
        return _import_eval_kind(
            db, folder, created_by, gold_dir, kind=kind, parent_id=parent_id, extra_config=extra_config
        )
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
    field_row, version_row = legacy_version(db, gold.topic, created_by)
    gold_row = _gold_set(db, gold)
    status = "updated" if run is not None else "created"
    if run is None:
        run = Run(
            field_id=field_row.id, kind="eval", status="done", folder=str(folder), created_by=created_by
        )
        db.add(run)
    else:
        clear_run(db, run.id)
    run.field_id = field_row.id  # a re-import may name another topic
    run.field_version_id = version_row.id
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
            decided_by="topic_match"
            if decision == "exclude" and list(probabilities) == ["topic_match"]
            else None,
        )
        db.add(row)
        db.flush()
        for name, probability in probabilities.items():
            db.add(
                CriterionScore(
                    screening_id=row.id,
                    criterion_id=criterion(db, field_row, name, version_row).id,
                    probability=probability,
                    jev_version=version,
                )
            )

    agreement_path = folder / "agreement.json"
    agreement = json.loads(agreement_path.read_text())["papers"] if agreement_path.is_file() else {}
    for pid, entry in agreement.items():
        if pid not in papers:
            raise ImportFailed(f"{folder}: agreement.json names an unknown paper {pid}")
        paper, adjudicated = papers[pid], bool(entry["adjudicated"])
        # Whether an adjudication was expected comes from agreement.json, never from whether its row exists:
        # the table shows an expected-but-absent adjudicator as missing, not as "not adjudicated".
        for role in ("a", "b"):
            key = calls.key(f"review_{role}", pid)
            db.add(_review_row(run, paper, role, entry[f"review_{role}"], key, adjudicated=adjudicated))
        try:
            extract = read_call(folder, calls.key("extract", pid) or "")["output"]
        except CallStoreError:
            warnings.append(f"{pid}: extraction call missing from the run's audit trail")
        else:
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
        if adjudicated:
            try:
                adjudication = read_call(folder, calls.key("adjudicate", pid) or "")["output"]
            except CallStoreError:
                warnings.append(f"{pid}: adjudication call missing from the run's audit trail")
            else:
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

    metrics = json.loads((folder / "metrics.json").read_text())
    report = EvalReport(
        kind="screening",
        gold_set_id=gold_row.id,
        run_id=run.id,
        metrics=metrics,
        agreement=metrics.get("agreement"),
        config={"kind": "screening", "gold": gold.name}
        | {k: manifest[k] for k in SCREENING_CONFIG if k in manifest},
        created_by=created_by,
    )
    db.add(report)
    db.flush()
    return ImportResult(run.id, status, warnings, report.id)


def _gold_from_file(db, path, gold_dir):
    path = Path(path)
    if not path.is_file() and gold_dir is not None:
        path = Path(gold_dir) / path.name
    if not path.is_file():
        return None
    return _gold_set(db, load_gold(path))


def _panel_report_for(db, folder):
    """The eval report imported from the panel folder `folder` (an ablation's source), if any."""
    run = db.scalar(select(Run).where(Run.folder == str(Path(folder).resolve())))
    if run is None:
        return None
    return db.scalar(select(EvalReport).where(EvalReport.run_id == run.id))


def _import_eval_kind(db, folder, created_by, gold_dir, *, kind, parent_id, extra_config):
    metrics_path = folder / "metrics.json"
    if not metrics_path.is_file():
        raise ImportFailed(f"{folder}: no metrics.json (run `research-eval report` first)")
    files = [folder / "manifest.json", metrics_path]
    files += [p for p in (folder / RATINGS_FILE,) if p.is_file()]
    digest = file_sha256(*files)
    run = db.scalar(select(Run).where(Run.folder == str(folder)))
    if run is not None and run.source_sha256 == digest:
        report = db.scalar(select(EvalReport).where(EvalReport.run_id == run.id))
        return ImportResult(run.id, "unchanged", [], report.id if report else None)
    try:
        manifest = json.loads((folder / "manifest.json").read_text())
        metrics = json.loads(metrics_path.read_text())
        kind = kind or manifest["kind"]
        warnings, gold_row, settings_row, topic = [], None, None, manifest.get("topic") or ""
        if manifest["kind"] == "panel":
            source = manifest.get("source") or {}
            if source.get("gold_path"):
                gold_row = _gold_from_file(db, source["gold_path"], gold_dir)
                if gold_row is None:
                    warnings.append("the gold file of this panel eval was not found; no gold set linked")
            settings_row, _reviewers = link_review(
                db, json.loads((folder / "review.json").read_text()), created_by
            )
        else:  # ablation: the panel it came from
            panel_dir = Path(manifest["panel_dir"])
            parent = _panel_report_for(db, panel_dir)
            if parent is not None:
                parent_id = parent_id or parent.id
                gold_row = db.get(GoldSet, parent.gold_set_id) if parent.gold_set_id else None
            else:
                warnings.append("the panel eval of this ablation is not imported; no parent linked")
            try:
                topic = json.loads((panel_dir / "manifest.json").read_text()).get("topic") or ""
            except (OSError, ValueError):
                topic = ""
    except (OSError, ValueError, KeyError, TypeError, GoldIntegrityError) as exc:
        raise ImportFailed(f"{folder}: cannot read the eval ({type(exc).__name__}: {exc})") from exc
    with db.begin_nested():
        field_row, version_row = legacy_version(db, topic or f"{kind} evaluation", created_by)
        status = "updated" if run is not None else "created"
        if run is None:
            run = Run(
                field_id=field_row.id, kind="eval", status="done", folder=str(folder), created_by=created_by
            )
            db.add(run)
        else:
            db.execute(delete(EvalReport).where(EvalReport.run_id == run.id))
        run.field_id, run.field_version_id = field_row.id, version_row.id
        run.manifest, run.source_sha256, run.status, run.error = manifest, digest, "done", None
        run.gold_set_id = gold_row.id if gold_row else None
        run.settings_version_id = settings_row.id if settings_row else None
        run.finished_at = datetime.now(UTC)
        db.flush()
        report = EvalReport(
            kind=kind,
            gold_set_id=gold_row.id if gold_row else None,
            run_id=run.id,
            parent_id=parent_id,
            metrics=metrics,
            config={**(metrics.get("config") or {}), **(extra_config or {})},
            created_by=created_by,
        )
        db.add(report)
        db.flush()
    return ImportResult(run.id, status, warnings, report.id)
