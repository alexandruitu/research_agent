# Web app

## What this is

The department web app: a PostgreSQL database, importers that load finished research runs and eval runs,
sign-in with roles, a job queue and worker that start runs, a JSON API under `/api/v1`, and a React
frontend in `web/` (Papers, Library, Runs, Fields, Evals, System map, Settings) that talks only to that API.

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

## Keyword fields, assist, preview and the team library (slice 4)

**Keywords.** A field version may carry a `description` (≤ 2000), `keywords {all, any, none}` (≤ 20 terms of
1–80 characters per group) and `query_override {europepmc?, openalex?, arxiv?}`. `research_agent.querybuild`
turns keywords into one query per source (Europe PMC `TITLE_ABS:` boolean, OpenAlex
`filter=title_and_abstract.search:`, arXiv `abs:` boolean plus the imaging categories); years are added by the
connectors. A run's `domain.json` gets `queries {source: query}`; a source with a query is searched with it as
is, and when every source has one the pipeline makes no planning call. Fields without keywords run as before.

**Assist** (`POST /fields/assist`, member): one model call (role `assist`, model `RESEARCH_ASSIST_MODEL`, else
`RESEARCH_MODEL`) suggests keywords per group with synonyms and 2–6 inclusion / 0–4 exclusion criteria. It runs
in the worker as job `field_assist`; the result is in the job's `progress.result`. Calls are cached under
`RESEARCH_CACHE_DIR` (default `<project>/cache`, gitignored). Demo mode is deterministic and needs no key.

**Preview** (`POST /fields/preview`, member): job `field_preview` runs the built queries against the enabled
sources (≤ 10 papers each, the source's own hit count, no model). At most 10 previews per user per minute (429).

**Library** (`/library…`): one item per paper, saved from a run with a frozen `snapshot` of its evidence
(paper and abstract, run, field version, screening and criteria, rank, panel score, editor verdict, red flags,
reviewer summaries, text source, file refs). Items have a team status (`to_read`, `read`, `relevant`,
`rejected`), a note, lower-case tags and collections; every change is an event. Saving is idempotent (already
saved papers get the collections and tags merged). Search `q` is ILIKE over title, abstract and note. Viewers
read and export (CSV, injection-safe; BibTeX, escaped); members save and edit; the adder or an admin deletes;
admins archive collections. Paper rows and the drawer carry `library: {item_id, status, collections} | null`.

## More sources (slice 5)

The `sources` table has a row per `research_agent.sources.REGISTRY` entry (14; migration 0006; only Europe PMC
enabled by default). `GET /sources` returns the registry metadata (label, group, covers, auth `none|optional|
required`, key variable names, capabilities, rate limits and `rps_in_use`) plus the worker's key report
(`key_present`, `key_accepted`, `key_detail`, `key_checked_at`; never a value). The worker writes that report at
start-up: presence of every variable, then one search for one result per keyed search source (`accepted`, or
`null` with "check failed": a connector never exposes the HTTP cause when a key was sent). Enabling a source whose
required key the worker did not report → 422 `key_missing` ("Set IEEE_API_KEY in the worker environment first");
`POST /sources/{name}/check` on a full-text-only source (Unpaywall, ScienceDirect) → 422 `not_searchable`.
Fields, previews and query overrides accept all 12 search sources; review settings take the 9 full-text resolvers
in any order. Panel reviews record `text_licence` (`cc-*`, `cc0`, `open_access`, `publisher_licensed`,
`user_upload`, `abstract`; null for older runs); exports read metadata keys only (`library.EXPORT_KEYS`), so no
review text, of any licence, is ever exported. Keys go in `deploy/worker.env` (see `worker.env.example`); restart
the worker after a change.

## Live evals, gold sets, human reference ratings, Gemini (slice 6)

- **Evaluations run as worker jobs** (`eval_run`). `POST /evals` (member) takes `kind` + inputs and returns a
  202 job: `screening` (gold set, optional field version), `panel` (gold set *or* finished research run, review
  settings version — default current —, `sample`, `seed`), `ablation` (a panel report, optional `rerun_editor`),
  `human` (a rating sample). The worker runs the same `research-eval` subcommands as the CLI in a child process
  (`panel`/`screen`/`ablation`/`human`, then `report`) in a new folder under `RESEARCH_EVALS_DIR`, and imports it
  as a new immutable report (`eval_reports.kind`, frozen `config`, `parent_id` for ablation/human). Old screening
  reports keep working (kind `screening`). Job progress: `{status, kind, step, steps, done, total}`, and on success
  `result: {eval_id, folder, warnings}`.
- `GET /evals` lists finished reports (kind, config chips, headline numbers per kind); `GET /evals/jobs` lists
  evaluations without a report yet (queued, running, failed). `GET /evals/{id}` returns metrics, frozen config (paths
  reduced to file names), children and rating samples. `GET /evals/compare?ids=a,b[,c]` aligns 2–3 reports of one
  family (screening; panel + human; ablation). `POST /evals/estimate` counts calls and estimates chars, tokens
  (chars/4) and cost from a small price table before anything starts; it never calls a provider and counts cached
  calls too (an upper bound).
- **Gold sets**: `GET /gold-sets`; `POST /gold-sets` (member) queues `gold_build` from an SR spec (name, citation,
  topic, Europe PMC query, the included studies as DOIs and/or titles). Only the public Europe PMC API is used; the
  gold file is frozen in `RESEARCH_GOLD_DIR`. The SR's own DOI/PMID (`sr_reference`) is recorded, not resolved:
  reading an SR's included list from its references is not automated.
- **Human reference ratings**: an admin draws a rating sample from a panel report
  (`POST /evals/{id}/rating-samples`, stratified by panel score, seeded). Members rate with
  `GET /rating-samples/{id}/next` (text the panel reviewed + checklist items; never a model answer) and
  `POST /rating-samples/{id}/ratings` (every item of every reviewer, once per rater); only then
  `GET /rating-samples/{id}/papers/{paper}/reveal` shows the model's answers next to theirs. Ratings are stored with
  the reviewer version and item wording they answered. Each submission queues (at most one at a time) a `human`
  job: the worker writes `human_ratings.json` into the panel folder (eval contract), copies the folder, recomputes
  there and imports a new `human` report — the panel report never changes.
- **System map**: the Reviewers stage reads the newest panel/human report's Fleiss kappa (or raw agreement when
  kappa is undefined); the "one model family" caveat appears only when every reviewer uses one provider.
