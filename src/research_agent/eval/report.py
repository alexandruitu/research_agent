"""Offline metrics from cached calls. No network, no API keys, no new model calls."""

import json
from pathlib import Path

from ..agents import Evaluator
from ..jev import JevScreener, JevThresholds
from ..schemas import Screen
from ..storage import MissingCall, Store
from .gold import gold_paper, load_gold
from .metrics import STRATEGIES, cohen_kappa, evaluate, rate, recommend, sweep, weighted_kappa
from .screen import read_manifest


class ReportError(RuntimeError):
    """The report cannot be computed faithfully (missing calls, mixed model versions, stale gold)."""


def load_records(gold, store, evaluator, jev, allow_mixed=False):
    """Cached Jev probabilities + LLM screen decision for every candidate with an abstract."""
    records, versions, missing = [], set(), 0
    for candidate in gold.candidates:
        if not candidate.abstract:
            continue
        paper = gold_paper(candidate, gold).model_dump()
        try:
            probabilities, version = jev.cached_probabilities(gold.topic, paper)
            llm = evaluator.ask("screen", Screen, {"topic": gold.topic, "paper": paper}).decision
        except MissingCall:
            missing += 1
            continue
        versions.add(version)
        records.append(
            {
                "id": candidate.id,
                "title": candidate.title,
                "label": candidate.label,
                "probabilities": probabilities,
                "llm": llm,
            }
        )
    if missing:
        raise ReportError(
            f"{missing} candidate(s) have missing cached calls; run `research-eval screen` for this gold set first "
            "(a prompt-version change also invalidates the cache)"
        )
    if len(versions) > 1 and not allow_mixed:
        raise ReportError(
            f"Jev model versions differ across cached calls ({sorted(versions)}); "
            "re-screen, or pass --allow-mixed-jev-versions"
        )
    return records, sorted(versions)


def _load_run(run_dir, allow_mixed):
    manifest = read_manifest(run_dir)
    gold = load_gold(manifest["gold_path"])
    if gold.content_sha256 != manifest["gold_sha256"]:
        raise ReportError("gold file changed since this run was screened; re-run `research-eval screen`")
    store = Store(run_dir)
    evaluator = Evaluator(store, manifest["mode"], manifest["models"], offline=True)
    jev = JevScreener(store, "offline", model=manifest["jev_model"])
    records, versions = load_records(gold, store, evaluator, jev, allow_mixed)
    return manifest, gold, records, versions


def _provider(models, role):
    model = models.get(role)
    return model.split(":")[0] if model and ":" in model else None


def _agreement(run_dir, manifest, gold):
    path = Path(run_dir) / "agreement.json"
    if not path.exists():
        return None
    papers = json.loads(path.read_text())["papers"]
    if not papers:
        return None
    if set(papers) - {c.id for c in gold.candidates}:
        raise ReportError("agreement.json does not belong to this gold set; re-run `research-eval agreement`")
    ids = sorted(papers)
    a = [papers[i]["review_a"] for i in ids]
    b = [papers[i]["review_b"] for i in ids]
    provider_a, provider_b = (
        _provider(manifest["models"], "review_a"),
        _provider(manifest["models"], "review_b"),
    )
    return {
        "n": len(ids),
        "verdict": cohen_kappa([r["verdict"] for r in a], [r["verdict"] for r in b]),
        "scores": {
            key: weighted_kappa([r[key] for r in a], [r[key] for r in b])
            for key in ("relevance", "methods", "support")
        },
        "adjudication_rate": rate(sum(papers[i]["adjudicated"] for i in ids), len(ids)),
        "same_family": None if None in (provider_a, provider_b) else provider_a == provider_b,
    }


def _thresholds(row):
    return {"min_confidence": row["min_confidence"], "exclude_min_confidence": row["exclude_min_confidence"]}


def _lost_text(lost):
    return "; ".join(f"{m['id']} '{m['title']}'" for m in lost)


