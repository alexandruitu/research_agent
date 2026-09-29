# Web app

## What this is

The department web app: a PostgreSQL database, importers that load finished research runs and eval runs,
sign-in with roles, a job queue and worker that start runs, a JSON API under `/api/v1`, and a React
frontend in `web/` (Papers, Runs, Fields, Evals, System map, Settings) that talks only to that API.

## Requirements

```bash
pip install -e '.[dev,live,ui,web,web-dev]'
```

No Docker and no system PostgreSQL are needed for development: `research-web dev` starts an embedded
PostgreSQL 16 (the `pgserver` package) with its data in `.web-dev/pgdata`.

## Run it locally

The admin password is read from the environment so it never appears on the command line:

```bash
export RESEARCH_WEB_ADMIN_PASSWORD='choose-a-long-passphrase'
research-web dev --import-all --admin-email you@example.org --admin-name "Your Name"
```

This creates the admin (once), imports every folder under `runs/` and `evals/`, and serves the API on
`http://127.0.0.1:8000/api/v1`. Stop it with Ctrl-C; the data stays in `.web-dev/`.

## Commands

| Command | What it does |
|---|---|
| `research-web migrate` | apply database migrations (`RESEARCH_WEB_DATABASE_URL` required) |
| `research-web create-admin --email … --name …` | create an admin; password from `RESEARCH_WEB_ADMIN_PASSWORD` or a prompt |
| `research-web import PATH… \| --all` | import run and eval folders; prints `created`, `updated`, `unchanged` or `FAILED` per folder |
| `research-web openapi -o FILE` | write the OpenAPI schema (the frontend generates its types from it) |
| `research-web dev` | embedded PostgreSQL, migrations, optional admin and import, then the API |

## How the numbers get in

- The importers read the same files the pipeline and `research-eval` write (`report.json`, `research.sqlite`,
  `manifest.json`, `metrics.json`, `agreement.json`, the gold file). Each folder is imported in one
  transaction: a failure writes nothing.
- Re-importing is safe: an unchanged folder is `unchanged`, a changed one is replaced in place. A gold file
  whose content no longer matches the eval run's manifest is refused.
- Raw prompts and responses stay in the run folders and are read on demand (members only), through a
  validated 64-hex call key and a folder check that refuses anything outside the configured roots.
- Candidates without an abstract are listed in the paper table (tier `rule`, "not screened") but are not
  counted as screened, kept or dropped, so the run counts equal the eval report.
- The System map's status is computed, never written by hand: a stage is `measured` only when its metric
  exists in the imported eval data. **Limitation:** each metric is taken from the most recently imported
  eval report that has it, so one stage's number may come from a different gold set than another's.

Checked on the real data (2026-09-26): mlffrct-2024 151 screened / 112 kept / 82 escalated / 16 in the SR,
aiffr-slr-2023 141 / 129 / 82 / 19, live-01 5 / 5 / 2 / 0; the only SR-included paper the mlffrct-2024
screen dropped is the ΔCT-FFR paper (Jev 0.06, escalated, LLM exclude; reviewers A uncertain, B exclude,
adjudicator uncertain).

## Security notes

- No default password; the first admin is created explicitly.
- Sessions are server-side (cookie `ra_session`, `HttpOnly`, `SameSite=Lax`, `Secure` unless
  `RESEARCH_WEB_COOKIE_SECURE=false` for local development); every state-changing request needs the
  `X-CSRF-Token` header; sign-in is rate limited per process.
- Roles: viewer (read), member (also raw calls, start runs, create and save fields, test criteria, upload and
  download full-text PDFs), admin (also users, imports, archive fields, sources, settings, reviewers, review
  settings).
  A test fails if any route lacks a role guard.
- LLM provider keys never enter the API process; the API docs endpoints are off.

## Runs and the worker

The API never runs the pipeline. `POST /api/v1/runs` (members) writes a job row and returns 202; a worker
claims it from PostgreSQL (`FOR UPDATE SKIP LOCKED`), runs the existing pipeline in a child process,
mirrors `progress.json` into the job every poll, and imports the finished run into the database. A run
goes `queued` → `running` → `done` (or `failed`). The browser polls `GET /api/v1/jobs/{id}`.

