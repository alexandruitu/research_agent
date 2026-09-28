"""Run Jev and the LLM screen over every gold candidate. Results live in the calls cache."""

import json
from pathlib import Path

from ..agents import PROMPT_VERSION
from ..connectors import digest
from ..criteria import screen_payload
from ..jev import JEV_SCREEN_VERSION
from ..schemas import CriteriaScreen, Screen
from .gold import gold_paper

MANIFEST = "manifest.json"


def run_screen(gold, store, evaluator, jev, progress=None, domain=None):
    """Both tiers on every candidate with an abstract (not only the escalated ones), so `report` can
    replay the cascade at any threshold pair offline. Errors propagate; the cache makes re-runs resume.
    With `domain` (a field, as a dict) both tiers screen per criterion and the field's topic is used."""
    versions, done = set(), 0
    for candidate in gold.candidates:
        if not candidate.abstract:
            continue
        paper = gold_paper(candidate, gold).model_dump()
        if domain:
            verdict = jev.screen_criteria(paper, domain)
            evaluator.ask("screen_criteria", CriteriaScreen, screen_payload(domain, paper))
        else:
            verdict = jev.screen(gold.topic, paper)
            evaluator.ask("screen", Screen, {"topic": gold.topic, "paper": paper})
        versions.add(verdict["model_version"])
        done += 1
        if progress:
            progress(done)
    return {"screened": done, "jev_model_versions": sorted(versions)}


def field_sha256(domain):
    return digest(domain) if domain else None


def check_run_dir(run_dir, gold, domain=None):
    """One run dir holds one gold set and one field: a resume is fine, anything else is refused."""
    path = Path(run_dir) / MANIFEST
    if not path.exists():
        return
    manifest = json.loads(path.read_text())
    if manifest.get("gold_sha256") != gold.content_sha256:
        raise ValueError("run dir already holds a run for a different gold set; use a new --run-dir")
    if manifest.get("field_sha256") != field_sha256(domain):
        raise ValueError("run dir already holds a run for a different field; use a new --run-dir")


def write_manifest(run_dir, *, gold_path, gold, mode, models, jev_model, screened, domain=None):
    check_run_dir(run_dir, gold, domain)
    run_dir = Path(run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    data = {
        "gold_path": str(Path(gold_path).resolve()),
        "gold_sha256": gold.content_sha256,
        "mode": mode,
        "models": models,
        "prompt_version": PROMPT_VERSION,
        "jev_screen_version": JEV_SCREEN_VERSION,
        "jev_model": jev_model,
        "field": domain,
        "field_sha256": field_sha256(domain),
        **screened,
    }
    temporary = run_dir / (MANIFEST + ".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2))
    temporary.replace(run_dir / MANIFEST)
    return data


def read_manifest(run_dir):
    path = Path(run_dir) / MANIFEST
    if not path.exists():
        raise ValueError(f"no eval run in {run_dir}; run `research-eval screen` first")
    return json.loads(path.read_text())
