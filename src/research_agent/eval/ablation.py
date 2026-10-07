"""research-eval ablation: every reviewer subset of a finished panel eval, scored in code.

Offline by default: it reads the panel eval's panel.json and its research.sqlite (for cost). With
`rerun_editor` the editor is asked once per paper for every proper subset (cached in the ablation folder's
own research.sqlite). Cost is counted from cached call metadata: calls, and characters of prompt + output
as a token proxy, because the calls table does not store provider token usage (see the plan's decisions)."""

import json
import sqlite3
from itertools import combinations
from pathlib import Path

from ..agents import PROMPT_VERSION
from ..graph import editor_payload
from ..schemas import EditorDecision
from ..scoring import score_paper
from .metrics import compare_to_full, majority, rate
from .panel_eval import MANIFEST, file_sha256, load_panel_eval

ABLATION_FILE = "ablation.json"
ABLATION_VERSION = "ablation-1"


def subset_name(keys):
    return "+".join(keys)


def reviewer_subsets(keys):
    """Every non-empty subset, by size then panel order: [(a,), (b,), ..., (a, b), ..., (a, b, c)]."""
    return [combo for size in range(1, len(keys) + 1) for combo in combinations(keys, size)]


def call_costs(store_path):
    """{(role, paper id): {"calls", "chars"}} from a research.sqlite calls table (prompt + output chars)."""
    out = {}
    if not Path(store_path).exists():
        return out
    db = sqlite3.connect(store_path)
    try:
        rows = db.execute("SELECT role, input, output FROM calls").fetchall()
    finally:
        db.close()
    for role, inputs, output in rows:
        paper = json.loads(inputs).get("payload", {}).get("paper", {}).get("id")
        cost = out.setdefault((role, paper), {"calls": 0, "chars": 0})
        cost["calls"] += 1
        cost["chars"] += len(inputs) + len(output)
    return out


def flag_keys(flags):
    return sorted(
        f.get("source") or f.get("item_text") or f["text"] for f in flags
    )  # the item, stable across wordings


def run_ablation(panel_dir, out_dir, *, rerun_editor=False, evaluator=None, mode="demo"):
    """Writes ablation.json and manifest.json into `out_dir`; returns ablation.json's dict."""
    manifest, review, panel_data = load_panel_eval(panel_dir)
    if rerun_editor and evaluator is None:
        raise ValueError("--rerun-editor needs an evaluator")
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    panel = review["panel"]
    keys = [r["key"] for r in panel]
    papers = panel_data["papers"]
    costs = call_costs(Path(panel_dir) / "research.sqlite")
    subsets = {}
    for combo in reviewer_subsets(keys):
        members = [r for r in panel if r["key"] in combo]
        full = len(combo) == len(keys)
        rows = {}
        for pid, paper in papers.items():
            reviews = {k: paper["reviews"][k] for k in combo}
            scored = score_paper(members, reviews)
            editor = None
            if full:
                editor = paper["editor"]["verdict"]
            elif rerun_editor:
                payload = editor_payload(
                    manifest["topic"],
                    {"id": pid, "title": paper["title"], "year": paper["year"]},
                    paper["text_source"],
                    members,
                    reviews,
                    review["editor"]["instructions"],
                )
                editor = evaluator.ask("editor", EditorDecision, payload).model_dump()["verdict"]
            # A deployed panel of this size runs one editor call per paper; outside the full panel its
            # size is estimated from the full panel's cached editor call (flagged).
            editor_cost = costs.get(("editor", pid), {"calls": 1, "chars": 0})
            estimated = not full
            reviewer_cost = [costs.get((f"review:{k}", pid), {"calls": 0, "chars": 0}) for k in combo]
            rows[pid] = {
                "score": scored["score"],
                "verdict": majority([reviews[k]["verdict"] for k in combo]),
                "flags": flag_keys(scored["red_flags"]),
                "editor": editor,
                "cost": {
                    "calls": sum(c["calls"] for c in reviewer_cost) + editor_cost["calls"],
                    "chars": sum(c["chars"] for c in reviewer_cost) + editor_cost["chars"],
                    "editor_estimated": estimated,
                },
            }
        subsets[subset_name(combo)] = {"reviewers": list(combo), "size": len(combo), "papers": rows}
    data = {"full": subset_name(keys), "subsets": subsets}
    (out_dir / ABLATION_FILE).write_text(json.dumps(data, ensure_ascii=False, indent=2))
    ablation_manifest = {
        "kind": "ablation",
        "version": ABLATION_VERSION,
        "panel_dir": str(Path(panel_dir).resolve()),
        "panel_config_sha256": manifest["config_sha256"],
        "panel_sha256": manifest["panel_sha256"],
        "reviewers": keys,
        "rerun_editor": rerun_editor,
        "mode": mode if rerun_editor else None,
        "editor_model": evaluator.model_for("editor") if rerun_editor else None,
        "prompt_version": PROMPT_VERSION,
        "cost_basis": "chars",  # prompt + output characters; provider token usage is not cached
        "ablation_sha256": file_sha256(out_dir / ABLATION_FILE),
    }
    (out_dir / MANIFEST).write_text(json.dumps(ablation_manifest, ensure_ascii=False, indent=2))
    return data