Locally, start the API with a worker thread and demo runs allowed (demo mode makes no model calls):

```bash
research-web dev --with-worker --allow-demo --import-all --admin-email you@example.org
```

In production the worker is its own process (`research-web worker`) and the API is `research-web serve`
behind a TLS reverse proxy; see `docs/deployment.md`.

- **Keys.** Live runs need the provider keys in the *worker's* environment only. The child process gets them;
  the database URL and every `RESEARCH_WEB_*` variable are removed from its environment. Keys never go on a
  command line, into the database, into errors or into the API. Tests never start a live run.
- **Failures** are stored as `failed at stage '<stage>': <ErrorType>: <safe message>` or
  `the run process exited with code <n>`, never raw provider output; the child's output stays in
  `worker.log` in the run folder, and the checkpoint is kept so `POST /runs/{id}/resume` continues it.
- **Safety nets.** `Idempotency-Key` makes a repeated start return the same job; caps limit `max_papers` and
  active runs per user; a worker whose heartbeat goes stale loses the job (another worker resumes it) and
  stops its child instead of writing over the new owner. Heartbeats use the database clock, so hosts with
  different clocks cannot steal live jobs; imports keep the heartbeat going from a separate thread. The run
  follows its job: requeued → `queued`, out of attempts → `failed` with the same message.
- **Resume.** `POST /runs/{id}/resume` is atomic (one `UPDATE … WHERE status='failed'`) and refused while a
  queued or running job already carries the run. The worker passes `--resume` only when the folder has a
  `manifest.json`; otherwise it starts the run again from the saved contract. Run folders must lie under
  `RESEARCH_RUNS_DIR` (symlinks resolved), or the job fails without starting anything.
- **Time limit.** `RESEARCH_WEB_JOB_TIMEOUT_SECONDS` (default 3600) bounds one run; past it the child is
  stopped and the job and run fail with `the run timed out after N s`. `RESEARCH_WEB_PROGRESS_POLL_SECONDS`
  times 3 must stay below `RESEARCH_WEB_JOB_STALE_SECONDS`.
- **Graceful stop.** SIGTERM or SIGINT (`docker stop`, Ctrl-C) asks `research-web worker` to stop: a running
  child is stopped and its job goes back to the queue without counting an attempt (the run shows `queued`
  and continues from its checkpoint on the next claim). `dev --with-worker` stops and joins its worker
  thread when the API exits. A child that finds the folder locked by another process exits with 75
  (`EX_TEMPFAIL`); the worker then gives the job back the same way instead of failing the run.
- **.env.** The child never loads a `.env` (`PYTHON_DOTENV_DISABLED=1`), so it sees exactly the worker's
  environment minus the removed variables. `research-web dev --with-worker` loads `.env` into its own process
  environment for the worker's keys (not into the API settings, not into logs); set
  `PYTHON_DOTENV_DISABLED=1` to skip that. `research-web worker` never reads `.env`: give it the keys in
  its environment (`deploy/worker.env` in Docker).

Checked on 2026-09-26: a demo run with 3 papers went queued → running → done with every stage `completed`,
a repeated start with the same key returned 200 and the same job, the run shows 3 screened / 3 kept with
3 rows in the table, and a start without the CSRF header was refused with 403.

## Fields, sources and worker checks (slice 2)

- **Fields are versioned.** `POST /fields` creates version 1; `POST /fields/{id}/versions` saves the next one
  and must send `base_version` (the version the editor opened); if someone saved in between the answer is
  409 `stale_version` "This field changed since you opened it (now vN)". Old versions and their criteria are
  never changed; runs record the version they used (`RunOut.field_version`). Admins archive and restore a
  field; an archived field cannot be saved, tested or run (409 `archived`). Migration 0002 turned every
  existing field into version 1 with its `topic_match` question as a `legacy` criterion.
