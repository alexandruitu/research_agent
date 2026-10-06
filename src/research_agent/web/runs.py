"""Runs management, API side: permissions, frozen config, timeline, resume rules, trash, logs, calls,
compare and export. No provider calls happen here; files are only read from run folders inside the runs root."""

import json
import re
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


# --- delete -----------------------------------------------------------------------------------------------------


def trash_folder(settings, run, now=None):
    """Move the run folder to `<runs root>/.trash/<id hex>-<UTC time>`. Nothing is ever unlinked; a folder that
    does not resolve strictly inside the runs root (or is already in the trash) is left where it is.
    Returns "trashed", "missing" or "outside"."""
    folder = folder_of(settings, run)
    if folder is None:
        return "missing" if not run.folder else "outside"
    if not folder.is_dir():
        return "missing"
    trash = Path(settings.runs_dir).resolve() / TRASH
    trash.mkdir(parents=True, exist_ok=True)
    stamp = (now or datetime.now(UTC)).strftime("%Y%m%dT%H%M%SZ")
    target = trash / f"{run.id.hex}-{stamp}"
    n = 1
    while target.exists():
        n += 1
        target = trash / f"{run.id.hex}-{stamp}-{n}"
    folder.rename(target)  # same filesystem (inside the root): an atomic move
    return "trashed"


def check_deletable(db, user, run):
    """Raise RunConflict unless `user` may delete `run` now."""
    from .jobs import active_research_job

    if run.kind != "research":
        raise RunConflict(409, "conflict", "Evaluation runs are managed from Evals")
    require_manage(user, run)
    if run.status in ACTIVE or active_research_job(db, run.id) is not None:
        raise RunConflict(409, "run_active", "Cancel the run before deleting it")
    reports = evals_from(db, run)
    if reports:
        raise RunConflict(
            409,
            "referenced_by_eval",
            f"{len(reports)} evaluation report(s) were computed from this run; they read its folder, "
            "so it cannot be deleted while they exist",
            detail=[str(r["id"]) for r in reports],
        )


def delete_run(db, settings, user, run):
    """Delete the run's rows (children go by ON DELETE CASCADE; library items keep their snapshot with
    run_id set to null) and move its folder to the trash. The caller commits."""
    check_deletable(db, user, run)
    db.delete(run)
    db.flush()
    return trash_folder(settings, run)


# --- debug: log tail, calls -------------------------------------------------------------------------------------

LOG_READ_BYTES = 256 * 1024
LOG_MAX_LINES = 2000
ATTEMPT = re.compile(r"^\S+: attempt \d+ failed \(")


def log_tail(settings, run, lines=200):
    """The last `lines` lines of worker.log (at most 256 KiB read), every secret value replaced by ***.
    Also the failed stage and reason from progress.json and the model-retry lines."""
    from .runner import failure_message, redact

    folder = folder_of(settings, run)
    path = folder / "worker.log" if folder else None
    text, size, exists = "", 0, bool(path and path.is_file())
    if exists:
        size = path.stat().st_size
        with path.open("rb") as handle:
            handle.seek(max(0, size - LOG_READ_BYTES))
            text = handle.read().decode("utf-8", errors="replace")
        if size > LOG_READ_BYTES:
            text = text.split("\n", 1)[-1]  # drop the partial first line
        text = redact(text)
    all_lines = text.splitlines()
    keep = all_lines[-max(1, min(lines, LOG_MAX_LINES)) :] if all_lines else []
    progress = folder_json(settings, run, "progress.json") or {}
    failed = [name for name, state in (progress.get("stages") or {}).items() if state == "failed"]
    reason = None
    if progress.get("status") == "failed" and folder:
        reason = failure_message(folder, None)
    elif run.error:
        reason = run.error
    return {
        "exists": exists,
        "size": size,
        "text": "\n".join(keep) + ("\n" if keep else ""),
        "full": text,
        "truncated": size > LOG_READ_BYTES or len(all_lines) > len(keep),
        "failed_stage": failed[0] if failed else None,
        "reason": redact(reason) if reason else None,
        "attempts": [line for line in all_lines if ATTEMPT.match(line)][-50:],
    }


STAGE_OF_ROLE = {
    "plan": "plan",
    "screen": "screen",
    "screen_criteria": "screen",
    "jev_screen": "screen",
    "extract": "extract",
    "review_a": "review",
    "review_b": "review",
    "adjudicate": "review",
    "editor": "review",
}


def provider_of(model):
    if not model:
        return None
    if ":" in model:
        return model.split(":", 1)[0]
    if model.startswith("jev"):
        return "typesafe"
    if model.startswith("claude"):
        return "anthropic"
    if model.startswith("gemini"):
        return "google_genai"
    return None


