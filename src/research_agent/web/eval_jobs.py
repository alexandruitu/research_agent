"""The worker side of eval jobs: `research-eval` steps per kind, the human-ratings export, gold building.

Payloads are built by the API (`web.evals`); paths are re-checked here against the configured roots."""

import json
import shutil
import tempfile
from pathlib import Path

import yaml
from sqlalchemy import select

from ..connectors import EuropePMC
from ..eval.gold import SRSpec, write_gold
from ..eval.human import RATINGS_FILE
from ..eval.resolve import build_gold
from ..storage import Store
from .db.models import EvalReport, GoldSet, HumanRatingRow, RatingSample

FIELD_REQUEST = "field.request.json"
REVIEW_REQUEST = "review.request.json"
COPY_IGNORE = shutil.ignore_patterns("metrics.json", "metrics.md", "errors.log", "worker.log", "*.tmp")


def inside(path, root):
    path = Path(path).resolve()
    if not path.is_relative_to(Path(root).resolve()):
        raise ValueError("a path of this eval is outside the configured directories")
    return path


def ratings_document(db, folder):
    """human_ratings.json (eval contract, schema 1) with every rating of every sample of `folder`."""
    samples = [s.id for s in db.scalars(select(RatingSample).where(RatingSample.folder == str(folder)))]
    rows = db.scalars(
        select(HumanRatingRow)
        .where(HumanRatingRow.sample_id.in_(samples))
        .order_by(
            HumanRatingRow.paper_id, HumanRatingRow.reviewer, HumanRatingRow.item, HumanRatingRow.rater_id
        )
    )
    return {
        "schema": 1,
        "ratings": [
            {
                "paper_id": r.paper_id,
                "reviewer": r.reviewer,
                "reviewer_version": r.reviewer_version,
                "item": r.item,
                "item_text": r.item_text,
                "rater": str(r.rater_id),
                "answer": r.answer,
                "quote": r.quote or "",
            }
            for r in rows
        ],
    }


def eval_steps(settings, payload, db):
    """(eval folder, [argv per research-eval step], import options) for an `eval_run` payload."""
    kind, mode = payload["kind"], payload.get("mode", "live")
    folder = inside(settings.evals_dir / payload["folder"], settings.evals_dir)
    if kind != "human":  # a human eval folder is a copy of its panel folder, made below
        folder.mkdir(parents=True, exist_ok=True)
    options = {"kind": kind, "parent_id": None, "extra_config": None}
    if kind == "screening":
        gold = inside(payload["gold_path"], settings.gold_dir)
        argv = ["screen", str(gold), "--run-dir", str(folder), "--mode", mode]
        if payload.get("domain"):
            request = folder / FIELD_REQUEST
            request.write_text(json.dumps(payload["domain"], ensure_ascii=False, indent=2))
            argv += ["--field", str(request)]
        return folder, [argv, ["report", str(folder)]], options
    if kind == "panel":
        request = folder / REVIEW_REQUEST
        request.write_text(json.dumps(payload["review"], ensure_ascii=False, indent=2))
        if payload.get("gold_path"):
            source = ["--gold", str(inside(payload["gold_path"], settings.gold_dir))]
        else:
            source = ["--run", str(inside(payload["run_dir"], settings.runs_dir))]
        argv = ["panel", *source, "--review", str(request), "--eval-dir", str(folder)]
        argv += ["--sample", str(int(payload["sample"])), "--seed", str(int(payload["seed"])), "--mode", mode]
        return folder, [argv, ["report", str(folder)]], options
    if kind == "ablation":
        panel = inside(payload["panel_dir"], settings.evals_dir)
        argv = ["ablation", str(panel), "--eval-dir", str(folder)]
        if payload.get("rerun_editor"):
            argv += ["--rerun-editor", "--mode", mode]
        options["parent_id"] = payload.get("parent_id")
        return folder, [argv, ["report", str(folder)]], options
    if kind == "human":
        sample = db.get(RatingSample, payload["rating_sample_id"])
        if sample is None:
            raise ValueError("the rating sample no longer exists")
        panel = inside(sample.folder, settings.evals_dir)
        document = json.dumps(ratings_document(db, panel), ensure_ascii=False, indent=2)
        (panel / RATINGS_FILE).write_text(document)  # the contract's place for them
        if not folder.exists():
            shutil.copytree(
                panel, folder, ignore=COPY_IGNORE
            )  # a new immutable report; the panel is untouched
        (folder / RATINGS_FILE).write_text(document)
        options["parent_id"] = str(sample.eval_report_id)
        options["extra_config"] = {"rating_sample_id": str(sample.id)}
        return folder, [["human", str(folder)], ["report", str(folder)]], options
    raise ValueError(f"unknown eval kind {kind!r}")


def parent_report_id(db, value):
    import uuid

    if not value:
        return None
    report = db.get(EvalReport, uuid.UUID(str(value)))
    return report.id if report else None


def build_gold_set(settings, payload, *, http_client=None, created_by=None, db=None):
    """Resolve the SR's included studies against Europe PMC and freeze the gold file in the gold directory.
    Public API only (no key). Returns the GoldSet row (added to `db`) and a short result."""
    spec = SRSpec.model_validate(payload["spec"])
    if db.scalar(select(GoldSet).where(GoldSet.name == spec.name)) is not None:
        raise ValueError(f"a gold set named {spec.name!r} already exists")
    target = inside(settings.gold_dir / f"{spec.name}.json", settings.gold_dir)
    if target.exists():
        raise ValueError(f"a gold file named {spec.name!r} already exists")
    with tempfile.TemporaryDirectory() as scratch:  # raw Europe PMC payloads are not kept
        connector = EuropePMC(Store(scratch), client=http_client)
        gold = build_gold(spec, connector, int(payload.get("max_candidates") or 200))
    gold = write_gold(gold, target)
    (target.with_suffix(".sr.yaml")).write_text(yaml.safe_dump(spec.model_dump(), sort_keys=False))
    positives = sum(c.label == "include" for c in gold.candidates)
    row = GoldSet(
        name=gold.name,
        citation=gold.citation,
        sha256=gold.content_sha256,
        path=str(target),
        candidates=len(gold.candidates),
        positives=positives,
        unresolved=len(gold.unresolved) + len(gold.ambiguous),
        source=payload["spec"] | {"sr_reference": payload.get("sr_reference")},
        created_by=created_by,
    )
    db.add(row)
    db.flush()
    return row, {
        "gold_set_id": str(row.id),
        "name": gold.name,
        "candidates": len(gold.candidates),
        "positives": positives,
        "unresolved": len(gold.unresolved),
        "ambiguous": len(gold.ambiguous),
    }