- **Starting a run.** A field with inclusion or exclusion criteria starts a `--domain` run: the API builds
  `domain.json` from the current version, its sources that are enabled (each with the source's
  `max_results`; OpenAlex gets the contact email from Settings) and the default thresholds, and stores it in
  the run (`manifest.domain_request`); the worker writes it as `domain.request.json` next to the run and the
  pipeline copies it to `domain.json`. None of the field's sources enabled → 422 `no_enabled_source`. A legacy
  field starts today's positional-topic run (Europe PMC must be enabled). Resume passes only `--resume` once
  the pipeline has saved its manifest (the saved contract holds the domain); before that the run starts again
  from the stored request.
- **Sources and settings** (`/sources`, `/settings`): everyone reads, admins change them. A connection check
  (`POST /sources/{name}/check`) is a worker job that searches for one result and records `last_check_*`.
- **Criteria test** (`POST /fields/{id}/test`, members): a worker job that searches the field's enabled
  sources (at most 20 papers after deduplication) and asks Jev every criterion; the result (per paper:
  probabilities, decision, deciding criterion; a summary) arrives in the job's `progress.result`. Nothing is
  written to the paper tables. The body may carry an unsaved draft. Live tests need `TYPESAFE_API_KEY` in the
  worker; demo mode (when the server allows it) uses demo papers and an offline stand-in for Jev.
- **Key check.** `research-web worker` (not `--once`) and `dev --with-worker` check the provider keys once at
  start and write one `worker_status` row per model role: key present, key accepted (a free model-listing
  call for Anthropic and OpenAI; TypeSafe has none, so "not checked"). Never a key value. A failed check does
  not stop the queue; `GET /workers/status` shows it.
- **Papers.** Rows gain `sources` (which sources found the paper) and `screen.cells` / `screen.decided_by`
  (per criterion: Jev p, LLM answer, quote); filters `decided_by=<key>` and `source=<name>`. The drawer gains
  `screening.criteria_table` with every criterion of the run's version and the one that decided. Fields added
  to existing responses are optional in the generated TypeScript types, so older clients keep compiling.

Checked on the real data after migration 0002 (2026-09-29): the three imports give the same numbers as above
(mlffrct-2024 151 / 112 / 82 / 16, aiffr-slr-2023 141 / 129 / 82 / 19, live-01 5 / 5 / 2).

## Review panel, review settings and uploads (slice 3)

- **Every new run is a panel run.** `POST /runs` builds `review.json` from the current review settings version and
  the current version of each reviewer in the default panel, validated by the pipeline's `ReviewSpec`, and keeps
  it in `run.manifest["review_request"]` (the run also links `settings_version_id` and `run_reviewers`). The
  worker writes `<run>/review.request.json`, passes `--review`, and on every start and resume hard-links (or
  copies) the latest uploaded PDF of each paper to `<run>/uploads/<safe-id>.pdf`, where the pipeline reads it.
  Resume uses the saved manifest (`--resume` only). Old runs import exactly as before.
- **Reviewers** (`/reviewers`): versioned profiles (name, perspective, checklist items, optional model). Saving
  needs `base_version` (409 `stale_version` otherwise); archived reviewers cannot be saved (409 `archived`); a
  reviewer in the default panel cannot be archived (409 `in_default_panel`). Seeded: Methodologist, Clinician,
  Statistician (version 1, from `research_agent.panel`).
- **Review settings** (`/settings/review`): versioned models per role, screening thresholds, full text (sources,
  contact, max length, upload limit) and the default panel with the editor. A save is refused (422
  `invalid_settings`) unless the result is a runnable `review.json`. `GET /models/available` lists the models the
  worker, the settings and the reviewers name, marked available when the worker's key check accepted the key.