def calls_summary(settings, run):
    """Per role and model: calls, characters in and out and an estimated cost (approximate list prices).
    The call cache keeps one row per distinct call and no timing, so cache hits and durations are null."""
    import sqlite3

    from .callstore import CallStoreError, connect_readonly
    from .evals import price

    folder = folder_of(settings, run)
    rows, recorded = [], False
    if folder is not None:
        try:
            connection = connect_readonly(folder)
            try:
                found = connection.execute(
                    "select role, model, count(*), coalesce(sum(length(input)), 0), "
                    "coalesce(sum(length(output)), 0) from calls group by role, model order by role, model"
                ).fetchall()
                recorded = True
            finally:
                connection.close()
        except (CallStoreError, sqlite3.Error):
            found = []
        for role, model, count, input_chars, output_chars in found:
            stage = STAGE_OF_ROLE.get(role) or ("review" if str(role).startswith("review:") else role)
            cost = None if str(model).startswith("jev") else price(model, input_chars, output_chars / 4)
            rows.append(
                {
                    "stage": stage,
                    "role": role,
                    "model": model,
                    "provider": provider_of(model),
                    "calls": count,
                    "input_chars": input_chars,
                    "output_chars": output_chars,
                    "cost_usd": cost,
                    "cache_hits": None,
                    "seconds": None,
                }
            )
    unpriced = sorted({r["model"] for r in rows if r["cost_usd"] is None and r["model"]})
    providers = {}
    for r in rows:
        entry = providers.setdefault(r["provider"] or "unknown", {"calls": 0, "cost_usd": 0.0})
        entry["calls"] += r["calls"]
        entry["cost_usd"] = round(entry["cost_usd"] + (r["cost_usd"] or 0.0), 4)
    return {
        "recorded": recorded,
        "estimate": True,
        "rows": rows,
        "providers": [{"provider": k, **v} for k, v in sorted(providers.items())],
        "totals": {
            "calls": sum(r["calls"] for r in rows),
            "cost_usd": round(sum(r["cost_usd"] or 0.0 for r in rows), 4),
            "unpriced_models": unpriced,
        },
    }


# --- compare ----------------------------------------------------------------------------------------------------

NOT_SCREENED = "rule"


def _results(db, run):
    """{paper_id: {paper, kept, score}} of a run (score: panel score, else ranking score)."""
    from .db.models import Paper, PaperReview, Ranking, Screening

    out = {}
    for screening, paper in db.execute(
        select(Screening, Paper).join(Paper, Paper.id == Screening.paper_id).where(Screening.run_id == run.id)
    ).all():
        out[paper.id] = {
            "paper": paper,
            "kept": screening.tier != NOT_SCREENED and screening.decision != "exclude",
            "decision": screening.decision,
            "tier": screening.tier,
            "score": None,
            "position": None,
        }
    for paper_id, score, position in db.execute(
        select(Ranking.paper_id, Ranking.score, Ranking.position).where(Ranking.run_id == run.id)
    ).all():
        if paper_id in out:
            out[paper_id]["score"], out[paper_id]["position"] = score, position
    for paper_id, score in db.execute(
        select(PaperReview.paper_id, PaperReview.score).where(PaperReview.run_id == run.id)
    ).all():
        if paper_id in out and score is not None:
            out[paper_id]["score"] = score
    return out


def _paper_ref(paper):
    return {"paper_id": paper.id, "source_id": paper.source_id, "title": paper.title, "year": paper.year}


def _config_rows(a, b):
    def text(config, key):
        value = config.get(key)
        if key == "sources":
            return ", ".join(f"{s['name']} ({s['max_results']})" for s in value or []) or None
        if key == "panel":
            return ", ".join(f"{p['key']} v{p['version']}" for p in value or []) or None
        return None if value is None else str(value)

    labels = [
        ("Field", "field_name"),
        ("Field version", "field_version"),
        ("Topic", "topic"),
        ("Sources", "sources"),
        ("Review settings version", "settings_version"),
        ("Panel", "panel"),
        ("Mode", "mode"),
        ("Papers to screen", "max_papers"),
        ("Prompt version", "prompt_version"),
    ]
    rows = [(label, text(a, key), text(b, key)) for label, key in labels]
    for role in sorted(set(a["models"]) | set(b["models"])):
        rows.append((f"Model · {role}", a["models"].get(role), b["models"].get(role)))
    return [{"label": label, "a": x, "b": y, "differs": x != y} for label, x, y in rows]


def compare(db, settings, a, b):
    ra, rb = _results(db, a), _results(db, b)
    kept_only_a, kept_only_b, changes = [], [], []
    for pid in ra.keys() & rb.keys():
        x, y = ra[pid], rb[pid]
        if x["kept"] and not y["kept"]:
            kept_only_a.append(_paper_ref(x["paper"]))
        elif y["kept"] and not x["kept"]:
            kept_only_b.append(_paper_ref(y["paper"]))
        if x["score"] is not None and y["score"] is not None and abs(x["score"] - y["score"]) >= 0.05:
            changes.append(
                _paper_ref(x["paper"])
                | {"a": x["score"], "b": y["score"], "delta": round(y["score"] - x["score"], 2)}
            )
    by_title = lambda p: (p["title"] or "").lower()
    return {
        "config": _config_rows(frozen_config(db, settings, a), frozen_config(db, settings, b)),
        "kept_only_a": sorted(kept_only_a, key=by_title),
        "kept_only_b": sorted(kept_only_b, key=by_title),
        "only_in_a": sorted((_paper_ref(ra[p]["paper"]) for p in ra.keys() - rb.keys()), key=by_title),
        "only_in_b": sorted((_paper_ref(rb[p]["paper"]) for p in rb.keys() - ra.keys()), key=by_title),
        "score_changes": sorted(changes, key=lambda c: -abs(c["delta"])),
    }


