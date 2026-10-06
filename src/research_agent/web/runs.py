"""Runs management, API side: permissions, frozen config, timeline, resume rules, trash, logs, calls,
compare and export. No provider calls happen here; files are only read from run folders inside the runs root."""

import json
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import func, select

from ..agents import PROMPT_VERSION
from .db.models import (
    EvalReport,
    Field,
    FieldVersion,
    LibraryItem,
    ReviewerProfile,
    ReviewerVersion,
    Run,
    RunReviewer,
    SettingsVersion,
    User,
)

TRASH = ".trash"
RESUMABLE = ("failed", "cancelled")
ACTIVE = ("queued", "running")


class RunConflict(Exception):
    def __init__(self, status, code, message, detail=None):
        super().__init__(message)
        self.status, self.code, self.message, self.detail = status, code, message, detail


# --- permissions ------------------------------------------------------------------------------------------------


def can_manage(user, run):
    """The run's creator or an admin (an imported run has no creator: admins only)."""
    return user.role == "admin" or (run.created_by is not None and run.created_by == user.id)


def require_manage(user, run):
    if not can_manage(user, run):
        raise RunConflict(403, "forbidden", "Only the run's creator or an admin can do this")


# --- folders ----------------------------------------------------------------------------------------------------


def folder_of(settings, run):
    """The run folder, resolved, when it lies strictly inside the runs root (and not in the trash); else None."""
    if not run.folder:
        return None
    root = Path(settings.runs_dir).resolve()
    folder = Path(run.folder).resolve()
    if folder == root or not folder.is_relative_to(root) or folder.is_relative_to(root / TRASH):
        return None
    return folder


def read_json(path):
    try:
        return json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return None


def folder_json(settings, run, name):
    folder = folder_of(settings, run)
    return read_json(folder / name) if folder else None


# --- frozen configuration ---------------------------------------------------------------------------------------


def _panel(db, run):
    rows = db.execute(
        select(RunReviewer.position, ReviewerProfile.key, ReviewerVersion.name, ReviewerVersion.version)
        .join(ReviewerVersion, ReviewerVersion.id == RunReviewer.reviewer_version_id)
        .join(ReviewerProfile, ReviewerProfile.id == ReviewerVersion.profile_id)
        .where(RunReviewer.run_id == run.id)
        .order_by(RunReviewer.position)
    ).all()
    if rows:
        return [{"key": key, "name": name, "version": version} for _pos, key, name, version in rows]
    review = (run.manifest or {}).get("review_request") or (run.manifest or {}).get("review") or {}
    return [
        {"key": r.get("key"), "name": r.get("name") or r.get("key"), "version": r.get("version")}
        for r in review.get("panel") or []
        if isinstance(r, dict)
    ]


def models_of(run, folder_manifest=None):
    manifest = run.manifest or {}
    review = manifest.get("review_request") or manifest.get("review") or {}
    models = {k: v for k, v in (review.get("models") or {}).items() if isinstance(v, str) and v}
    for source in (manifest.get("models") or {}, (folder_manifest or {}).get("models") or {}):
        models |= {k: v for k, v in source.items() if isinstance(v, str)}
    return models


def frozen_config(db, settings, run):
    manifest = run.manifest or {}
    saved = folder_json(settings, run, "manifest.json") or {}
    contract = manifest.get("contract") or saved.get("contract") or {}
    domain = manifest.get("domain_request") or manifest.get("domain") or saved.get("domain") or {}
    field = db.get(Field, run.field_id)
    version = db.get(FieldVersion, run.field_version_id) if run.field_version_id else None
    review = db.get(SettingsVersion, run.settings_version_id) if run.settings_version_id else None
    sources = [
        {"name": s.get("name"), "max_results": s.get("max_results")}
        for s in domain.get("sources") or []
        if isinstance(s, dict)
    ]
    return {
        "field_id": run.field_id,
        "field_name": field.name if field else "",
        "field_version": version.version if version else None,
        "topic": domain.get("topic") or contract.get("topic") or (field.topic if field else ""),
        "sources": sources,
        "settings_version": review.version if review else None,
        "panel": _panel(db, run),
        "models": models_of(run, saved),
        "mode": contract.get("mode"),
        "max_papers": contract.get("max_papers"),
        "prompt_version": saved.get("prompt_version") or manifest.get("prompt_version"),
        "jev": bool(contract.get("jev")) if "jev" in contract else None,
    }


# --- timeline, duration -----------------------------------------------------------------------------------------


def _time(value):
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    try:
        parsed = datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _seconds(start, end):
    start, end = _time(start), _time(end)
    return round((end - start).total_seconds(), 1) if start and end else None


def timeline(settings, run):
    """Stages in pipeline order with start, finish and seconds (null: not recorded, runs before slice 7)."""
    progress = folder_json(settings, run, "progress.json") or {}
    timings = progress.get("timings") or {}
    stages = []
    for name, status in (progress.get("stages") or {}).items():
        timing = timings.get(name) or {}
        stages.append(
            {
                "name": name,
                "status": status,
                "started_at": _time(timing.get("started_at")),
                "finished_at": _time(timing.get("finished_at")),
                "seconds": _seconds(timing.get("started_at"), timing.get("finished_at")),
            }
        )
    return {
        "stages": stages,
        "started_at": _time(progress.get("started_at")),
        "updated_at": _time(progress.get("updated_at")),
        "status": progress.get("status"),
        "recorded": bool(timings),
    }


def wall_seconds(run, line):
    """Wall time: progress.json start to last update when the run has finished, else the database times."""
    if run.status in ACTIVE:
        return _seconds(run.started_at or line["started_at"], datetime.now(UTC))
    if line["started_at"] and line["updated_at"]:
        return _seconds(line["started_at"], line["updated_at"])
    return _seconds(run.started_at or run.created_at, run.finished_at)


# --- resume -----------------------------------------------------------------------------------------------------


def resume_state(settings, run):
    """{allowed, code, reason}: whether POST /runs/{id}/resume would be accepted (permissions aside)."""
    if run.kind != "research" or run.status not in RESUMABLE:
        return {
            "allowed": False,
            "code": "not_resumable",
            "reason": "Only a failed or cancelled run can be resumed",
        }
    saved = folder_json(settings, run, "manifest.json")
    if saved and saved.get("prompt_version") not in (None, PROMPT_VERSION):
        return {
            "allowed": False,
            "code": "prompt_version_changed",
            "reason": (
                f"The prompts changed since this run started ({saved['prompt_version']} → {PROMPT_VERSION}); "
                "its checkpoint cannot be continued. Run it again with the same configuration instead."
            ),
        }
    return {"allowed": True, "code": None, "reason": None}


# --- links ------------------------------------------------------------------------------------------------------


def evals_from(db, run):
    """Eval reports computed from this research run (a panel eval of a finished run)."""
    if not run.folder:
        return []
    target = str(Path(run.folder).resolve())
    out = []
    for report, eval_run in db.execute(
        select(EvalReport, Run).join(Run, Run.id == EvalReport.run_id).where(Run.kind == "eval")
    ).all():
        source = ((eval_run.manifest or {}).get("source") or {}).get("run_dir")
        if source and str(Path(source).resolve()) == target:
            out.append({"id": report.id, "kind": report.kind, "created_at": report.created_at})
    return out


def library_count(db, run):
    return db.scalar(select(func.count()).select_from(LibraryItem).where(LibraryItem.run_id == run.id))


def user_names(db, ids):
    ids = {i for i in ids if i}
    if not ids:
        return {}
    return dict(db.execute(select(User.id, User.name).where(User.id.in_(ids))).all())