def build_report(run_dir, target_recall=None, holdout_dir=None, allow_mixed=False):
    run_dir = Path(run_dir)
    manifest, gold, records, versions = _load_run(run_dir, allow_mixed)
    if holdout_dir:
        try:
            same = read_manifest(holdout_dir)["gold_sha256"] == manifest["gold_sha256"]
        except ValueError as exc:
            raise ReportError(f"holdout run {holdout_dir}: {exc}") from exc
        if same:
            raise ReportError("holdout run uses the same gold set; it must be a different SR")
    default = JevThresholds()
    strategies = {name: evaluate(records, name, default) for name in STRATEGIES}
    rows = sweep(records)
    positives = [c for c in gold.candidates if c.label == "include"]
    total = len(positives) + len(gold.unresolved) + len(gold.ambiguous)
    warnings = []
    if len(versions) > 1:
        warnings.append(f"Mixed Jev model versions in this run: {versions}.")
    other_records = holdout_rows = None
    if holdout_dir:
        try:
            _m, other, other_records, other_versions = _load_run(holdout_dir, allow_mixed)
        except (ReportError, ValueError) as exc:
            raise ReportError(f"holdout run {holdout_dir}: {exc}") from exc
        if len(other_versions) > 1 or other_versions != versions:
            warnings.append(
                f"Holdout Jev model versions {other_versions} differ from the main run's {versions} "
                "(or are mixed); the recommended pair may not transfer."
            )
        holdout_rows = sweep(other_records)
    # With no screened SR-included paper, "loses nothing" would hold vacuously: recommend nothing.
    has_positives = any(r["label"] == "include" for r in records)
    best = recommend(rows, target_recall, holdout_rows) if has_positives else None
    best_main_only = recommend(rows, target_recall) if has_positives else None
    if not has_positives:
        warnings.append("No SR-included paper with an abstract was screened; recall is undefined.")
    elif best is None:
        where = " on the main or the holdout set" if holdout_dir else ""
        message = (
            "No threshold pair is admissible: every pair loses at least one SR-included paper "
            f"that llm_only keeps{where}."
        )
        if target_recall is not None:
            message += f" No threshold pair reaches recall >= {target_recall} either."
        warnings.append(message)
    if best and best["kept_negatives"] > strategies["llm_only"]["kept_negatives"]:
        warnings.append(
            f"The recommended pair forwards more non-included papers than llm_only "
            f"({best['kept_negatives']} vs {strategies['llm_only']['kept_negatives']}); "
            "consider a stricter include threshold."
        )
    rejected = None
    if holdout_dir and best_main_only and (best is None or _thresholds(best) != _thresholds(best_main_only)):
        thresholds = _thresholds(best_main_only)
        lost = evaluate(other_records, "cascade", JevThresholds(**thresholds))["lost_vs_llm"]
        if lost:  # otherwise the pair is merely outranked, not rejected
            rejected = {"thresholds": thresholds, "lost": lost}
            noun = "paper" if len(lost) == 1 else "papers"
            warnings.append(
                f"The main-set-only pick include>={thresholds['min_confidence']}/"
                f"exclude>={thresholds['exclude_min_confidence']} loses {len(lost)} SR-included {noun} "
                f"on the holdout that llm_only keeps: {_lost_text(lost)}. Rejected."
            )
    holdout = None
    if holdout_dir and best:
        thresholds = _thresholds(best)
        out = evaluate(other_records, "cascade", JevThresholds(**thresholds))
        holdout = {
            "gold": other.name,
            "n": len(other_records),
            "jev_model_versions": other_versions,
            "thresholds": thresholds,
            "recall": out["recall"],
            "missed": out["missed"],
            "lost_vs_llm": out["lost_vs_llm"],
            "calls_saved": out["calls_saved"],
        }
    elif not holdout_dir:
        warnings.append("Recommended thresholds are untested on held-out data (no usable --holdout run).")
    return {
        "gold": {
            "name": gold.name,
            "citation": gold.citation,
            "topic": gold.topic,
            "query": gold.query,
            "sha256": gold.content_sha256,
        },
        "run": {
            "prompt_version": manifest["prompt_version"],
            "jev_screen_version": manifest["jev_screen_version"],
            "models": manifest["models"],
        },
        "jev_model_versions": versions,
        "counts": {
            "candidates": len(gold.candidates),
            "screened": len(records),
            "positives_total": total,
            "positives_resolved": len(positives),
            "positives_screened": sum(r["label"] == "include" for r in records),
            "positives_no_abstract": sum(1 for c in positives if not c.abstract),
            "unresolved": len(gold.unresolved),
            "ambiguous": len(gold.ambiguous),
        },
        "retrieval_recall": rate(sum(c.via == "query" for c in positives), total),
        "default_thresholds": {
            "min_confidence": default.min_confidence,
            "exclude_min_confidence": default.exclude_min_confidence,
        },
        "strategies": strategies,
        "sweep": rows,
        "target_recall": target_recall,
        "recommended": best,
        "rejected_on_holdout": rejected,
        "holdout": holdout,
        "screen_vs_gold": cohen_kappa(
            ["excluded" if r["llm"] == "exclude" else "kept" for r in records],
            ["kept" if r["label"] == "include" else "excluded" for r in records],
        )
        if records
        else None,
        "agreement": _agreement(run_dir, manifest, gold),
        "warnings": warnings,
    }


