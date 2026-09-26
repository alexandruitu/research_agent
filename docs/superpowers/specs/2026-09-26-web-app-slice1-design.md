# Web app, slice 1: foundation and paper table — design

Date: 2026-09-26 · Status: draft for review · Branch: `feat/web-app` (stacked on `feat/eval-harness`)

## Context and vision

The research agent (search, dedup, screen with Jev then LLM, extract with exact quotes, two reviewers,
adjudication, rank) and its eval harness (`research-eval`) exist and produce files: `runs/<id>/` and
`evals/<name>/` folders, `gold/*.json`. Reading them means opening JSON and Markdown by hand, and the
project has many concepts that are hard to grasp.

The tool is meant to run for a whole department, possibly company-wide: **a curated field radar** that
screens the literature for what matters in the department's field and presents papers that make sense,
already screened and explained. A later step (step 2, out of scope here) turns a paper into code, so
the design keeps a paper a first-class record with a slot for full text and room for an implementation
tab; nothing is built for it now.

## Decisions taken during brainstorming

| Topic | Decision |
|---|---|
| Audience | Department first, possibly corporate: shared server, logins, SSO-ready, real database |
| Daily workflow | Both: a field inbox (saved topics on a schedule, colleagues vote) and ad-hoc research; inbox first, ad-hoc is the same pipeline behind "Run now" |
| What "makes sense" means | Topic plus criteria the team writes and edits; each criterion is a yes/no question for Jev and a column in the table (slice 2) |
| Home page | Paper-centric table whose columns are the pipeline stages (merged strip), plus a separate System map page |
| Stack | FastAPI JSON API, React + TypeScript SPA, PostgreSQL with a Postgres-backed job queue, Docker Compose |
| Expert votes | Become expert gold labels (`label_source = expert`) for the eval harness (slice 3) |

## Slices

1. **Foundation and paper table (this spec).** Database, API, logins, worker, Papers/Runs/Evals/System
   map/Users/Login screens, import of existing runs and evals.
2. Fields and criteria: team-editable criteria, passed into the pipeline (needs the run contract extended).
3. Votes and the feedback loop: relevant / not relevant, feeding expert gold labels.
4. Scheduled monitors: saved fields run weekly and land in an inbox of new papers.

Slices 2–4 are a roadmap this slice must not block; nothing in slice 1 builds them.

## Non-goals of slice 1

Editing fields or criteria, votes, scheduled monitors, SSO, a full audit log, full-text retrieval, the
business layer, paper-to-code, self-signup, a live event stream (polling is used), automated backups.

## Architecture

Components (Docker Compose):

| Service | Role |
|---|---|
| `web` | nginx serving the built React app and proxying `/api` to `api` |
| `api` | FastAPI: sign-in, read endpoints, enqueue jobs. Never runs the pipeline. Holds no LLM keys |
| `worker` | Claims jobs, runs the existing pipeline in a subprocess, runs the importer. The only service with LLM keys |
| `db` | PostgreSQL 16: product data and the job queue |

Shared volume: the run folders (`runs/`, `evals/`, `gold/`); mounted read-write in `worker`, read-only in `api`.

Rule: the API enqueues, the worker executes. A request such as "run this field" writes a `jobs` row and
returns immediately; the browser polls the job.

Two stores with different roles: PostgreSQL holds product data (what people see and edit); the run
folders remain the audit trail and Raw Layer (`research.sqlite` `calls`, checkpoints, manifests) exactly
as today. The importer copies finished runs and evals into PostgreSQL.

Existing code is not rewritten: `research_agent` (pipeline) and `research_agent.eval` remain libraries
called by the worker and importer.

Repository layout (new):

```
src/research_agent/web/
  api/        FastAPI app, routers, auth, schemas, dependencies
  db/         SQLAlchemy models, Alembic migrations, repositories
  worker/     job claiming, subprocess runner, heartbeat
  importer/   run and eval importers
  cli.py      `research-web`: migrate, create-admin, import, worker, serve
  stages.yaml stage catalog (System map content)
web/          React + TypeScript app (Vite)
deploy/       docker-compose.yml, Dockerfiles, nginx.conf, deployment notes
```

Technology defaults (fixed here to avoid ambiguity): Python 3.12, FastAPI, SQLAlchemy 2 with Alembic,
psycopg 3, argon2-cffi; frontend Vite + React 18 + TypeScript, TanStack Query and Table, React Router,
plain CSS with design tokens (no heavy UI kit), TypeScript types generated from the OpenAPI schema with
`openapi-typescript`.

## Data model (PostgreSQL)

Primary keys are UUIDs; every table has `created_at`.