- **Gemini**: set `GOOGLE_API_KEY` in the worker's environment and use model ids such as
  `google_genai:gemini-2.5-pro`, `google_genai:gemini-2.5-flash` or `google_genai:gemini-3.1-pro-preview` for any
  role (reviewers, editor). The worker checks the key with the free models listing
  (`GET https://generativelanguage.googleapis.com/v1beta/models`, key in the `x-goog-api-key` header); a provider whose
  key is set but that no role uses gets a `key:<provider>` row in the workers status, and `/models/available` lists the
  curated Gemini ids once the key is accepted. Structured output uses the same `json_schema` path as Anthropic.

## Runs management (slice 7)

Every research run has a page, `/runs/<id>`, and the list at `/runs` can filter, sort, select and act.

- **Who may do what.** Everyone reads runs, compares them and exports them. Members also run any research run
  again (the new run is theirs) and read its worker log and calls summary. The run's creator or an admin also
  resumes, cancels, renames, annotates, pins and deletes it; imported runs (no creator) are admin-only for that.
- **Detail.** The frozen configuration (field and version, sources with their caps, review settings version,
  panel reviewers with versions, models per role, mode, papers to screen, prompt version), the stage timeline
  (start, end, duration from `progress.json` `timings`, recorded since this slice; older runs say "not recorded"),
  counts, wall time, links to the papers, evaluations made from the run and library items saved from it.
- **Run again.** `POST /runs/{id}/rerun {"config": "same"|"current"}` (send an `Idempotency-Key`): `same` reuses
  the frozen domain and review requests, field version, review settings and panel versions exactly; `current` uses
  the field's current version and the current review settings. Both keep `max_papers` and `mode`.
- **Resume** works for `failed` and `cancelled` runs. When the run folder's `manifest.json` has another prompt
  version than the code, it is refused with 409 `prompt_version_changed`; the page says why and offers
  "Run again (same configuration)".
- **Cancel.** `POST /runs/{id}/cancel`: a queued run is cancelled at once (200); a running one gets
  `jobs.cancel_requested`, its worker stops the child at the next poll and marks job and run `cancelled`
  (202 `cancelling`). The checkpoint stays, so a cancelled run can be resumed. A stale job with a cancel request
  is cancelled, not requeued.