def fmt_rate(r):
    if r["value"] is None:
        return f"n/a ({r['reason']})"
    low, high = r["ci"]
    return f"{r['value']:.3f} ({r['k']}/{r['n']}; 95% CI {low:.3f}-{high:.3f})"


def _fmt_kappa(k):
    """Kappa next to raw agreement and class prevalence, since kappa collapses under skewed classes."""
    prevalence = ", ".join(f"{label} {value:.2f}" for label, value in k["prevalence"].items())
    context = f"agreement {k['agreement']:.2f}; prevalence {prevalence}"
    if k["kappa"] is None:
        return f"n/a ({k['reason']}); {context}"
    return f"{round(k['kappa'], 3) + 0.0:.3f}; {context}"  # + 0.0 turns -0.0 into 0.0


def _count_pct(count, total):
    return f"{count} ({100 * count / total:.1f}%)" if total else f"{count} (n/a)"


def _run_line(run):
    models = ", ".join(f"{role}={model}" for role, model in sorted(run["models"].items())) or "none recorded"
    return f"Run: prompt {run['prompt_version']} · jev-screen {run['jev_screen_version']} · models: {models}"


def _probabilities(probabilities):
    return ", ".join(f"{question}={p:.2f}" for question, p in probabilities.items())


def _lost_line(m):
    return f"{m['id']} · {m['title']} · Jev {_probabilities(m['probabilities'])} · decided by {m['tier']}"


