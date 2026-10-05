"""Live evals, API side: request -> worker payload, cost estimate, headline and chips, compare, gold sets.

No provider calls happen here (the API never holds keys); the worker runs every evaluation."""

import json
import random
import uuid
from pathlib import Path, PurePosixPath

from sqlalchemy import select

from ..eval.gold import GoldIntegrityError, load_gold
from ..eval.panel_eval import gold_source, run_source
from . import fields as field_svc
from . import review as review_svc
from .db.models import (
    EvalReport,
    Field,
    FieldVersion,
    GoldSet,
    RatingSample,
    Run,
    SettingsVersion,
    WorkerStatus,
)


class EvalConflict(Exception):
    def __init__(self, status, code, message):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


PANEL_KINDS = ("panel", "human")  # reports with a panel folder (panel.json + review.json)
FAMILY = {"screening": "screening", "panel": "panel", "human": "panel", "ablation": "ablation"}


def get(data, dotted):
    node = data
    for part in dotted.split("."):
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    return node


def public(value):
    """Config without server layout: absolute paths become their basename."""
    if isinstance(value, dict):
        return {k: public(v) for k, v in value.items()}
    if isinstance(value, list):
        return [public(v) for v in value]
    if isinstance(value, str) and PurePosixPath(value).is_absolute():
        return PurePosixPath(value).name
    return value


# --- gold sets -------------------------------------------------------------------------------------------------


def gold_path(settings, row):
    return Path(row.path) if row.path else Path(settings.gold_dir) / f"{row.name}.json"


def gold_usable(settings, row):
    path = gold_path(settings, row)
    if not path.is_file():
        return False
    try:
        return load_gold(path).content_sha256 == row.sha256
    except (OSError, ValueError, GoldIntegrityError):
        return False


def load_gold_set(db, settings, gold_set_id):
    row = db.get(GoldSet, gold_set_id) if gold_set_id else None
    if row is None:
        raise EvalConflict(404, "not_found", "No such gold set")
    path = gold_path(settings, row)
    if not path.is_file():
        raise EvalConflict(422, "gold_file_missing", f"The gold file of '{row.name}' is not on the server")
    try:
        gold = load_gold(path)
    except (OSError, ValueError, GoldIntegrityError):
        raise EvalConflict(
            422, "gold_file_changed", f"The gold file of '{row.name}' cannot be read"
        ) from None
    if gold.content_sha256 != row.sha256:
        raise EvalConflict(
            422, "gold_file_changed", f"The gold file of '{row.name}' changed since it was frozen"
        )
    return row, path, gold


def gold_set_out(settings, row):
    return {
        "id": row.id,
        "name": row.name,
        "citation": row.citation,
        "candidates": row.candidates,
        "positives": row.positives,
        "unresolved": row.unresolved,
        "built_in_app": row.path is not None,
        "usable": gold_usable(settings, row),
        "created_at": row.created_at,
    }


def gold_spec(body):
    """SRSpec dict of a POST /gold-sets body (validated again by the worker)."""
    return {
        "name": body.name,
        "citation": body.citation,
        "topic": body.topic,
        "query": body.query,
        "included": [s.model_dump() for s in body.included],
    }


# --- requests -> payloads ---------------------------------------------------------------------------------------


def _report(db, report_id, kinds, what):
    report = db.get(EvalReport, report_id) if report_id else None
    if report is None:
        raise EvalConflict(404, "not_found", f"No such {what}")
    if report.kind not in kinds:
        raise EvalConflict(422, "wrong_kind", f"The {what} must be a {' or '.join(kinds)} evaluation")
    return report


def report_folder(db, report):
    return Path(db.get(Run, report.run_id).folder)


def _finished_run(db, settings, run_id):
    run = db.get(Run, run_id)
    if run is None or run.kind != "research":
        raise EvalConflict(404, "not_found", "No such research run")
    folder = Path(run.folder or "")
    if run.status != "done" or not (folder / "report.json").is_file():
        raise EvalConflict(422, "run_not_finished", "The run has not finished (no report.json)")
    return run, folder


