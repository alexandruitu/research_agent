"""Offline metrics for panel evals (agreement, coverage, dispersion, SR-inclusion AUC, model families).
Reads panel.json only: no network, no API keys, no model calls."""

import json
import re
from itertools import combinations
from pathlib import Path

from .metrics import (
    auc,
    cohen_kappa,
    dispersion,
    fleiss_kappa,
    majority,
    pairwise_cohen,
    rate,
    unit_agreement,
)

SINGLE_FAMILY_NOTE = "All reviewers use one model family — add a second provider key to compare."
REWORD_AGREEMENT = 0.7  # item agreement below this, or
REWORD_UNANSWERED = 0.5  # this share of unclear / not_reported answers, marks a "candidate to reword"


def provider(model):
    """Provider family of a model id ('anthropic:claude-x' -> 'anthropic'); demo models are 'demo'."""
    if not model:
        return "unknown"
    if model.startswith("synthetic-demo"):
        return "demo"
    if ":" in model:
        return model.split(":", 1)[0]
    for prefix, name in (("claude", "anthropic"), ("gpt", "openai"), ("o1", "openai"), ("gemini", "google")):
        if model.startswith(prefix):
            return name
    return model


def _norm(text):
    return re.sub(r"\s+", " ", text.strip().lower())


def _answers(review):
    return {a["key"]: a["answer"] for a in review["answers"]}


def verdict_agreement(papers, ids, keys):
    labels = {k: [papers[p]["reviews"][k]["verdict"] for p in ids] for k in keys}
    if len(keys) < 2 or not ids:
        return {"fleiss": None, "pairwise": {}, "reason": "needs >= 2 reviewers and >= 1 paper"}
    return {
        "fleiss": fleiss_kappa([[labels[k][i] for k in keys] for i in range(len(ids))]),
        "pairwise": pairwise_cohen(labels),
        "reason": None,
    }


def item_agreement(papers, ids, panel):
    """Items are grouped by their (normalised) text across reviewers: a shared item has several answerers.
    The default panel has disjoint items, so its rows carry 'single answerer' and only the unanswered
    share can flag an item; human ratings (section `human`) give per-item agreement there."""
    groups = {}
    for reviewer in panel:
        for item in reviewer["items"]:
            groups.setdefault(_norm(item["text"]), []).append((reviewer["key"], item))
    rows = []
    for members in groups.values():
        units = [
            {key: _answers(papers[p]["reviews"][key])[item["key"]] for key, item in members} for p in ids
        ]
        counts = {}
        for unit in units:
            for answer in unit.values():
                counts[answer] = counts.get(answer, 0) + 1
        total = sum(counts.values())
        unanswered = (counts.get("unclear", 0) + counts.get("not_reported", 0)) / total if total else None
        agreement = unit_agreement(units)
        share = agreement["share"]["value"]
        reword = (share is not None and share < REWORD_AGREEMENT) or (
            unanswered is not None and unanswered >= REWORD_UNANSWERED
        )
        rows.append(
            {
                "items": [{"reviewer": key, "item": item["key"]} for key, item in members],
                "text": members[0][1]["text"],
                "source": members[0][1].get("source"),
                **agreement,
                "answers": counts,
                "unanswered_share": unanswered,
                "reword_candidate": reword,
            }
        )
    rows.sort(
        key=lambda r: (
            r["share"]["value"] if r["share"]["value"] is not None else 2.0,
            -(r["unanswered_share"] or 0.0),
            r["text"],
        )
    )
    return rows


def coverage(papers, ids, panel):
    """Per reviewer and item: answered (yes/no) share, separately on full text and on abstracts."""
    out = {}
    for reviewer in panel:
        key = reviewer["key"]
        per_item = {}
        for item in reviewer["items"]:
            split = {}
            for kind in ("fulltext", "abstract"):
                chosen = [p for p in ids if (papers[p]["text_source"] == "abstract") == (kind == "abstract")]
                answered = sum(
                    _answers(papers[p]["reviews"][key])[item["key"]] in ("yes", "no") for p in chosen
                )
                split[kind] = rate(answered, len(chosen))
            per_item[item["key"]] = split
        out[key] = per_item
    return out


def score_dispersion(papers, ids, keys):
    rows = [
        {
            "paper_id": p,
            "title": papers[p]["title"],
            "score": papers[p]["score"],
            "scores": {k: papers[p]["reviews"][k]["score"] for k in keys},
            **dispersion([papers[p]["reviews"][k]["score"] for k in keys]),
        }
        for p in ids
    ]
    return sorted(rows, key=lambda r: (-(r["range"] if r["range"] is not None else -1), r["paper_id"]))


def inclusion_auc(papers, ids, labelled):
    if not labelled:
        return {"value": None, "ci": None, "reason": "no SR labels (papers from a run folder)"}
    scored = [p for p in ids if papers[p]["score"] is not None]
    out = auc(
        [papers[p]["score"] for p in scored if papers[p]["label"] == "include"],
        [papers[p]["score"] for p in scored if papers[p]["label"] != "include"],
    )
    return {
        **out,
        "unscored": len(ids) - len(scored),
        "note": "SR inclusion is not study quality (weak signal)",
    }


def families(papers, ids, manifest):
    providers = {r["key"]: provider(r["model"]) for r in manifest["panel"]}
    names = sorted(set(providers.values()))
    if len(names) < 2:
        return {
            "providers": providers,
            "single_family": True,
            "families": {"single": names[0] if names else "unknown"},
            "note": SINGLE_FAMILY_NOTE,
        }
    per = {}
    for name in names:
        keys = [k for k, v in providers.items() if v == name]
        per[name] = {"reviewers": keys, **verdict_agreement(papers, ids, keys)}
    verdicts = {k: [papers[p]["reviews"][k]["verdict"] for p in ids] for k in providers}
    between = {
        f"{a}|{b}": {
            f"{x}|{y}": cohen_kappa(verdicts[x], verdicts[y])
            for x in sorted(k for k, n in providers.items() if n == a)
            for y in sorted(k for k, n in providers.items() if n == b)
        }
        for a, b in combinations(names, 2)
    }
    return {"providers": providers, "single_family": False, "families": per, "between": between}