# --- export -----------------------------------------------------------------------------------------------------

CSV_COLUMNS = (
    "run",
    "run_name",
    "source_id",
    "doi",
    "title",
    "year",
    "decision",
    "tier",
    "score",
    "position",
)
BUNDLE_FILES = ("report.json", "report.md", "domain.json", "review.json", "manifest.json")
LICENSED = "publisher_licensed"


def to_csv(db, runs):
    import csv
    import io

    from .library import _cell

    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\r\n")
    writer.writerow(CSV_COLUMNS)
    for run in runs:
        rows = sorted(
            _results(db, run).values(),
            key=lambda r: (r["position"] is None, r["position"] or 0, (r["paper"].title or "").lower()),
        )
        for r in rows:
            p = r["paper"]
            writer.writerow(
                _cell(v)
                for v in (
                    run.id,
                    run.name,
                    p.source_id,
                    p.doi,
                    p.title,
                    p.year,
                    r["decision"],
                    r["tier"],
                    r["score"],
                    r["position"],
                )
            )
    return out.getvalue()


def to_bibtex(db, runs):
    """The kept papers of each run (each paper once), as BibTeX."""
    from .library import bibtex_escape

    entries, used, seen = [], set(), set()
    for run in runs:
        for r in _results(db, run).values():
            p = r["paper"]
            if not r["kept"] or p.id in seen:
                continue
            seen.add(p.id)
            base = "ra_" + (re.sub(r"[^A-Za-z0-9]", "", p.source_id) or "paper")
            key, n = base, 1
            while key in used:
                n += 1
                key = f"{base}_{n}"
            used.add(key)
            fields = [("title", p.title), ("year", p.year), ("doi", p.doi)]
            if p.source_id.startswith("arxiv:"):
                fields.append(("eprint", p.source_id.split(":", 1)[1]))
            body = ",\n".join(f"  {k} = {{{bibtex_escape(v)}}}" for k, v in fields if v not in (None, ""))
            entries.append(f"@article{{{key},\n{body}\n}}\n")
    return "\n".join(entries)


def _licensed_papers(report):
    state = (report or {}).get("state") or {}
    licensed = set()
    for section in ("review", "texts"):
        for pid, entry in (state.get(section) or {}).items():
            if isinstance(entry, dict) and entry.get("text_licence") == LICENSED:
                licensed.add(pid)
    return licensed


def _blank_quotes(node):
    if isinstance(node, dict):
        return {
            k: ("" if k in ("quote", "quotes") and isinstance(v, str) else _blank_quotes(v))
            for k, v in node.items()
        }
    if isinstance(node, list):
        return [_blank_quotes(v) for v in node]
    return node


def _withhold(node, licensed):
    """Blank every quote under a key naming a publisher-licensed paper."""
    if isinstance(node, dict):
        return {k: (_blank_quotes(v) if k in licensed else _withhold(v, licensed)) for k, v in node.items()}
    if isinstance(node, list):
        return [_withhold(v, licensed) for v in node]
    return node


def bundle(settings, run):
    """A zip of the run's reports and frozen requests. Never the call cache, checkpoints, uploads or logs.
    Quotes from publisher-licensed texts are blanked and report.md is left out when there are any."""
    import io
    import zipfile

    folder = folder_of(settings, run)
    buffer = io.BytesIO()
    included, notes = [], []
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        report = read_json(folder / "report.json") if folder else None
        licensed = _licensed_papers(report)
        for name in BUNDLE_FILES:
            path = folder / name if folder else None
            if path is None or not path.is_file():
                continue
            if name == "report.json" and licensed:
                archive.writestr(name, json.dumps(_withhold(report, licensed), ensure_ascii=False, indent=2))
                notes.append(f"report.json: quotes of {len(licensed)} publisher-licensed paper(s) withheld.")
            elif name == "report.md" and licensed:
                notes.append("report.md left out: it prints quotes from publisher-licensed texts.")
                continue
            else:
                archive.writestr(name, path.read_bytes())
            included.append(name)
        readme = [
            f"Research run {run.id}" + (f" ({run.name})" if run.name else ""),
            f"Status: {run.status}. Exported {datetime.now(UTC).isoformat(timespec='seconds')}.",
            "Files: " + (", ".join(included) or "none (the run folder is not available)"),
            "Not included: the call cache (research.sqlite), checkpoints, uploads, logs, keys.",
            *notes,
        ]
        archive.writestr("README.txt", "\n".join(readme) + "\n")
    return buffer.getvalue()