def _review(db, settings_version_id):
    if settings_version_id:
        row = db.get(SettingsVersion, settings_version_id)
        if row is None:
            raise EvalConflict(404, "not_found", "No such review settings version")
    else:
        row = review_svc.current_settings(db)
    try:
        reviewers = review_svc.panel_versions(db, row.default_panel)
        return review_svc.review_dict(review_svc.settings_content(row), reviewers), row
    except review_svc.ReviewConflict as exc:
        raise EvalConflict(exc.status, exc.code, exc.message) from None


def _domain(db, field_version_id):
    version = db.get(FieldVersion, field_version_id)
    if version is None:
        raise EvalConflict(404, "not_found", "No such field version")
    field = db.get(Field, version.field_id)
    if field_svc.is_legacy(db, version):
        return None, version  # a legacy topic: the gold set's own topic question
    try:
        return field_svc.domain_for_version(db, field, version), version
    except field_svc.FieldConflict as exc:
        raise EvalConflict(exc.status, exc.code, exc.message) from None


def build_payload(db, settings, body):
    """The `eval_run` job payload for a POST /evals body. Raises EvalConflict (404/422) before any job."""
    if body.mode == "demo" and not settings.allow_demo:
        raise EvalConflict(422, "validation_error", "demo mode is disabled on this deployment")
    folder = f"{body.kind}-{uuid.uuid4().hex[:12]}"
    payload = {"kind": body.kind, "folder": folder, "mode": body.mode}
    if body.kind == "screening":
        row, path, _gold = load_gold_set(db, settings, body.gold_set_id)
        payload |= {"gold_path": str(path), "gold_set_id": str(row.id)}
        if body.field_version_id:
            domain, version = _domain(db, body.field_version_id)
            payload |= {"domain": domain, "field_version_id": str(version.id)}
        return payload
    if body.kind == "panel":
        if bool(body.gold_set_id) == bool(body.run_id):
            raise EvalConflict(422, "validation_error", "Give either a gold set or a finished run")
        if body.gold_set_id:
            row, path, _gold = load_gold_set(db, settings, body.gold_set_id)
            payload |= {"gold_path": str(path), "gold_set_id": str(row.id)}
        else:
            run, folder_path = _finished_run(db, settings, body.run_id)
            payload |= {"run_dir": str(folder_path), "run_id": str(run.id)}
        review, version = _review(db, body.settings_version_id)
        return payload | {
            "review": review,
            "settings_version_id": str(version.id),
            "sample": body.sample,
            "seed": body.seed,
        }
    if body.kind == "ablation":
        parent = _report(db, body.panel_eval_id, PANEL_KINDS, "panel evaluation")
        return payload | {
            "panel_dir": str(report_folder(db, parent)),
            "parent_id": str(parent.id),
            "rerun_editor": body.rerun_editor,
        }
    sample = db.get(RatingSample, body.rating_sample_id) if body.rating_sample_id else None
    if sample is None:
        raise EvalConflict(404, "not_found", "No such rating sample")
    return payload | {"rating_sample_id": str(sample.id)}


# --- estimate ---------------------------------------------------------------------------------------------------

PROMPT_OVERHEAD = 2500  # system prompt + instruction + JSON schema, chars per call
OUTPUT_TOKENS = {"screen": 200, "review": 1500, "editor": 600, "jev": 0}
REVIEW_CHARS = 3000  # one reviewer's report as the editor reads it
# Approximate list prices, USD per 1M tokens (input, output); matched by substring of the model id.
PRICES = (
    ("claude-opus", 5.0, 25.0),
    ("claude-sonnet", 3.0, 15.0),
    ("claude-haiku", 1.0, 5.0),
    ("gemini-2.5-pro", 1.25, 10.0),
    ("gemini-2.5-flash", 0.30, 2.50),
    ("gemini-3.1-pro", 2.0, 12.0),
)


def price(model, input_chars, output_tokens):
    for needle, per_in, per_out in PRICES:
        if model and needle in model:
            return round((input_chars / 4 * per_in + output_tokens * per_out) / 1_000_000, 4)
    return None


def _line(role, model, calls, input_chars, output_tokens):
    return {
        "role": role,
        "model": model,
        "calls": calls,
        "input_chars": input_chars,
        "output_tokens": output_tokens,
        "cost_usd": price(model, input_chars, output_tokens) if calls else 0.0,
    }


def _worker_model(db, role):
    row = db.get(WorkerStatus, role)
    return row.model if row else None