| Table | Important columns |
|---|---|
| `users` | `id`, `email` (unique), `name`, `role` (`viewer` / `member` / `admin`), `password_hash`, `active` |
| `sessions` | `id`, `user_id`, `expires_at`, `last_seen_at`, `revoked_at`, `csrf_token` |
| `fields` | `id`, `name`, `topic`, `created_by` |
| `criteria` | `id`, `field_id`, `key`, `question`, `version`, `position` |
| `papers` | `id`, `source_id` (unique, e.g. `MED:35097009`), `doi`, `title`, `abstract`, `year`, `fulltext_ref` (reserved, always null in slice 1) |
| `runs` | `id`, `field_id`, `kind` (`research` / `eval`), `status` (`queued` / `running` / `done` / `failed`), `manifest` (jsonb), `folder`, `source_sha256`, `gold_set_id` (eval runs), `created_by`, `finished_at`, `error` |
| `screenings` | `id`, `run_id`, `paper_id`, `found_by` (`query` / `lookup`), `tier` (`jev` / `llm` / `rule`), `decision` (`include` / `exclude` / `uncertain`), `jev_decision`, `llm_decision`, `reason`, `call_key` |
| `criterion_scores` | `screening_id`, `criterion_id`, `probability`, `jev_version` |
| `evidence_claims` | `id`, `run_id`, `paper_id`, `statement`, `quote`, `call_key` |
| `reviews` | `id`, `run_id`, `paper_id`, `role` (`a` / `b` / `adjudicator`), `verdict`, `relevance`, `methods`, `support`, `detail` (jsonb: strengths, weaknesses, assessment, takeaways), `call_key` |
| `rankings` | `run_id`, `paper_id`, `score`, `position` |
| `gold_sets` | `id`, `name`, `citation`, `sha256` |
| `gold_labels` | `gold_set_id`, `paper_id`, `label` (`include` / `not_included`), `label_source` (`sr_included_list` now, `expert` in slice 3), `via` |
| `eval_reports` | `id`, `gold_set_id`, `run_id`, `metrics` (jsonb: the `metrics.json` content), `agreement` (jsonb or null) |
| `jobs` | `id`, `kind` (`research` / `import`), `payload` (jsonb), `status` (`queued` / `running` / `done` / `failed`), `progress` (jsonb), `attempts`, `locked_by`, `heartbeat_at`, `idempotency_key` (unique per user), `created_by`, `error` |

Invariants:
- A paper exists once (unique `source_id`, and DOI when present); decisions belong to a run.
- Criteria are versioned and never edited in place; every `criterion_scores` row records the criterion version. In slice 1 each field has one criterion, `topic_match`, created at import from the topic sentence.
- Every decision that came from a model call keeps its `call_key`, pointing into the run folder's `calls` table.
- The paper table is a database view over one run: papers joined with screenings, criterion scores, reviews, rankings and the gold label.

## API

REST + JSON under `/api/v1`. Errors: `{"code", "message", "request_id"}` with 401, 403, 404, 409, 422, 429;
an unexpected 500 returns only a generic message and the request id. Default deny: every route declares a
role. Pagination: `page`, `page_size` (capped at 200). `POST` endpoints that spend money accept an
`Idempotency-Key` header.

| Verb and path | Purpose | Role |
|---|---|---|
| `POST /auth/login`, `POST /auth/logout`, `GET /auth/me` | Sign in (cookie), sign out, current user | public / signed in |
| `POST /users`, `PATCH /users/{id}` | Invite, change role, deactivate | admin |
| `GET /fields`, `GET /fields/{id}` | Fields with criteria | viewer |
| `GET /runs`, `GET /runs/{id}` | Runs with status, models, counts | viewer |
| `GET /runs/{id}/papers` | The paper table (sort, filter, page) | viewer |
| `GET /runs/{id}/papers/{paper_id}` | The drawer: abstract, screening, claims, reviews, rank, gold label | viewer |
| `GET /runs/{id}/calls/{call_key}` | Exact prompt and response from the run folder | member |
| `GET /stages` | System map: catalog plus latest measurements | viewer |
| `GET /evals`, `GET /evals/{id}` | Eval reports: recall, sweep, holdout, agreement | viewer |
| `POST /runs` | Enqueue a research run for a field (`field_id`, `max_papers`); returns a job id | member |
| `POST /runs/{id}/resume` | Resume a failed run from its checkpoint | member |
| `GET /jobs/{id}` | Job status and progress (the browser polls every 2 s) | member |
| `POST /imports` | Import a run or eval folder | admin |

Paper table filters: `decision`, `tier`, `escalated` (bool), `in_sr` (bool), `criterion` + `p_min` / `p_max`.
Sorts: title, year, any criterion probability, score. One row:

