# Slice 6 · Plan 2: Live evals backend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Run evaluations (screening, panel, ablation, human) as worker jobs, build gold sets from an SR spec,
compare/estimate reports, collect blind human reference ratings, and add Google Gemini as a second provider.

**Architecture:** The worker gains `eval_run` and `gold_build` jobs. `eval_run` runs `research-eval`
subcommands in a child process (same `child_environment()` as research runs, so keys never reach the API),
then imports the eval folder as a new immutable `eval_reports` row (kind + frozen config). Gold sets are built
in-process (public Europe PMC only, no keys). Ratings live in PostgreSQL; the `human` job exports them in the
contract's `human_ratings.json` format into the panel folder and into a copy of it, recomputes metrics there
and imports that copy as a new `human` report. Gemini works through `init_chat_model("google_genai:...")` with
the same `with_structured_output(method="json_schema")` path as Anthropic.

**Tech Stack:** FastAPI, SQLAlchemy 2 + Alembic (PostgreSQL), pytest with pgserver, langchain-google-genai 4.x.

Spec: `docs/superpowers/specs/2026-10-05-live-evals-design.md`. Eval contract: `docs/superpowers/plans/2026-10-05-slice6-1-eval.md`
("Contract for Plan 2"). Testing rule (user): only the test files touched by a task plus `ruff check .`; no full suite.

## Decisions (made without asking, per the user)

1. **Gemini structured output**: `langchain-google-genai` 4.x defaults `with_structured_output` to
   `method="json_schema"` (native response schema) and parses with `PydanticOutputParser`, which raises
   `OutputParserException` — the existing retry loop covers it. No per-provider branch in `agents.py`; only a test
   (fake chat model, no network) that `google_genai:*` ids go through `json_schema` and retries. `max_tokens`,
   `timeout`, `max_retries` are accepted aliases on `ChatGoogleGenerativeAI`. Key: `GOOGLE_API_KEY` (read by the library).
2. **Model ids**: `google_genai:gemini-2.5-pro`, `google_genai:gemini-2.5-flash`, `google_genai:gemini-3.1-pro-preview`
   (curated, listed by `/models/available` when the Google key was accepted). Family = prefix before `:`
   (`eval.panel_report.provider`), so two providers on the panel give the model-family split automatically.
3. **Key check for unused providers**: providers whose key is present but no role uses them get a
   `worker_status` row with role `key:<provider>` (model null), so `/models/available` can know Gemini is usable.
4. **Child process per eval step** (`python -m research_agent.eval.cli ...`), like research runs; the worker's
   `spawn_eval` seam is replaced in tests by an in-process call to `eval.cli.main(argv, dotenv=False)` (demo mode).
5. **Gold-set builder runs in-process** in the worker (no provider key involved), using the worker's
   `http_client` seam for Europe PMC. Input: a list of DOIs (and/or titles). An SR DOI/PMID is recorded as the
   citation reference only — resolving an SR's *included* list automatically needs full-text reference parsing and
   is out of scope (deviation, documented).
6. **Human reports never mutate an old report**: each `human` job copies the panel folder to a new folder
   `<panel>-human-<hex>` and imports it as a new report (kind `human`, parent = panel report). The ratings file is
   also written into the original panel folder (contract), by the worker (the API may run with a read-only evals volume).
   At most one queued human job per rating sample (later submissions ride on it).
7. **Rating flow**: a rater submits all items of all panel reviewers for one paper at once; reviewer version and
   item text come from the panel's frozen `review.json` (never from the client). Resubmitting is 409.
   Rater id in `human_ratings.json` = the user's UUID (no emails in files).
8. **Stratified sample**: papers sorted by panel score (unscored last), cut into `size` equal bins, one seeded pick
   per bin; `size >= papers` takes all.
9. **Estimate**: calls counted from inputs (no cache lookup, so it is an upper bound); chars from the source
   abstracts (or `fulltext.max_chars` when full-text sources are configured) plus prompt overhead; tokens = chars/4;
   cost from a small price table (USD per 1M tokens), `null` for unknown models.
10. **List**: `GET /evals` returns finished reports only (ids stay non-null for the existing frontend); `GET /evals/jobs` lists queued/running/failed `eval_run` jobs. The Reviewers stage keeps its title "Reviewers A and B" (the frontend e2e names it; Plan 3 may rename it).
11. **Compare**: 2–3 reports of one family (`screening`; `panel`+`human`; `ablation`), aligned metric rows and config rows.
12. **System map**: stage entries may list `alternatives`; the Reviewers stage reads the newest panel/human report's
    Fleiss kappa first (caveat "one model family" when `panel.model_families.single_family`), else the legacy A/B kappa.

## File map

- Modify `pyproject.toml` (live extra), `src/research_agent/web/checks.py` (google provider, `key:` rows),
  `src/research_agent/web/review.py` (curated Gemini models), `deploy/worker.env.example`, docs.
- Create migration `src/research_agent/web/db/migrations/versions/0007_live_evals.py`; modify `db/models.py`
  (EvalReport: kind, config, parent_id, rating_sample_id, nullable gold_set_id; GoldSet: path, counts, source,
  created_by; new RatingSample, HumanRatingRow).
- Create `src/research_agent/web/evals.py` (eval inputs → job payload, estimate, headline, compare, sampling,
  ratings export) and `src/research_agent/web/api/routers/ratings.py`, `routers/gold_sets.py`; modify
  `routers/evals.py`, `routers/stages.py`, `stages.py`, `stages.yaml`, `api/schemas.py`, `api/app.py`.