def _role_model(db, review, role):
    return (
        ((review or {}).get("models") or {}).get(role)
        or _worker_model(db, role)
        or _worker_model(db, "screen")
    )


def _papers_of(payload):
    if payload.get("gold_path"):
        _topic, papers, _rows = gold_source(load_gold(payload["gold_path"]))
    else:
        _topic, papers, _rows = run_source(payload["run_dir"])
    return papers


def _text_chars(papers, review):
    abstracts = [len(p.get("title") or "") + len(p.get("abstract") or "") for p in papers.values()]
    mean = sum(abstracts) // len(abstracts) if abstracts else 0
    fulltext = review.get("fulltext") or {}
    if fulltext.get("sources"):
        return max(mean, int(fulltext.get("max_chars") or 60000))  # upper bound: full text found for all
    return mean


def _panel_lines(db, review, papers_n, text_chars, editor_calls_per_paper=1, reviewers=True):
    lines = []
    if reviewers:
        for r in review["panel"]:
            items = sum(len(i.get("text", "")) for i in r.get("items", []))
            chars = papers_n * (text_chars + items + len(r.get("perspective", "")) + PROMPT_OVERHEAD)
            model = r.get("model") or _worker_model(db, "review_a")
            lines.append(
                _line(f"review:{r['key']}", model, papers_n, chars, papers_n * OUTPUT_TOKENS["review"])
            )
    calls = papers_n * editor_calls_per_paper
    chars = calls * (text_chars + len(review["panel"]) * REVIEW_CHARS + PROMPT_OVERHEAD)
    model = (review.get("editor") or {}).get("model") or _worker_model(db, "adjudicate")
    lines.append(_line("editor", model, calls, chars, calls * OUTPUT_TOKENS["editor"]))
    return lines


def estimate(db, settings, body):
    """Calls and a char-based cost before an evaluation starts. Counts every call (an upper bound: cached
    calls are free); never calls a provider."""
    payload = build_payload(db, settings, body)
    notes = [
        "Counts every call; calls already in a cache cost nothing.",
        "Tokens are estimated as chars / 4.",
    ]
    lines = []
    if body.kind == "screening":
        _row, _path, gold = load_gold_set(db, settings, body.gold_set_id)
        screened = [c for c in gold.candidates if c.abstract]
        chars = sum(len(c.title) + len(c.abstract) + PROMPT_OVERHEAD for c in screened)
        lines.append(_line("jev", "jev", len(screened), chars, 0))
        lines.append(
            _line("screen", _role_model(db, None, "screen"), len(screened), chars, len(screened) * 200)
        )
        notes.append("The LLM screen runs on every candidate here (the report replays the cascade offline).")
    elif body.kind == "panel":
        papers = _papers_of(payload)
        n = min(body.sample, len(papers))
        lines = _panel_lines(db, payload["review"], n, _text_chars(papers, payload["review"]))
        if payload["review"].get("fulltext", {}).get("sources"):
            notes.append("Full-text sources are on: text size assumes the full-text limit for every paper.")
    elif body.kind == "ablation":
        parent = db.get(EvalReport, body.panel_eval_id)
        review = json.loads((report_folder(db, parent) / "review.json").read_text())
        papers_n = get(parent.metrics, "panel.n") or 0
        k = len(review["panel"])
        if body.rerun_editor:
            _folder, _review, data = panel_files(db, parent)
            sizes = [p.get("chars") or 0 for p in data["papers"].values()]
            text = sum(sizes) // len(sizes) if sizes else 0
            lines = _panel_lines(db, review, papers_n, text, 2**k - 2, reviewers=False)
            notes.append(f"The editor is asked once per paper for each of the {2**k - 2} smaller panels.")
        else:
            notes.append("Offline: every reviewer subset is scored in code from cached calls.")
    else:
        notes.append("Offline: recomputed from the panel's cached answers and the ratings.")
    costs = [line["cost_usd"] for line in lines]
    input_chars = sum(line["input_chars"] for line in lines)
    return {
        "kind": body.kind,
        "calls": sum(line["calls"] for line in lines),
        "input_chars": input_chars,
        "input_tokens": input_chars // 4,
        "output_tokens": sum(line["output_tokens"] for line in lines),
        "cost_usd": None if any(c is None for c in costs) else round(sum(costs), 4),
        "lines": lines,
        "notes": notes,
    }