def load_ablation(out_dir):
    out_dir = Path(out_dir)
    manifest = json.loads((out_dir / MANIFEST).read_text())
    if manifest.get("kind") != "ablation":
        raise ValueError(f"{out_dir} is not an ablation eval")
    if file_sha256(out_dir / ABLATION_FILE) != manifest["ablation_sha256"]:
        raise ValueError("ablation.json changed after the eval was written")
    return manifest, json.loads((out_dir / ABLATION_FILE).read_text())


def _as_sets(rows):
    return {pid: {**r, "flags": set(r["flags"])} for pid, r in rows.items()}


def _mean(values):
    values = [v for v in values if v is not None]
    return sum(values) / len(values) if values else None


def build_ablation_metrics(manifest, data):
    """Each subset vs the full panel, means per subset size, and the "last reviewer" summary."""
    full = _as_sets(data["subsets"][data["full"]]["papers"])
    n = len(manifest["reviewers"])
    rows = []
    for name, subset in data["subsets"].items():
        cmp = compare_to_full(full, _as_sets(subset["papers"]))
        rows.append({"subset": name, "reviewers": subset["reviewers"], "size": subset["size"], **cmp})
    sizes = {}
    for k in range(1, n + 1):
        chosen = [r for r in rows if r["size"] == k]
        sizes[str(k)] = {
            "subsets": len(chosen),
            "verdict_changed": _mean([r["verdict_changed"]["value"] for r in chosen]),
            "red_flags_missed": _mean([r["red_flags_missed"]["value"] for r in chosen]),
            "mean_abs_score_delta": _mean([r["mean_abs_score_delta"] for r in chosen]),
            "cost_calls": _mean([r["cost"]["calls"] for r in chosen]),
            "cost_chars": _mean([r["cost"]["chars"] for r in chosen]),
        }
    summary = None
    if n >= 2:
        before = [r for r in rows if r["size"] == n - 1]
        full_cost = rows[-1]["cost"]["chars"]
        added_flags = _mean(
            [
                sum(
                    len(full[p]["flags"] - set(data["subsets"][r["subset"]]["papers"][p]["flags"]))
                    for p in full
                )
                for r in before
            ]
        )
        changed = _mean([r["verdict_changed"]["value"] for r in before])
        increase = _mean(
            [
                (full_cost - r["cost"]["chars"]) / r["cost"]["chars"] if r["cost"]["chars"] else None
                for r in before
            ]
        )
        summary = {
            "from_size": n - 1,
            "to_size": n,
            "verdict_changed": changed,
            "red_flags_added": added_flags,
            "cost_increase": increase,
            "sentence": (
                f"Going from {n - 1} to {n} reviewers changed the majority verdict on "
                f"{_pct(changed)} of papers and added {added_flags:.1f} red flags on average; "
                f"cost +{_pct(increase)} (prompt + output characters)."
            )
            if changed is not None and added_flags is not None
            else None,
        }
    return {
        "papers": len(full),
        "reviewers": manifest["reviewers"],
        "rerun_editor": manifest["rerun_editor"],
        "cost_basis": manifest["cost_basis"],
        "token_usage": None,  # not cached by the Evaluator; chars are the proxy
        "subsets": rows,
        "sizes": sizes,
        "summary": summary,
        "full_editor_vs_majority": rate(
            sum(r["editor"] == r["verdict"] for r in full.values() if r["editor"]),
            sum(1 for r in full.values() if r["editor"]),
        ),
    }


def _pct(value):
    return "n/a" if value is None else f"{100 * value:.0f}%"
