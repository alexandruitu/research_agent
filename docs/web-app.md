# Web app (backend)

## What this is

The backend of the department web app: a PostgreSQL database, importers that load finished research
runs and eval runs, sign-in with roles, and a read-only JSON API under `/api/v1` for the paper table,
the paper drawer, runs, evals and the System map. The React frontend comes in plan 3 (`docs/superpowers/plans/2026-09-26-web-app-*.md`).

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
- Roles: viewer (read), member (also raw calls, and in plan 2 start runs), admin (also users, imports).
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
  stops its child instead of writing over the new owner.

Checked on 2026-09-26: a demo run with 3 papers went queued → running → done with every stage `completed`,
a repeated start with the same key returned 200 and the same job, the run shows 3 screened / 3 kept with
3 rows in the table, and a start without the CSRF header was refused with 403.

## Deployment

Docker Compose files live in `deploy/`; see `docs/deployment.md`. They cannot be run on a machine without
Docker, so they are checked by tests as data only until a Docker host (or CI) builds them.