# --- headline, chips, compare -----------------------------------------------------------------------------------


def _ratio(rate):
    return {"k": rate["k"], "n": rate["n"]} if rate else None


def headline(report_or_metrics, kind=None):
    metrics = getattr(report_or_metrics, "metrics", report_or_metrics) or {}
    kind = kind or getattr(report_or_metrics, "kind", None) or "screening"
    out = dict.fromkeys(
        ["retrieval_recall", "cascade_recall", "recommended", "kappa", "same_family", "screened"]
    )
    if kind == "screening":
        recommended, agreement = metrics.get("recommended"), metrics.get("agreement") or {}
        out |= {
            "retrieval_recall": _ratio(metrics.get("retrieval_recall")),
            "cascade_recall": _ratio(get(metrics, "strategies.cascade.recall")),
            "recommended": {
                "min_confidence": recommended["min_confidence"],
                "exclude_min_confidence": recommended["exclude_min_confidence"],
            }
            if recommended
            else None,
            "kappa": get(agreement, "verdict.kappa"),
            "same_family": agreement.get("same_family"),
            "screened": get(metrics, "counts.screened"),
        }
    if kind in PANEL_KINDS:
        out |= {
            "papers": get(metrics, "panel.n"),
            "reviewers": len(get(metrics, "panel.reviewers") or []) or None,
            "fleiss_kappa": get(metrics, "panel.verdicts.fleiss.kappa"),
            "raw_agreement": get(metrics, "panel.verdicts.fleiss.agreement"),
            "editor_vs_majority": get(metrics, "panel.editor_vs_majority.value"),
            "sr_auc": get(metrics, "panel.sr_inclusion_auc.value"),
            "same_family": get(metrics, "panel.model_families.single_family"),
        }
    if kind == "human":
        out |= {
            "human_accuracy": get(metrics, "human.panel.accuracy.value"),
            "human_kappa": get(metrics, "human.panel.kappa.kappa"),
            "human_raters": get(metrics, "human.raters"),
            "human_units": get(metrics, "human.units"),
            "spearman": get(metrics, "human.scores.spearman.rho"),
        }
    if kind == "ablation":
        out |= {
            "papers": get(metrics, "ablation.papers"),
            "reviewers": len(get(metrics, "ablation.reviewers") or []) or None,
            "summary": get(metrics, "ablation.summary.sentence"),
            "verdict_changed": get(metrics, "ablation.summary.verdict_changed"),
            "red_flags_added": get(metrics, "ablation.summary.red_flags_added"),
            "cost_increase": get(metrics, "ablation.summary.cost_increase"),
        }
    return out


def chips(report, gold_name=None):
    config, kind = report.config or {}, report.kind
    out = []
    if gold_name:
        out.append(f"gold {gold_name}")
    if config.get("mode"):
        out.append(config["mode"])
    if kind in PANEL_KINDS:
        panel = config.get("panel") or []
        out.append(f"{len(panel)} reviewers")
        providers = sorted(
            {(p.get("model") or "").split(":", 1)[0] for p in panel if ":" in (p.get("model") or "")}
        )
        out += [f"provider {p}" for p in providers]
        sample = config.get("sample") or {}
        if sample:
            out.append(f"n={sample.get('n')} seed {sample.get('seed')}")
        if (config.get("source") or {}).get("run_dir"):
            out.append("from a run")
    if kind == "ablation":
        out.append(f"{len(config.get('reviewers') or [])} reviewers")
        out.append("editor re-run" if config.get("rerun_editor") else "offline")
    if kind == "human":
        out.append("human reference")
    if config.get("prompt_version"):
        out.append(f"prompt {config['prompt_version']}")
    return out