```json
{"paper": {"id": "…", "source_id": "MED:35097009", "title": "…", "year": 2021, "doi": "…"},
 "found_by": "lookup", "in_sr": true,
 "screen": {"tier": "llm", "decision": "exclude", "jev_decision": "escalate", "llm_decision": "exclude",
            "criteria": {"topic_match": 0.06}},
 "extract": {"claims": 5, "quotes_verified": true},
 "reviews": {"a": "uncertain", "b": "exclude", "adjudicated": true, "adjudicator": "uncertain"},
 "rank": null}
```

A cell can be `null` (stage not applicable, shown as a dash), or `{"missing": true}` (expected data not
found, shown hatched). The API never collapses the two.

## Sign-in and security

- Local accounts for slice 1: email and password (argon2id), invited by an admin; no self-signup, no default password. The first admin is created with `research-web create-admin`.
- Sign-in sits behind one interface ("who is this user?"); corporate SSO (OpenID Connect) becomes a second implementation later without touching endpoints.
- Server-side sessions in PostgreSQL (revocable), HttpOnly + Secure + SameSite cookie, CSRF token on every state-changing request, idle and absolute expiry (defaults 8 h / 7 d, configurable). Sign-in is rate-limited per account and per address.
- Roles: viewer reads; member reads, starts and resumes runs, sees raw calls; admin manages users and imports.
- LLM keys (Anthropic, TypeSafe) exist only in the worker environment; the API container has none. Keys never appear in URLs, logs, responses or jobs; the existing `*_API_KEY` redaction is reused.
- Data leaving the company: only public titles and abstracts go to LLM providers. The allowed providers are a deployment setting, and the app logs at startup which external hosts it can reach. Note for slice 2: criteria text is also sent to the model and the UI must say so where criteria are edited.
- Input handling: parameterized queries, capped page sizes; run folders are located only from database ids, never from user paths; `call_key` must match a hex pattern; abstracts are rendered as text only; strict Content-Security-Policy; TLS at the reverse proxy with HSTS (deployment notes).
- Audit: runs, jobs and imports record the user; sign-ins are logged. A full audit log is a later slice.
- Dependencies pinned; `pip-audit` and `npm audit` run in CI.

## Screens

Top navigation: Papers, Runs, Evals, System map; user menu (Users for admins). All screens are read-only
except Runs (start, resume) and Users.

1. **Papers (home).** Toolbar: field and run pickers, counts, filter chips (kept, dropped, only escalated, in the SR). The **pipeline strip** sits above the table as column group headers: Search, Screen, Extract, Reviewers, Rank, plus the SR label; each header shows its status and headline number from `/stages`. Columns: paper, found by, topic match (Jev probability with a Jev/escalated badge), decision (with the deciding tier), claims, reviewer A / B, score, in SR. Clicking a stage header opens an "about this stage" panel; clicking a row opens the drawer.
2. **Paper drawer.** A stage-by-stage timeline for one paper: search (how it was found), screen (Jev probability against the auto-drop line, escalation, LLM reason), extract (claims with verified quotes), reviewers (A, B, adjudicator with reasons), rank, SR label. Tabs: Abstract, Raw calls (members).
3. **Runs.** List with status chips; "Start run" (members) with a paper cap; a failed run shows a red banner with the failed stage, the sanitized reason and Resume; a running run shows job progress.
4. **Evals.** Per eval set: summary cards (search recall, Jev share, recommended pair, reviewer kappa with a same-family flag); recall as dot-and-interval rows for llm_only / jev_only / cascade on the main set and the holdout; the threshold grid (rows include, columns exclude, cell = screening calls saved, shipped default outlined, recommended pair starred, pairs that lose an SR-included paper on the holdout in red); the rejected-pick note; caveats.
5. **System map.** The pipeline as clickable boxes; a stage panel shows what it does, its status, known limits, the latest measurements and links into the data.
6. **Users** (admin): invite, role, deactivate. **Sign-in** page.

### Stage catalog

`stages.yaml` holds, per stage: `id`, `title`, `summary`, `limits`, and `measured_by` (a named metric path into the latest `eval_reports`, or none). Status is computed, never written by hand:
- `measured`: the metric exists in the latest eval report;
- `caveat`: measured but a data-driven caveat applies (for Reviewers: `agreement.same_family` is true);
- `unmeasured`: no metric.

A stage is only teal when a measurement exists; `caveat` and `unmeasured` render amber. Headline numbers come from the same report fields the Evals page uses.

## Import

