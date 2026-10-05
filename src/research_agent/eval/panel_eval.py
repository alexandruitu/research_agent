"""research-eval panel: run full text + the review panel + editor on a sample of papers, cached.

The eval folder holds manifest.json (frozen config), review.json (copy), research.sqlite (calls + raw text)
and panel.json (per-paper results). Errors propagate (fail closed); the cache makes a re-run resume."""

import hashlib
import json
import random
from pathlib import Path

from ..agents import PROMPT_VERSION
from ..connectors import digest
from ..fulltext import FULLTEXT_VERSION
from ..graph import editor_payload, reviewer_payload
from ..schemas import EditorDecision, PanelReview, read_review
from ..scoring import SCORE_VERSION, score_paper
from .gold import gold_paper

MANIFEST = "manifest.json"
PANEL_FILE = "panel.json"
PANEL_EVAL_VERSION = "panel-eval-1"


def sample_papers(papers, n, seed):
    """`papers`: [{"id", "label" ("include"/"not_included"/None), "year", "source"}]. SR-included papers
    first (up to n // 2, a seeded sample when there are more), then one excluded paper per chosen included
    paper matched on (year, source), else year, else any; remaining slots are a seeded sample of the rest.
    Unlabelled papers (a run folder) are a plain seeded sample. Deterministic for a given seed."""
    if n < 1:
        raise ValueError("sample size must be >= 1")
    rng = random.Random(seed)
    papers = sorted(papers, key=lambda p: p["id"])
    positives = [p for p in papers if p["label"] == "include"]
    pool = [p for p in papers if p["label"] != "include"]
    take = min(len(positives), n // 2) if pool else min(len(positives), n)
    chosen = rng.sample(positives, take) if take < len(positives) else positives
    chosen = sorted(chosen, key=lambda p: p["id"])
    negatives = []
    for positive in chosen:
        if len(chosen) + len(negatives) >= n or not pool:
            break
        for match in (
            lambda q, p=positive: q["year"] == p["year"] and q["source"] == p["source"],
            lambda q, p=positive: q["year"] == p["year"],
            lambda q: True,
        ):
            options = [q for q in pool if match(q)]
            if options:
                pick = rng.choice(options)
                negatives.append(pick)
                pool.remove(pick)
                break
    rest = n - len(chosen) - len(negatives)
    if rest > 0 and pool:
        negatives += rng.sample(pool, min(rest, len(pool)))
    return [p["id"] for p in chosen] + [p["id"] for p in negatives]


def file_sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def gold_source(gold):
    """Papers (pipeline-shaped dicts) and sampling rows of a gold set; only candidates with an abstract."""
    papers, rows = {}, []
    for c in gold.candidates:
        if not c.abstract:
            continue
        papers[c.id] = gold_paper(c, gold).model_dump()
        rows.append({"id": c.id, "label": c.label, "year": c.year, "source": c.via})
    return gold.topic, papers, rows


def run_source(run_dir):
    """Papers of a finished run (report.json state); no SR labels, so AUC is not computed for it."""
    state = json.loads((Path(run_dir) / "report.json").read_text())["state"]
    papers = {p["id"]: p for p in state["papers"] if p.get("abstract")}
    rows = [
        {"id": pid, "label": None, "year": p.get("year", ""), "source": (p.get("sources") or [""])[0]}
        for pid, p in papers.items()
    ]
    return state["contract"]["topic"], papers, rows


def config_sha256(manifest):
    """Identity of an eval folder: everything that changes results (not the output paths)."""
    keys = ("source", "review_sha256", "mode", "models", "prompt_version", "sample")
    return digest({k: manifest[k] for k in keys})


def check_eval_dir(eval_dir, manifest):
    """One eval folder holds one frozen config: a resume is fine, anything else is refused."""
    path = Path(eval_dir) / MANIFEST
    if not path.exists():
        return
    old = json.loads(path.read_text())
    if old.get("kind") != "panel" or old.get("config_sha256") != manifest["config_sha256"]:
        raise ValueError("eval dir already holds a different evaluation; use a new --eval-dir")


def run_panel_eval(
    eval_dir, *, topic, papers, rows, labels, source, review, review_path, evaluator, fulltext, n, seed, mode
):
    """Sample, then full text -> every reviewer -> editor on each sampled paper, then score in code.
    `review` is the validated review.json dict, `labels` {paper id: label or None}. Returns panel.json."""
    eval_dir = Path(eval_dir)
    ids = sample_papers(rows, n, seed)
    panel = review["panel"]
    manifest = {
        "kind": "panel",
        "version": PANEL_EVAL_VERSION,
        "source": source,
        "topic": topic,
        "review_sha256": file_sha256(review_path),
        "panel": [
            {
                "key": r["key"],
                "name": r["name"],
                "version": r["version"],
                "model": evaluator.model_for(f"review:{r['key']}"),
            }
            for r in panel
        ],
        "editor_model": evaluator.model_for("editor"),
        "mode": mode,
        "models": evaluator.models,
        "prompt_version": PROMPT_VERSION,
        "score_version": SCORE_VERSION,
        "fulltext_version": FULLTEXT_VERSION,
        "sample": {
            "n": n,
            "seed": seed,
            "ids": ids,
            "positives": sum(labels.get(i) == "include" for i in ids),
            "labelled": any(labels.get(i) is not None for i in ids),
        },
    }
    manifest["config_sha256"] = config_sha256(manifest)
    check_eval_dir(eval_dir, manifest)  # before any call
    eval_dir.mkdir(parents=True, exist_ok=True)
    (eval_dir / "review.json").write_bytes(Path(review_path).read_bytes())
    _write_manifest(eval_dir, {**manifest, "panel_sha256": None})  # claims the folder for this config
    results = {}
    for pid in ids:
        paper = papers[pid]
        text = fulltext.resolve(paper)
        content = text.pop("content")
        text["sha256"] = evaluator.store.raw({"fulltext": content})
        reviews = {
            r["key"]: evaluator.ask(
                f"review:{r['key']}",
                PanelReview,
                reviewer_payload(topic, paper, text["text_source"], content, r),
            ).model_dump()
            for r in panel
        }
        payload = editor_payload(
            topic, paper, text["text_source"], panel, reviews, review["editor"]["instructions"]
        )
        decision = evaluator.ask("editor", EditorDecision, payload).model_dump()
        scored = score_paper(panel, reviews)
        results[pid] = {
            "label": labels.get(pid),
            "year": paper.get("year", ""),
            "title": paper["title"],
            "text_source": text["text_source"],
            "text_sha256": text["sha256"],
            "chars": len(content),
            "reviews": {
                key: {
                    **reviews[key],
                    "score": scored["reviewers"][key]["score"],
                    "coverage": scored["reviewers"][key]["coverage"],
                }
                for key in reviews
            },
            "editor": decision,
            "score": scored["score"],
            "coverage": scored["coverage"],
            "red_flags": scored["red_flags"],
        }
    data = {"papers": results}
    (eval_dir / PANEL_FILE).write_text(json.dumps(data, ensure_ascii=False, indent=2))
    _write_manifest(eval_dir, {**manifest, "panel_sha256": file_sha256(eval_dir / PANEL_FILE)})
    return data


def _write_manifest(eval_dir, manifest):
    temporary = eval_dir / (MANIFEST + ".tmp")
    temporary.write_text(json.dumps(manifest, ensure_ascii=False, indent=2))
    temporary.replace(eval_dir / MANIFEST)


def load_panel_eval(eval_dir):
    """(manifest, review dict, panel.json dict) of a finished panel eval; refuses an edited panel.json."""
    eval_dir = Path(eval_dir)
    path = eval_dir / MANIFEST
    if not path.exists():
        raise ValueError(f"no eval in {eval_dir}")
    manifest = json.loads(path.read_text())
    if manifest.get("kind") != "panel":
        raise ValueError(f"{eval_dir} is not a panel eval")
    if not manifest.get("panel_sha256"):
        raise ValueError(f"the panel eval in {eval_dir} did not finish; re-run it to resume from the cache")
    if file_sha256(eval_dir / PANEL_FILE) != manifest["panel_sha256"]:
        raise ValueError("panel.json changed after the eval was written")
    review = read_review(eval_dir / "review.json").model_dump()  # defaults (weights) filled in
    return manifest, review, json.loads((eval_dir / PANEL_FILE).read_text())