def build_panel_metrics(manifest, review, panel_data):
    papers = panel_data["papers"]
    ids = sorted(papers)
    panel = review["panel"]
    keys = [r["key"] for r in panel]
    editor_vs_majority = rate(
        sum(
            papers[p]["editor"]["verdict"] == majority([papers[p]["reviews"][k]["verdict"] for k in keys])
            for p in ids
        ),
        len(ids),
    )
    return {
        "n": len(ids),
        "reviewers": keys,
        "text_sources": {
            s: sum(papers[p]["text_source"] == s for p in ids)
            for s in sorted({papers[p]["text_source"] for p in ids})
        },
        "verdicts": verdict_agreement(papers, ids, keys),
        "editor_vs_majority": editor_vs_majority,
        "items": item_agreement(papers, ids, panel),
        "coverage": coverage(papers, ids, panel),
        "dispersion": score_dispersion(papers, ids, keys),
        "sr_inclusion_auc": inclusion_auc(papers, ids, manifest["sample"]["labelled"]),
        "model_families": families(papers, ids, manifest),
    }


def panel_config(manifest):
    keep = (
        "kind",
        "version",
        "source",
        "topic",
        "review_sha256",
        "panel",
        "editor_model",
        "mode",
        "models",
        "prompt_version",
        "score_version",
        "fulltext_version",
        "sample",
        "config_sha256",
        "panel_sha256",
    )
    return {k: manifest[k] for k in keep if k in manifest}


def build_eval_report(eval_dir):
    """metrics.json for a panel or ablation eval folder. Sections: `panel` (+ `human` when the folder has
    human_ratings.json) for a panel eval; `ablation` for an ablation eval. Offline: no model calls."""
    from .ablation import build_ablation_metrics, load_ablation
    from .human import RATINGS_FILE, compare_human, load_ratings
    from .panel_eval import file_sha256, load_panel_eval

    eval_dir = Path(eval_dir)
    kind = json.loads((eval_dir / "manifest.json").read_text()).get("kind")
    if kind == "ablation":
        manifest, data = load_ablation(eval_dir)
        return {"kind": "ablation", "config": manifest, "ablation": build_ablation_metrics(manifest, data)}
    manifest, review, panel_data = load_panel_eval(eval_dir)
    report = {
        "kind": "panel",
        "config": panel_config(manifest),
        "panel": build_panel_metrics(manifest, review, panel_data),
    }
    ratings = eval_dir / RATINGS_FILE
    if ratings.exists():
        report["human"] = {
            "ratings_sha256": file_sha256(ratings),
            **compare_human(review, panel_data, load_ratings(ratings)),
        }
    return report


def _num(value, digits=2):
    return "n/a" if value is None else f"{value:.{digits}f}"


def _rate(r):
    return "n/a" if r is None or r["value"] is None else f"{r['k']}/{r['n']} ({100 * r['value']:.0f}%)"


def render_eval_markdown(report):
    lines = [f"# {report['kind'].title()} evaluation", ""]
    if report["kind"] == "ablation":
        a = report["ablation"]
        lines += [
            f"Papers: {a['papers']} · reviewers: {', '.join(a['reviewers'])} · cost basis: {a['cost_basis']}",
            "",
        ]
        if a["summary"] and a["summary"]["sentence"]:
            lines += [a["summary"]["sentence"], ""]
        lines += [
            "| Subset | Verdict changed | Red flags missed | Mean abs score delta | Calls |",
            "|---|---|---|---|---|",
        ]
        for r in a["subsets"]:
            lines.append(
                f"| {r['subset']} | {_rate(r['verdict_changed'])} | {_rate(r['red_flags_missed'])} | "
                f"{_num(r['mean_abs_score_delta'])} | {r['cost']['calls']} |"
            )
        return "\n".join(lines) + "\n"
    p = report["panel"]
    fleiss = p["verdicts"]["fleiss"]
    lines += [
        f"Papers: {p['n']} · reviewers: {', '.join(p['reviewers'])} · texts: {p['text_sources']}",
        "",
        "## Verdict agreement",
        "",
        (
            f"Fleiss kappa: {_num(fleiss and fleiss['kappa'])} (raw agreement "
            f"{_num(fleiss and fleiss['agreement'])}; {(fleiss and fleiss['reason']) or 'defined'})"
        ),
        "",
        "## Items (worst first)",
        "",
        "| Item | Answerers | Agreement | Unanswered | Reword? |",
        "|---|---|---|---|---|",
    ]
    for r in p["items"]:
        lines.append(
            f"| {r['text']} | {len(r['answerers'])} | {_rate(r['share'])} | {_num(r['unanswered_share'])} | "
            f"{'yes' if r['reword_candidate'] else 'no'} |"
        )
    auc = p["sr_inclusion_auc"]
    lines += [
        "",
        "## SR inclusion (inclusion is not quality)",
        "",
        f"AUC: {_num(auc['value'])} CI {auc['ci']}",
        "",
    ]
    if p["model_families"]["single_family"]:
        lines += [p["model_families"]["note"], ""]
    if "human" in report:
        h = report["human"]
        lines += ["## Human reference", "", f"Panel vs human: {_rate(h['panel']['accuracy'])}", ""]
    return "\n".join(lines) + "\n"