- Modify `src/research_agent/web/worker.py` (`eval_run`, `gold_build`), `runner.py` (`eval_command`, `spawn_command`),
  `importer/evals.py` (panel/ablation/human folders).
- Tests: `tests/test_agents_gemini.py`, `tests/test_web_checks.py` (keys), `tests/test_web_review_settings.py`,
  `tests/test_web_migration_evals.py`, `tests/test_web_eval_import_panel.py`, `tests/test_web_eval_jobs.py`,
  `tests/test_web_gold_sets.py`, `tests/test_web_evals_api.py`, `tests/test_web_ratings.py`,
  `tests/test_web_stages.py`, `tests/test_web_guards.py`.

## Tasks

### Task 1: Gemini provider
- [ ] Test (`tests/test_agents_gemini.py`): monkeypatch `langchain.chat_models.init_chat_model` with a fake whose
  `with_structured_output(schema, method)` records `method` and whose `invoke` returns a bad then a good
  `PanelReview`; `Evaluator(store,"live",{"review:m": "google_genai:gemini-2.5-flash", ...}).ask(...)` returns the good
  one after a retry and records `method == "json_schema"` and the model id. Second test: a real
  `ChatGoogleGenerativeAI(model="gemini-2.5-flash", google_api_key="test-not-a-key")` builds
  `with_structured_output(PanelReview, method="json_schema")` without network.
- [ ] Add `langchain-google-genai>=4,<5` to the `live` extra (the worker image installs `.[web,live]`).
- [ ] Commit.

### Task 2: Google key check + curated models + redaction sentinel
- [ ] Tests in `tests/test_web_checks.py`: `check_keys({"RESEARCH_MODEL": "anthropic:x", "ANTHROPIC_API_KEY": k,
  "GOOGLE_API_KEY": g}, mock)` → rows include `{"role":"key:google_genai","provider":"google_genai","key_accepted":True}`;
  the mock asserts URL `https://generativelanguage.googleapis.com/v1beta/models` and header `x-goog-api-key`;
  403 → rejected; a role model `google_genai:gemini-2.5-pro` checks the Google key. Sentinel: `redact()` hides a
  `GOOGLE_API_KEY` value. In `tests/test_web_review_settings.py`: with an accepted `key:google_genai` row,
  `/models/available` lists the 3 curated ids, available, provider `google_genai`.
- [ ] Implement `PROVIDERS["google_genai"]`, `key:` rows, `CURATED_MODELS` in `review.py`.
- [ ] `deploy/worker.env.example`: `GOOGLE_API_KEY=`. Commit.

### Task 3: Migration 0007 + models
- [ ] Test `tests/test_web_migration_evals.py`: columns exist; old eval report rows get kind `screening`.
- [ ] Implement migration and models. Commit.

### Task 4: Importer for panel / ablation / human folders
- [ ] Test: build a demo panel folder via `eval.cli.main` (as in `test_eval_panel_cli.py`), run `report`,
  `import_eval_run(db, folder)` → EvalReport kind `panel`, `config` = metrics config, gold set linked when the source
  is a gold file, metrics == metrics.json; ablation folder → kind `ablation`, parent = panel report; re-import of an
  unchanged folder → `unchanged`; the old screening import still works (existing `tests/test_web_import_eval.py`).
- [ ] Implement dispatch on `manifest.kind`. Commit.

### Task 5: Worker `eval_run` + `gold_build`
- [ ] Tests (`tests/test_web_eval_jobs.py`): fake `spawn_eval` running `eval.cli.main` in-process; panel job (demo,
  gold set) → report kind panel, job progress `{status, step, steps, done, total, result:{eval_id}}`; ablation job;
  failing step → job failed with `errors.log`-free sanitized message; `gold_build` with mocked Europe PMC → gold file
  in gold dir + GoldSet row with counts.
- [ ] Implement `runner.eval_command`, `runner.spawn_command`, `Worker._eval_run`, `Worker._gold_build`. Commit.

### Task 6: Evals API (create, list, detail, compare, estimate) + gold sets API
- [ ] Tests (`tests/test_web_evals_api.py`, `tests/test_web_gold_sets.py`): validation errors (unknown gold set 404,
  demo disabled 422, ablation of a non-panel 422, compare with 1 or 4 ids 422, mixed families 422), 202 JobOut,
  list with headline/chips per kind, estimate numbers for a toy panel.
- [ ] Implement `web/evals.py` + routers. Commit.

### Task 7: Rating samples (blind)
- [ ] Tests (`tests/test_web_ratings.py`): admin creates a sample (stratified, seeded, deterministic); member `next`
  returns text + items and no model answers (sentinel quote absent from every response before submit); submit
  validates full coverage, 409 on repeat; reveal 409 before submit, then mine vs model; a human job is enqueued once;
  running the worker produces a `human` report whose metrics have `human.units > 0`.
- [ ] Implement router + worker human step. Commit.

### Task 8: System map + guards + schema
- [ ] Tests: stages with a panel report (single family → caveat, two families → measured); guard matrix rows for
  every new route; secrets sentinel over the new GET routes with `GOOGLE_API_KEY` set.
- [ ] Implement; regenerate `web/src/api/schema.d.ts`; `cd web && npm run typecheck`. Docs (`docs/web-app.md`). Commit.

## Self-review
Spec coverage: eval jobs (5), gold builder (5, 6), API endpoints (6, 7), blind ratings (7), system map (8), security (8),
Gemini (1, 2), schema regen (8). Deviations: SR DOI → citation only (decision 5).