COMPARE_ROWS = {
    "screening": [
        ("recall", "retrieval_recall.value", "Retrieval recall"),
        ("recall", "strategies.cascade.recall.value", "Cascade recall"),
        ("recall", "strategies.llm_only.recall.value", "LLM-only recall"),
        ("agreement", "agreement.verdict.kappa", "Reviewer A/B kappa"),
        ("counts", "counts.screened", "Screened"),
    ],
    "panel": [
        ("panel", "panel.n", "Papers"),
        ("agreement", "panel.verdicts.fleiss.kappa", "Fleiss kappa (verdict)"),
        ("agreement", "panel.verdicts.fleiss.agreement", "Raw verdict agreement"),
        ("agreement", "panel.editor_vs_majority.value", "Editor = majority"),
        ("reference", "panel.sr_inclusion_auc.value", "SR inclusion AUC"),
        ("families", "panel.model_families.single_family", "One model family"),
        ("human", "human.panel.accuracy.value", "Accuracy vs humans"),
        ("human", "human.panel.kappa.kappa", "Kappa vs humans"),
        ("human", "human.scores.spearman.rho", "Score Spearman vs humans"),
    ],
    "ablation": [
        ("summary", "ablation.summary.verdict_changed", "Last reviewer: verdict changed"),
        ("summary", "ablation.summary.red_flags_added", "Last reviewer: red flags added"),
        ("summary", "ablation.summary.cost_increase", "Last reviewer: cost increase"),
    ]
    + [
        (f"size {k}", f"ablation.sizes.{k}.{field}", f"{k} reviewer(s): {label}")
        for k in ("1", "2", "3")
        for field, label in (
            ("verdict_changed", "verdict changed"),
            ("red_flags_missed", "red flags missed"),
            ("mean_abs_score_delta", "mean |score delta|"),
            ("cost_calls", "calls"),
        )
    ],
}
CONFIG_ROWS = (
    ("mode", "Mode"),
    ("prompt_version", "Prompt version"),
    ("score_version", "Score version"),
    ("sample.n", "Sample size"),
    ("sample.seed", "Seed"),
    ("editor_model", "Editor model"),
    ("rerun_editor", "Editor re-run"),
    ("gold", "Gold set"),
    ("source.gold_sha256", "Gold hash"),
    ("review_sha256", "Review config hash"),
    ("config_sha256", "Config hash"),
)


def _scalar(value):
    if isinstance(value, dict) and "value" in value:
        return value["value"]
    return value if isinstance(value, (int, float, str, bool)) or value is None else json.dumps(value)


def compare(reports):
    family = {FAMILY[r.kind] for r in reports}
    if len(family) != 1:
        raise EvalConflict(422, "mixed_kinds", "Only reports of the same kind can be compared")
    family = family.pop()

    def row(section, key, label, values):
        values = [_scalar(v) for v in values]
        return {
            "section": section,
            "key": key,
            "label": label,
            "values": values,
            "differs": len(set(map(str, values))) > 1,
        }

    metrics = [row(s, k, label, [get(r.metrics, k) for r in reports]) for s, k, label in COMPARE_ROWS[family]]
    if family == "panel":  # per-reviewer models side by side
        keys = []
        for r in reports:
            keys += [p["key"] for p in (r.config.get("panel") or []) if p["key"] not in keys]
        for key in keys:
            values = [
                next((p.get("model") for p in r.config.get("panel") or [] if p["key"] == key), None)
                for r in reports
            ]
            metrics.append(row("models", f"panel.{key}.model", f"Reviewer {key}: model", values))
    config = [row("config", k, label, [get(r.config or {}, k) for r in reports]) for k, label in CONFIG_ROWS]
    return family, metrics, [c for c in config if any(v is not None for v in c["values"])]


# --- rating samples ---------------------------------------------------------------------------------------------


def stratified_sample(papers, size, seed):
    """`papers` {id: panel.json paper}. Sorted by panel score (unscored last, then id), cut into `size`
    equal bins, one seeded pick per bin; returned in score order. Deterministic for a given seed."""
    ordered = sorted(
        papers, key=lambda pid: (papers[pid].get("score") is None, papers[pid].get("score") or 0, pid)
    )
    if size >= len(ordered):
        return ordered
    rng = random.Random(seed)
    picks = []
    for b in range(size):
        start, end = b * len(ordered) // size, (b + 1) * len(ordered) // size
        picks.append(rng.choice(ordered[start:end]))
    return picks


def panel_files(db, report):
    """(folder, review.json dict, panel.json dict) of a panel or human report."""
    folder = report_folder(db, report)
    review = json.loads((folder / "review.json").read_text())
    data = json.loads((folder / "panel.json").read_text())
    return folder, review, data


def latest_children(db, report_id):
    return list(
        db.scalars(
            select(EvalReport).where(EvalReport.parent_id == report_id).order_by(EvalReport.created_at)
        )
    )