- **Uploads** (`/papers/{id}/files`): members upload PDFs (checked by the `%PDF-` magic bytes, at most 30 MB or
  the settings' lower limit, only while `upload` is a full-text source), stored once by sha256 under
  `RESEARCH_UPLOADS_DIR` (default `uploads/`, outside any web root). Members download them as attachments; the
  uploader or an admin deletes them. nginx allows 31 MB on this path only.
- **Imports** read `state.review` into `paper_reviews`, `panel_reports` and `red_flags`; the paper table gains
  `score`, `coverage`, `red_flag_count`, `text_source` and the `has_red_flags` filter (sort by score uses the
  panel score), the drawer gains `panel` and `files`. Raw calls of roles `review:<key>` and `editor` open from
  the drawer like the others.

## Frontend

The single-page app lives in `web/` (Vite, React 18, TypeScript strict, TanStack Query). It needs Node 20.19
or newer (CI uses Node 22). It only calls `/api/v1` on its own origin, with the session cookie and the
`X-CSRF-Token` header on every state-changing request; its types are generated from the API's OpenAPI schema.

```bash
cd web && npm install
npm run dev        # http://127.0.0.1:5173, proxies /api to 127.0.0.1:8000
npm test           # Vitest + Testing Library
npm run gen:api    # regenerate src/api/schema.d.ts from the running code
npm run e2e        # Playwright + axe: starts its own API, worker and synthetic data
```

For `npm run dev`, run the backend in another terminal:
`research-web dev --import-all --with-worker --allow-demo --admin-email you@example.org` (password in
`RESEARCH_WEB_ADMIN_PASSWORD`). `npm run gen:api` must be run after any API change and the result committed:
CI regenerates the file and fails if it differs. `npm run e2e` needs `npx playwright install chromium` once.

Screens and who sees them:

- **Papers** (every role): run picker (`field · vN · kind`), counts, filter chips, "Dropped by criterion" and
  "Source" filters, the pipeline strip, the paper table and the paper drawer. The **Criteria** column names the
  criterion that decided ("dropped by incl 1 (0.01)", "dropped by excl 1 (LLM: yes)", "all met"); runs of a
  legacy field (only `topic_match`) still show the probability, sortable, with the topic-match range filter.
  The drawer's Screen step is a per-criterion table (Jev p, LLM answer, quote) naming the decider; "Found by"
  lists the sources.
  The drawer's Raw calls tab (exact prompt and response) is for members and admins only.
- **Runs** (every role; the Start form and Resume are for members and admins): runs with their status, start a
  run (1 to 12 papers, demo mode when the server allows it), follow its job, resume a failed run.
- **Evals** (every role): summary cards, recall with intervals per strategy, the threshold grid (default
  outlined, recommended starred, pairs that lose an SR-included paper in red and in words).
- **System map** (every role): every stage with its status in words and a panel explaining it.
- **Fields** (every role reads; members create, edit, test and start runs; admins archive and restore): the
  list (version, author, criteria counts, sources, last run, Start run, "Show archived fields") and the editor
  at `/fields/<id>`: name, topic, inclusion and exclusion lists (add, reorder, remove), sources (only those
  enabled in Settings), years, change note, **Save as vN+1**. Saving sends the version the editor opened; if
  someone saved in between, the editor says "This field changed since you opened it (now vN)" and offers to
  reload (unsaved edits are discarded). **Test criteria** sends the editor's current text (saved or not) to a
  Jev-only test of up to 20 papers; "Demo mode" uses the offline stand-in. The side panel lists versions with
  notes and runs, compares two versions (each line says added / removed / unchanged), and says "screening
  for this field (vN): not measured" unless an eval ran on that version. A legacy field is edited by adding
  criteria, which creates v2. Start run links to `/runs?field=<id>` with the field preselected.
- **Settings** (every role reads; admins write): **Sources** (enable, max results per run, Test = one real
  one-result search, the contact address sent to OpenAlex), **AI models** (per role: model, whether the
  worker has a key and whether a test call accepted it; never a key), **Users** (admins only: invite, change
  role, deactivate). `/users` redirects to `/settings/users`.

Three rules the UI keeps:

1. A stage is green (teal) only when it is measured; `input`, `caveat` and `not measured` look different and
   say so in words.
2. Missing data is hatched and says "missing"; a dash means "does not apply". The two are never conflated.
3. State is never conveyed by colour alone: every coloured chip, cell and box also carries text.

## Deployment

Docker Compose files live in `deploy/`; see `docs/deployment.md`. They cannot be run on a machine without
Docker, so they are checked by tests as data only until a Docker host (or CI) builds them.
