# Runs management (slice 7)

Date: 2026-10-06 · Status: approved feature list (user: build it, no questions; decisions recorded here)

## Goal

Turn **Runs** from a start form plus a flat table into a place to understand, repeat, stop, debug, compare,
export and tidy research runs.

## Permissions

| Action | Who |
|---|---|
| List, detail, compare, export (csv, bibtex, bundle) | every role (viewers already read every run's papers) |
| Log tail, calls summary | members and admins (same as the Raw calls tab) |
| Re-run (both kinds) | members and admins, on any research run (the new run is theirs) |
| Resume, cancel, delete, rename/note/pin | the run's creator or an admin (imported runs, no creator: admins only) |

## Data

Migration `0008_runs_management`: `runs.name` (varchar 200, null), `runs.note` (text, default ''),
`runs.pinned` (bool, default false), `runs.started_at` (timestamptz, null); `jobs.cancel_requested` (bool,
default false). `created_by` already exists. Run status gains `cancelled` (status is a free string; no
constraint to change). Job status gains `cancelled`.

Stage timings: `progress.json` gains `timings: {stage: {started_at, finished_at}}` written by `Progress.observe`
(the pipeline) from now on. Old runs: per-stage times are "not recorded"; the run's wall time comes from
`progress.json` `started_at`/`updated_at`, else `runs.started_at`/`finished_at`, else `created_at`/`finished_at`.

## Features

1. **Detail `/runs/:id`** — frozen configuration (field + version, sources with `max_results` from
   `domain_request`, review settings version, panel reviewers with versions from `run_reviewers`, models per role,
   mode, max_papers, prompt version from the run folder's `manifest.json`), stage timeline (start, end, duration),
   counts, wall time, links to Papers (`/?run=`), Evals made from it, Library items saved from it.
2. **Re-run** `POST /runs/{id}/rerun {config: "same"|"current"}` with `Idempotency-Key`. `same` copies
   `domain_request`, `review_request`, field version, settings version and run reviewers exactly; `current` builds
   them like `POST /runs` from the field's current version and the current review settings. Contract
   (`max_papers`, `mode`) is copied in both. Refused for eval runs and archived fields (409), caps as for start.
3. **Resume** allowed for `failed` and `cancelled`. Detail returns `resume: {allowed, reason, code}`. If the run
   folder's `manifest.json` has a different `prompt_version` than the code, resume is refused with
   409 `prompt_version_changed` and the UI offers "Run again (same configuration)" instead.
4. **Cancel** `POST /runs/{id}/cancel`: queued → job and run `cancelled` in one UPDATE; running → the job's
   `cancel_requested` is set; the worker checks it each poll, stops the child with `stop_child`, marks job and run
   `cancelled` (checkpoint kept, resumable). A stale running job with a cancel request becomes `cancelled`, not
   requeued. Anything else → 409.
5. **Delete** `DELETE /runs/{id}` and `POST /runs/delete {ids}` (bulk, per-id results). Research runs only.
   409 while queued/running, and 409 `referenced_by_eval` when a panel eval was made from the run (eval run
   manifest `source.run_dir` = the run folder), naming the reports. Rows: the run row is deleted; screenings,
   criterion scores, claims, reviews, rankings, run reviewers, paper reviews, panel reports, red flags go by
   `ON DELETE CASCADE`; `library_items.run_id` is `SET NULL` so the snapshot stays (tested). Papers stay.
   The folder moves to `<RESEARCH_RUNS_DIR>/.trash/<id hex>-<UTC timestamp>`; only a folder that resolves inside
   the runs root (and is not the root or the trash) is moved; nothing is ever unlinked.
6. **Debug** `GET /runs/{id}/log?lines=N&download=` (members): the tail of `worker.log` (≤ 256 KiB read,
   ≤ 2000 lines), passed through `redact()`; plus the failed stage and reason from `progress.json` and the
   `"<role>: attempt N failed (...)"` lines. `GET /runs/{id}/calls` (members): per role and model — stage, calls,
   input/output chars, estimated cost; cache hits and durations are not recorded by the call cache and are shown
   as "not recorded".
7. **Compare** `GET /runs/compare?ids=a,b`: config rows (label, a, b, differs) and results: kept in A dropped in
   B and vice versa, papers only in one run, score changes (panel score or ranking score) with delta.
8. **Export** `GET /runs/{id}/export?format=csv|bibtex|bundle`; bulk `GET /runs/export?ids=…&format=csv|bibtex`.
   Bundle = zip of `report.json`, `report.md`, `domain.json`, `review.json`, `manifest.json` (those present) and a
   `README.txt`. Never `research.sqlite`, checkpoints, uploads, logs or keys. Full texts are never in
   `report.json` (only hashes); for papers whose text licence is `publisher_licensed`, every `quote` in the
   bundle's `report.json` is blanked and `report.md` is left out (it prints evidence quotes).
9. **Rename/note/pin** `PATCH /runs/{id} {name?, note?, pinned?}`; list sorts pinned first.
10. **Cost and duration** in the detail: calls per provider/model and an estimated cost (the eval estimate's
    `PRICES`, labelled estimate), wall time.

List: `GET /runs` gains `status`, `mine`, `created_from`, `created_to`, `q` (name, topic, field name), `sort`
(`created|name|status|papers`), `direction`; rows gain name, note, pinned, created_by, created_by_name, topic.
UI: filters, search, sort, polling while anything is queued/running, row checkboxes, bulk delete and CSV export,
an accessible row menu (Open, Re-run, Resume, Cancel, Export, Rename, Delete), confirmation for destructive
actions, toasts. Run compare page `/runs/compare?ids=a,b`.

## Out of scope

Deleting eval runs (Evals owns them), cancelling eval jobs, restoring from trash in the UI (folder stays in
`.trash`; an admin can move it back and use import), per-call durations and cache-hit counting.