- **Delete.** `DELETE /runs/{id}` and `POST /runs/delete {"ids": [...]}` (per-run results). Not while queued or
  running (409 `run_active`), never an eval run, and not when a panel evaluation was computed from the run
  (409 `referenced_by_eval`). The run's rows go by `ON DELETE CASCADE`; library items keep their snapshot with
  `run_id` set to null; papers stay. The folder is moved, never erased, to
  `<RESEARCH_RUNS_DIR>/.trash/<run id>-<UTC time>`; a folder outside the runs directory is left where it is. To
  restore one, move it back out of `.trash` and import it (`POST /api/v1/imports` as an admin, or `research-web dev --import-all`).
- **Debug.** `GET /runs/{id}/log?lines=N` (members): the tail of `worker.log` (at most 256 KiB read) with every
  secret value replaced by `***`, the failed stage and reason, and the `"<role>: attempt N failed (...)"` retry
  lines; `&download=true` returns it as a file. `GET /runs/{id}/calls` (members): calls per role and model from the
  call cache with characters in/out and an estimated cost (the evaluation estimate's approximate list prices).
  Cache hits and per-call durations are not recorded by the cache and show as "not recorded".
- **Compare.** `/runs/compare?ids=a,b` (`GET /runs/compare`): configuration rows marked "differs", papers kept in
  one run and dropped in the other, papers screened in only one, and score changes.
- **Export.** `GET /runs/{id}/export?format=csv|bibtex|bundle` and `GET /runs/export?ids=a,b&format=csv|bibtex`.
  The bundle is a zip of `report.json`, `report.md`, `domain.json`, `review.json`, `manifest.json` and a README;
  never the call cache, checkpoints, uploads, logs or keys. Full texts are never in `report.json` (only hashes);
  quotes from `publisher_licensed` texts are blanked and `report.md` is left out when there are any.
- **List.** Filters (status including `cancelled`, field, only mine, date range), search over name, topic and
  field, sort and order, pinned runs first; the list refreshes every 3 s while a run is queued or running. Tick
  runs for bulk CSV/BibTeX export, Compare (exactly two) or Delete; every row has an actions menu (Open, Run
  again, Resume, Cancel, Export, Rename or add a note, Pin, Delete) operable with the keyboard; destructive
  actions ask first; results arrive as toasts. `?field=<id>` still preselects the start form; the field filter
  is `?in=<id>`.

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

Design ("the reading room", slice 4): warm paper background, ink text, one teal accent for primary actions and
focus; Newsreader (serif) for titles and reading text, IBM Plex Sans for the interface, both self-hosted from
`@fontsource` (no CDN, CSP-safe). Light and dark follow `prefers-color-scheme`. Feedback arrives as toasts
(bottom right, a polite live region) with **Undo** where it makes sense; loading shows skeletons; empty lists
say what to do next; only destructive actions ask for confirmation. Leaving a page with unsaved edits (a
field, a settings tab, a reviewer) asks first, from the main navigation, the settings tabs, Sign out or a
reload. With no paper to show yet, **Papers** opens on "Create your first field in 3 steps".

Keyboard (Papers and Library; never while typing in a field; `?` lists them): `j`/`k` move, `o` open,
`x` select (Papers), `s` save the selection to the library (Papers), `1`–`4` status (to read, read, relevant,
rejected), `/` search (Library), `Esc` close the side panel.

Screens and who sees them:

- **Library** (every role reads; members save and edit; the adder or an admin removes; admins archive
  collections): a list of saved papers (status as icon + word, score, red flags, collections, #tags, note mark)
  and a reading pane. Search (title, abstract, note), status buttons, collection, tag, field, minimum score,
  "Has red flags", sort and direction; active filters show as chips with **Clear all**; everything is in the URL
  (`/library?status=relevant&collection=<id>&item=<id>`). The pane has a sticky header (title, status radio
  group, Remove) and three sections: **Overview** (abstract set for reading, collections with create-on-the-spot,
  tags, note, files), **Evidence** (the snapshot frozen at save: screening decision and criteria with quotes,
  editor verdict and score, red flags, reviewer summaries; "Update evidence from the newer run" when a newer
  finished run of the same field exists) and **History** (every change in words). Status changes are instant with
  Undo. **Export CSV / BibTeX** download exactly the filtered list. **Manage collections** creates and renames
  (members) and archives/restores (admins).
- **Papers** (every role): run picker (`field · vN · kind`), counts, filter chips, "Dropped by criterion" and
  "Source" filters, the pipeline strip, the paper table and the paper drawer. The **Criteria** column names the
  criterion that decided ("dropped by incl 1 (0.01)", "dropped by excl 1 (LLM: yes)", "all met"); runs of a
  legacy field (only `topic_match`) still show the probability, sortable, with the topic-match range filter.
  The drawer's Screen step is a per-criterion table (Jev p, LLM answer, quote) naming the decider; "Found by"
  lists the sources.
  Panel runs (slice 3) replace "Reviewers A / B" with **Peer review score** ("72 · 8/10 answered", with a
  coverage meter; sortable), **Red flags** ("⚑ 2 red flags") and **Text reviewed** ("full text · PMC",
  "abstract only"), plus a "Has red flags" filter (`flags=true` in the URL). The drawer's **Peer review** step
  shows the editor's decision and reason first, the disagreements in words, the red flags with the quotes that
  raised them, then one collapsible report per reviewer (verdict, score, coverage, strengths/weaknesses and the
  checklist: answer icon + word, quote + section, "red flag" in words). Below the timeline, **Full-text PDFs**
  lists uploads (download for members, delete for the uploader or an admin) and lets members upload one
  (drag and drop or "Choose a PDF…", with progress; checked in the browser and again by the server); when only
  the abstract was reviewed the section is titled "Upload full text (PDF)".
  The drawer's Raw calls tab (exact prompt and response) is for members and admins only.
  Checklist answers also say **meets** or **concern** for the paper, from the item's "good answer" in the exact
  reviewer version that answered (so "✓ yes · ▲ concern" on a negatively phrased item is not mistaken for good).
  Slice 4: members tick rows (or "select all on this page") and press **Save to library…** (collections, a new
  collection, tags, team status, note); the rows say "In library · ★ Relevant" at once, the toast offers Undo
  (removes only the items that save created) and a refusal rolls the rows back. A saved row's badge links to its
  library item. The drawer's sticky header has **Save to library…** or, once saved, the badge and the status
  radio group. Active filters show as chips with **Clear all**.
- **Runs** (every role; the Start form and Run again are for members and admins; resume, cancel, rename, pin and
  delete for the run's creator or an admin): the filterable runs list, start a run (1 to 12 papers, demo mode when
  the server allows it), follow its job, and `/runs/<id>` and `/runs/compare` (see "Runs management (slice 7)").
- **Evals** (every role reads; members start evaluations; admins create rating samples): `/evals` lists report
  cards (kind, date, config chips, headline numbers in words, parent/follow-up links), evaluations in progress
  with their step, a kind filter and compare selection (2–3 reports of one family → `/evals/compare?ids=`).
  `/evals/new` is the wizard: kind → inputs (gold set or finished run, sample and seed, panel report and
  "re-run the editor" for 1/2/3 reviewers, demo mode, "Build a gold set from a systematic review") → cost
  estimate → start → follow → Open report. `/evals/<id>` shows the report by kind: screening (recall with
  intervals, threshold grid), review panel (Fleiss kappa with raw agreement and prevalence, items worst-first
  with "candidate to reword", coverage full text vs abstract, score dispersion, SR inclusion AUC, model
  families, rating samples), 1/2/3 reviewers (summary sentence, SVG chart with an equal table, every subset),
  human reference (panel vs human consensus per reviewer and item, Spearman). `/rate/<sample>` is the blind
  Rate view (keys 1–4 answer the focused item; the models' answers appear only after submitting).
- **System map** (every role): every stage with its status in words and a panel explaining it.
- **Fields** (every role reads; members create, edit, test and start runs; admins archive and restore): the
  list (version, author, criteria and keyword counts, sources, last run, Start run, "Show archived fields") and
  the editor at `/fields/<id>`, a three-step flow (`?step=1|2|3` in the URL; new fields open on 1, saved ones
  on 2; every step stays reachable from the stepper and **Save** is on every step):
  **1 · Describe** (name, a free description, an optional topic line; **Suggest keywords & criteria** runs the
  `field_assist` job and shows chips per group, synonyms and criteria sentences: nothing is applied until a chip
  or **Accept all** is clicked; a synonym of a Must-include term goes to At least one of),
  **2 · Keywords & criteria** (three tag inputs Must include / At least one of / Exclude: Enter or comma adds,
  Backspace removes the last; inclusion and exclusion lists; sources, only those enabled in Settings; years;
  the query each source will search, built live in the browser exactly like the server builds it, and an
  **Advanced: override query** disclosure per source),
  **3 · Preview & save** (**Preview search** runs `field_preview`: per source the hit count it reports, the first
  10 titles, the exact query and a failing source's error; **Test criteria**; change note; **Save as vN+1** /
  **Create field**). A **Field summary** card beside it shows the field as it would be saved and whether there
  are unsaved changes. "Demo mode" (in the URL as `demo=1`) covers suggestions, preview and the criteria test. Saving sends the version the editor opened; if
  someone saved in between, the editor says "This field changed since you opened it (now vN)" and offers to
  reload (unsaved edits are discarded). **Test criteria** sends the editor's current text (saved or not) to a
  Jev-only test of up to 20 papers; "Demo mode" uses the offline stand-in. The side panel lists versions with
  notes and runs, compares two versions (each line says added / removed / unchanged), and says "screening
  for this field (vN): not measured" unless an eval ran on that version. A legacy field is edited by adding
  criteria, which creates v2. Start run links to `/runs?field=<id>` with the field preselected.
- **Settings** (every role reads; admins write), tabs Sources · Reviewers · AI models · Screening · Full text ·
  Users. **Sources** (enable, max results per run, Test = one real one-result search, the contact address sent
  to OpenAlex). The four review tabs share one frame: a plain-language intro, a "Used by next run · vN" badge,
  Reset to default, a change note and one **Save as vN+1** that creates a new settings version (409 → "reload
  the latest version"; 422 shows the pipeline's message); leaving a tab with unsaved edits asks first (tab
  links, the main navigation, Sign out and reload/close).
  **Reviewers**: a card per reviewer (role, item count, how many items can raise a red flag, model, "In the
  default panel" switch; 1 to 5, the switch explains why when it is locked), the editor's instructions,
  archived reviewers (every role can open the list; Restore is for admins), "New reviewer". A reviewer's page (`/settings/reviewers/<key>`) edits the
  name, perspective, model and checklist (add, reorder, remove; weight 1·low/2·normal/3·high, what a good
  answer is, "red flag if", CLAIM / TRIPOD+AI source) with a live **What the model reads** preview (perspective
  and item key + text only: weights and red-flag rules are applied by code and never shown to the model),
  Save as vN+1, Reset to default, Archive/Restore and the version history, where two versions can be compared
  (perspective, model, items added / removed / changed).
  **AI models**: a model per role (Plan, Screen, Screen per criterion, Extract, each panel reviewer, Editor),
  limited to models whose provider key the worker accepted, a warning when all reviewers share one provider,
  and the worker's key report below (never a key). A reviewer's model is stored in the reviewer, so changing it
  here saves a new reviewer version (the tab says so).
  **Screening**: the four Jev thresholds (slider + number) with a band diagram and a sentence per criterion
  kind, and the latest Evals recommendation translated exactly for inclusion criteria (keep from
  (1 + min_confidence)/2, drop at or below (1 − exclude_min_confidence)/2) with "Apply to inclusion criteria";
  exclusion bands have no measured counterpart and are left alone.
  **Full text**: switches for PMC OA, Unpaywall and uploads (tried in that order), the Unpaywall contact
  (required while it is on), maximum length and upload limit.
  **Users** (admins only: invite, change role, deactivate). `/users` redirects to `/settings/users`.

Three rules the UI keeps:

1. A stage is green (teal) only when it is measured; `input`, `caveat` and `not measured` look different and
   say so in words.
2. Missing data is hatched and says "missing"; a dash means "does not apply". The two are never conflated.
3. State is never conveyed by colour alone: every coloured chip, cell and box also carries text.

## Deployment

Docker Compose files live in `deploy/`; see `docs/deployment.md`. They cannot be run on a machine without
Docker, so they are checked by tests as data only until a Docker host (or CI) builds them.
