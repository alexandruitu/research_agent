# Eval harness (sub-project B) — design

Date: 2026-09-25 · Status: draft for review · Branch: `feat/eval-harness` (stacked on `feat/jev-screening`)

## Context

The pipeline (M1 + Jev screening tier) has never been measured. Screening is a cascade: Jev decides
when confident, otherwise the LLM decides. Nothing says how many relevant papers it loses (recall),
where the Jev thresholds should sit, or whether reviewers A and B agree. Validation is the main open
problem, so this is built first; sub-projects A (OpenAlex/arXiv sources), C (checklist scoring) and
D (web app) are measured against it or render its outputs.

Decomposition, each with its own spec → plan → build cycle: **B eval harness** → A sources →
C checklist scoring → D web app (FastAPI + frontend, built last because it renders A–C outputs).

## Goals

1. Build reproducible gold sets from published systematic reviews (SRs).
2. Measure screening recall (with confidence intervals) for `llm_only`, `jev_only` and `cascade`.
3. Calibrate the two Jev thresholds from cached raw probabilities, at zero API cost per sweep.
4. Measure inter-reviewer agreement (Cohen's κ) and screen-vs-gold agreement.

## Non-goals

Expert-label import tooling, full-text retrieval, precision claims, new sources (A), checklist
scoring (C), web UI (D). The label format leaves room for expert labels (`label_source`), nothing more.

## What the gold set can and cannot measure

A gold file is one SR. Positives are the SR's included studies; negatives are the other records
returned by the SR's topic query. **Recall is the metric.** SR inclusion is decided on full text
against design/population/outcome criteria, while our screen asks only "is this on topic", so many
`not_included` papers are on topic and are correctly kept. Precision is therefore reported only as a
lower bound and never as a headline number. With 30–60 positives a bare recall is misleading, so every
recall carries a Wilson 95% interval.

## Architecture

New package `src/research_agent/eval/`, standalone from the LangGraph pipeline (measuring the pipeline
from inside it would couple the two and re-fetch data each run).

| Module | Responsibility |
|---|---|
| `metrics.py` | Pure functions, no I/O: Wilson interval, recall, Cohen's κ, quadratic-weighted κ, threshold sweep, recommended pair |
| `gold.py` | Gold-file schema (pydantic, `extra=forbid`), freezing, content hash, hash verification |
| `resolve.py` | Match SR-included studies to Europe PMC records |
| `screen.py` | Run Jev and the LLM screen over every gold candidate; cached in `calls` |
| `agreement.py` | Reviewers A/B on a sample; κ computations |
| `report.py` | Offline metrics from cached calls → `metrics.json`, `metrics.md` |
| `cli.py` | `research-eval` entry point |

`build_gold` and `GoldBuildError` live in `resolve.py`.

Reused, not rewritten: `Store`, `Evaluator`, `JevScreener`, `EuropePMC`, `digest`. Two small additions
to existing code:

- `JevScreener` gets a cached-only raw-probability read (no HTTP; raises on a miss).
- `Evaluator` gets an offline mode that raises `MissingCall` on a cache miss.

The offline cascade replay calls `JevScreener.decide` with the swept thresholds. The decision rule is
not reimplemented.

## Inputs and file formats

`gold/` and `evals/` are git-ignored; `sr_specs/*.yaml` are committed.

**`sr.yaml`** (hand-written, one per SR): `name`, `citation`, `topic`, `query`, `included`: list of
`{doi?, title?, year?}` (at least one of `doi` or `title`).

**`gold/<name>.json`** (generated, frozen): `version`, `name`, `citation`, `topic`, `query`,
`built_at`, `content_sha256`, `candidates[]`, `unresolved[]`, `ambiguous[]`. Each candidate:
`id`, `doi`, `title`, `abstract`, `year`, `label` (`include` | `not_included`), `label_source`
(`sr_included_list` now; `expert` later, overriding the SR label per paper), `flags[]`
(e.g. `no_abstract`), `via` (`query` | `lookup`: whether the record came from the topic query or from a
direct lookup of an SR-included study). Retrieval recall counts only `via == "query"` positives as found.
Frozen means abstracts are stored in the file; later commands never touch the
network for content.

## Commands

| Command | Behaviour | Cost |
|---|---|---|
| `research-eval build-gold sr.yaml -o gold/x.json [--max-candidates 200]` | Resolve the included list, add the query's other results as `not_included`, freeze | Europe PMC only |
| `research-eval screen gold/x.json --run-dir evals/x` | Jev and LLM screen on **every** candidate, cached; writes run manifest | N Jev + N LLM calls |
| `research-eval agreement gold/x.json --run-dir evals/x --limit 40` | Reviewers A and B on all positives with an abstract plus `--limit N` sampled negatives (default 40; fixed seed 0, recorded); reads mode and models from the run manifest, so it takes no `--mode` | 2 calls/paper |
| `research-eval report evals/x [--holdout evals/other] [--target-recall 0.98] [--allow-mixed-jev-versions]` | Offline; reads cached calls only | free |

Running the LLM screen on every candidate (not only escalated ones) is what lets `report` replay the
cascade at any threshold pair without new calls.

## Metrics (`report`)

A paper is **kept** unless its decision is `exclude`; `uncertain` and `escalate` count as kept,
matching the pipeline.

1. **Retrieval recall** = SR-included studies found by our search ÷ all SR-included studies.
   Unresolved and ambiguous studies count as misses.
2. **Screening recall** per strategy (`llm_only`, `jev_only`, `cascade`) = kept positives ÷ resolved
   positives that have an abstract, with Wilson 95% interval. `no_abstract` positives are reported
   separately.
3. **Missed positives**: every SR-included paper a strategy dropped, with title, Jev p, deciding tier.
4. **Workload**: shares auto-included / auto-excluded / escalated; LLM screen calls saved vs
   `llm_only` = candidates not escalated.
5. **Threshold sweep**: `min_confidence` ∈ {0.1 … 0.9 step 0.1} × `exclude_min_confidence` ∈
   {0.5, 0.6, 0.7, 0.8, 0.9, 0.95, 0.99}, keeping pairs with exclude ≥ include. Per pair: recall,
   missed count, calls saved. **Recommended pair** = most calls saved with point-estimate recall ≥
   target (default 0.98); ties → fewer missed, then stricter exclude threshold. If no pair meets the
   target the report says so; it never picks the "least bad" pair silently.
6. **Overfitting guard**: the sweep tunes on the papers it scores. `--holdout evals/other` takes the **run directory**
   of a second, already-screened SR and applies the chosen pair to it. Without a holdout the report states the thresholds are untested on held-out data.
7. **Agreement** (from `agreement`): Cohen's κ reviewer A vs B on verdict (include/uncertain/exclude);
   quadratic-weighted κ on each 0–4 score; κ of the LLM screen (include+uncertain → kept) vs SR label;
   adjudication rate. Raw % agreement and class prevalence sit next to every κ. Reviewers from the same
   provider (prefix before `:` in the model id) set `same_family: true`, because same-family κ
   overstates independence.

## Error handling (fail closed, as in the pipeline)

- **build-gold**: unresolved → `unresolved[]`, not fatal. Ambiguous match (same title, different DOI)
  → `ambiguous[]`, never guessed. Zero resolved positives → error. Europe PMC failures use the
  existing retry, then stop.
- **Integrity**: `screen` and `report` verify `content_sha256`; an edited gold file is an error.
- **screen**: a Jev or LLM error stops the run; the cache makes a re-run resume. `manifest.json`
  records gold hash, models, prompt version, Jev `model_version`s.
- **report**: missing cached calls → error with the count and the command to run; mixed Jev
  `model_version`s → error unless `--allow-mixed-jev-versions`; zero denominator → `None` plus a
  reason (never a fake 100% or a divide error); single-class κ → `None` plus a reason.
- **Diagnostics**: exception type and message written to `errors.log` in the run dir (fixes the CLI
  hiding the real error). API keys are never logged.

## Testing

All offline; the suite needs no network and no keys.

- `metrics`: Wilson known values (40/40 → lower bound ≈ 0.91); zero denominator; textbook 2×2 κ;
  weighted κ; single-class κ; recall never drops when the exclude threshold rises; exclude ≥ include
  constraint; recommended-pair selection including "no pair meets target".
- `gold`: mocked Europe PMC for DOI match, title+year match, ambiguous, unresolved, no-abstract; hash
  tamper detection.
- `screen`: fake Jev and LLM; second run makes zero calls; an error mid-run leaves the cache usable.
- **Consistency test**: run the real graph screening node on candidates, replay the same candidates
  through `report` at the same thresholds, assert identical decisions.
- CLI smoke: the four commands on a tiny synthetic gold with the demo evaluator and mock Jev.
- Optional live smoke: marked, skipped when keys are absent, outside the normal suite.

## Success criteria

Suite green, `ruff check` clean, and one real run on one or two open SRs produces `metrics.md` with
recall and interval, the missed-positives list and a threshold sweep. The numbers may be unflattering;
the report exists to show that.

## Open items (decided for now, revisit if wrong)

- Default `--max-candidates 200` (one Europe PMC page). SRs whose topic query returns far more may need
  paging; not built until a real SR needs it.
- Which SRs to use is chosen after this spec is approved (candidates proposed from open-access
  AI/CT-FFR-type reviews with a public included-studies table).