def render_markdown(report):
    g, c = report["gold"], report["counts"]
    out = [
        f"# Eval report: {g['name']}",
        "",
        f"{g['citation']} · topic: {g['topic']} · gold `{g['sha256'][:12]}`",
        "",
        _run_line(report["run"]),
        "",
    ]
    out += [
        "## Retrieval recall",
        "",
        (
            f"{fmt_rate(report['retrieval_recall'])} of SR-included studies were found by the search query "
            f"(unresolved: {c['unresolved']}, ambiguous: {c['ambiguous']} count as misses)."
        ),
        "",
        "## Screening recall",
        "",
        (
            f"Kept = not excluded. Denominator: {c['positives_screened']} SR-included papers with an abstract "
            f"({c['positives_no_abstract']} without abstract are not screened). "
            f"Jev thresholds: include >= {report['default_thresholds']['min_confidence']}, "
            f"exclude >= {report['default_thresholds']['exclude_min_confidence']}."
        ),
        "",
        (
            "| strategy | recall | missed | auto-included | auto-excluded | sent to LLM "
            "| LLM screen calls saved | kept | kept non-included |"
        ),
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for name, s in report["strategies"].items():
        sent = _count_pct(s["escalated"], c["screened"])
        if name == "jev_only":
            sent += " undecided (kept, no LLM look) [1]"
        out.append(
            f"| {name} | {fmt_rate(s['recall'])} | {len(s['missed'])} "
            f"| {_count_pct(s['auto_include'], c['screened'])} | {_count_pct(s['auto_exclude'], c['screened'])} "
            f"| {sent} | {s['calls_saved']} of {c['screened']} | {s['kept']} | {s['kept_negatives']} |"
        )
    out += [
        "",
        (
            "[1] jev_only makes no LLM calls: undecided papers are kept without any LLM look, "
            "so its recall is not comparable with cascade."
        ),
    ]
    out += ["", "## Missed positives", ""]
    any_missed = False
    for name, s in report["strategies"].items():
        for m in s["missed"]:
            any_missed = True
            out.append(
                f"- **{name}**: {m['id']} · {m['title']} · Jev {_probabilities(m['probabilities'])} · decided by {m['tier']}"
            )
    if not any_missed:
        out.append("None at the default thresholds.")
    out += [
        "",
        "## Threshold sweep",
        "",
        "| include >= | exclude >= | recall | missed | lost vs llm_only | calls saved | kept | kept non-included | note |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    best = report["recommended"]
    default = report["default_thresholds"]
    for r in report["sweep"]:
        pair = (r["min_confidence"], r["exclude_min_confidence"])
        marks = []
        if best and pair == (best["min_confidence"], best["exclude_min_confidence"]):
            marks.append("<-- recommended")
        if pair == (default["min_confidence"], default["exclude_min_confidence"]):
            marks.append("<-- default")
        out.append(
            f"| {pair[0]} | {pair[1]} | {fmt_rate(r['recall'])} | {r['missed']} | {r['lost_vs_llm']} "
            f"| {r['calls_saved']} | {r['kept']} | {r['kept_negatives']} | {' '.join(marks)} |"
        )
    out += [
        "",
        (
            "Note: calls saved counts only screening calls; papers kept are forwarded to extraction and both "
            "reviewers, so a loose include threshold can forward more negatives than llm_only."
        ),
    ]
    target = report["target_recall"]
    extra = "" if target is None else f", recall >= {target}"
    out += ["", f"**Recommended (loses no SR-included paper that llm_only keeps{extra}):** "]
    if best:
        out[-1] += (
            f"include >= {best['min_confidence']}, exclude >= {best['exclude_min_confidence']} "
            f"(recall {fmt_rate(best['recall'])}, {best['calls_saved']} calls saved, "
            f"{best['kept']} kept of which {best['kept_negatives']} not SR-included)."
        )
    else:
        out[-1] += "none: no pair is admissible."
    if report["holdout"] or report["rejected_on_holdout"]:
        out += ["", "## Holdout", ""]
    if report["holdout"]:
        h = report["holdout"]
        out.append(
            f"`{h['gold']}` (n={h['n']}): recall {fmt_rate(h['recall'])}, {h['calls_saved']} calls saved."
        )
        out += ["", "Lost positives (SR-included, kept by llm_only, excluded by the recommended pair):"]
        out += [f"- {_lost_line(m)}" for m in h["lost_vs_llm"]] or ["- none"]
    if report["rejected_on_holdout"]:
        rj = report["rejected_on_holdout"]
        t = rj["thresholds"]
        out += [
            "",
            (
                f"Rejected main-set-only pick include >= {t['min_confidence']}, "
                f"exclude >= {t['exclude_min_confidence']}; on the holdout it loses:"
            ),
        ]
        out += [f"- {_lost_line(m)}" for m in rj["lost"]]
    sg = report["screen_vs_gold"]
    out += ["", "## LLM screen vs SR label", ""]
    if sg is None:
        out.append("n/a (no candidate with an abstract was screened).")
    else:
        out.append(
            f"Cohen's kappa {_fmt_kappa(sg)} (n={sg['n']}). Caution: SR-not-included papers may be on topic, "
            "so a low kappa is expected; recall is the headline metric."
        )
    if report["agreement"]:
        a = report["agreement"]
        out += [
            "",
            "## Reviewer agreement",
            "",
            (
                f"n={a['n']} · same model family: {'unknown' if a['same_family'] is None else a['same_family']} "
                f"· adjudication rate {fmt_rate(a['adjudication_rate'])}"
            ),
            f"- verdict kappa: {_fmt_kappa(a['verdict'])}",
        ]
        out += [f"- {key} weighted kappa: {_fmt_kappa(k)}" for key, k in a["scores"].items()]
    if report["warnings"]:
        out += ["", "## Warnings", ""] + [f"- {w}" for w in report["warnings"]]
    return "\n".join(out) + "\n"


def write_report(run_dir, report):
    run_dir = Path(run_dir)
    (run_dir / "metrics.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
    (run_dir / "metrics.md").write_text(render_markdown(report))