The importer reads run and eval folders with the existing readers and writes in **one transaction per
run**. It is idempotent: `runs.source_sha256` records the hash of what was imported, so re-import updates
without duplicating, and it refuses to overwrite a run whose gold set hash changed.

- **Research run** (`runs/<id>/`): `report.json` state gives contract, papers, `screens` (decision, reason, tier, and the `jev` block with probabilities and model version), `evidence`, `reviews_a`, `reviews_b`, `decisions`, `ranking`. The field is matched or created by topic.
- **Eval run** (`evals/<name>/` + `gold/<name>.json`): candidates and labels from the gold file; per paper the cached Jev probabilities and LLM screen decision (the same offline read the report uses); reviews from `agreement.json`; `metrics.json` into `eval_reports`. Because the LLM screened every paper, the table shows both `jev_decision` and `llm_decision`, and `decision` / `tier` are the cascade outcome at the shipped default thresholds, computed with `cascade_decision`.
- The raw prompt and response stay in the run folder; the importer stores each `call_key`.
- Missing expected data (a decision without its raw call, a screened paper without its abstract) is imported as flagged, never dropped silently.

Triggers: `research-web import --all` for first load, and `POST /imports`.

## Worker and jobs

State machine: `queued → running → done | failed`; `running → queued` when the heartbeat is stale and
`attempts < 3`, else `failed`.

1. `POST /runs` validates the caps (paper limit, concurrency), writes a `jobs` row (idempotency key honoured), returns 202 and the job id.
2. The worker claims a job with `SELECT … FOR UPDATE SKIP LOCKED`, refreshes `heartbeat_at`, and runs the existing `run_research` in a separate process (the `jobs.py` pattern): keys in the child environment only.
3. Every couple of seconds it copies `progress.json` into `jobs.progress`.
4. On success it runs the importer on the finished run; `runs.status = done`.
5. On failure it stores the sanitized error (type and safe message) and keeps the checkpoint; `POST /runs/{id}/resume` reuses the pipeline's checkpoint resume.
6. Concurrency is set by configuration; default one job at a time.

Slice 1 runs use the default `topic_match` criterion from the field's topic; passing team criteria into the pipeline is slice 2.

## Errors

Fail closed and visible: a failed run is a first-class state, never a half-filled table shown as complete;
import is all-or-nothing per run; missing data (hatched) differs from not-applicable (dash); API errors have
one shape with a request id; `POST /runs` is idempotent; each frontend panel has an error boundary and a
"data may be stale" indicator when polling fails.

## Testing

No test needs the network or API keys.

- **API:** pytest with FastAPI's test client against a real PostgreSQL container (the queue's locking and JSON columns differ from SQLite); migrations tested.
- **Importer:** small committed fixtures (a synthetic demo-mode run, a toy eval set built with the existing eval test helpers): row counts, idempotent re-import, refusal on a changed gold hash, rollback on failure. **Consistency test:** importing a fixture eval and calling the Papers and Evals endpoints yields exactly `build_report`'s recall, sweep and recommended pair.
- **Worker:** two workers racing for one job never run it twice; a stale heartbeat requeues; a failure stores a sanitized error and keeps the checkpoint; end-to-end demo-mode run from `POST /runs` to a table row.
- **Security:** a test enumerates every route and fails if one lacks a role guard; role matrix (viewer/member/admin × every endpoint); CSRF, sign-in rate limit, session revocation, path traversal on `call_key`; a sentinel key placed in the environment must never appear in responses, logs or errors.
- **Frontend:** Vitest + Testing Library for the strip (a stage is green only with a measurement), table cells (missing vs not-applicable), and the drawer timeline; a check that fails when the generated API types are stale; a few Playwright end-to-end flows (sign in, Papers, drawer, System map, Evals grid); accessibility checks (axe) on the main pages; the table and drawer work from the keyboard.
- **CI:** ruff, pytest, type-check, lint, Vitest, Playwright headless, `pip-audit`, `npm audit`, Docker builds.
- Not tested here: LLM judgment quality; that is the eval harness's job.

## Success criteria

- `docker compose up` then `research-web import --all` shows the real mlffrct-2024 and aiffr-slr-2023 data in Papers (strip and drawer), Evals and System map.
- An admin can invite a member, and the member can start a demo-mode run that appears in the table.
- The role matrix and route-guard tests pass; the Evals page numbers equal `metrics.json` exactly; all tests are green in CI.

## Decided for now, revisit if wrong

- Polling every 2 s rather than a live event stream.
- One job at a time by default; `max_papers` capped per request.
- The System map content lives in `stages.yaml` in the repository, edited by developers, not in the database.
- Users, sessions and jobs live in the same PostgreSQL instance as product data.
