# Slice 7: Runs management Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Run detail, re-run, resume/cancel, delete to trash, debug log and calls, compare, export, rename/note/pin
and cost for research runs, in the API, worker and the Runs UI.

**Architecture:** One service module `src/research_agent/web/runs.py` (pure functions over a session and settings:
config, timeline, calls summary, compare, export, trash, permissions) behind thin routes in
`api/routers/runs.py`. The worker gains a cancel check in its poll loop; `jobs.py` gains `request_cancel`. The
pipeline's `Progress` records stage timings. The frontend gets a run detail page, a compare page, a rewritten list
with a menu button and a confirm dialog.

**Tech Stack:** FastAPI, SQLAlchemy 2 + Alembic (PostgreSQL via pgserver in tests), React 18 + TanStack Query, Vitest.

Spec: `docs/superpowers/specs/2026-10-06-runs-management-design.md`.
Testing rule (user): TDD, only the test files a task adds or touches, plus `ruff check .` and
`cd web && npm run typecheck && npm run lint`. No full pytest/vitest, no e2e, no live runs, no provider calls.

## Decisions (made without asking)

1. Owner-or-admin for resume/cancel/delete/patch; any member for re-run (the new run is theirs); members for
   log/calls; every role for detail/compare/export. Resume used to be open to any member: now owner-or-admin
   (the existing resume test sets `created_by`).
2. Re-run is one endpoint `POST /runs/{id}/rerun` with `{"config": "same" | "current"}`; both copy `max_papers`
   and `mode`. `same` on a legacy (pre-panel) run reproduces it without a panel.
3. Cancel uses a `jobs.cancel_requested` column, checked by the worker each poll (no signal to another host).
4. Delete only research runs; eval runs belong to Evals. Bulk delete is `POST /runs/delete {ids}` (a DELETE with a
   body is awkward for proxies), returning `{deleted: [...], refused: [{id, code, message}]}`.
5. Trash name `<id hex>-<YYYYmmddTHHMMSSZ>` under `<runs_dir>/.trash`; a folder outside the root, missing, or the
   root itself is not moved (rows still deleted; the response says `folder: "missing" | "trashed" | "outside"`).
6. Bundle redaction for `publisher_licensed`: blank `quote` values for those papers in `report.json`, drop
   `report.md`; full texts are never in `report.json` (hashes only).
7. Calls summary from `research.sqlite` `calls` (role, model, input/output length); cache hits and durations are
   "not recorded" (null). Provider = model id prefix before `:` (`anthropic`, `google_genai`, `jev-*` → `typesafe`).
8. Stage timings: `progress.json.timings`; `runs.started_at` set by the worker when it starts the child; `finished_at`
   also set on failure and cancel.
9. Bulk export: `GET /runs/export?ids=a,b&format=csv|bibtex` (one file, a `run` column in CSV).

## File map

- Create `src/research_agent/web/db/migrations/versions/0008_runs_management.py`; modify `db/models.py`.
- Modify `src/research_agent/runner.py` (`Progress.observe` timings), `web/runner.py` (`progress_snapshot` keeps timings).
- Modify `src/research_agent/web/jobs.py` (`request_cancel`, stale cancel), `web/worker.py` (cancel in poll, started_at).
- Create `src/research_agent/web/runs.py`; modify `api/routers/runs.py`, `api/schemas.py`.
- Tests: `tests/test_web_migration_runs.py`, `tests/test_progress_timings.py`, `tests/test_web_run_cancel.py`,
  `tests/test_web_runs_manage.py`, `tests/test_web_runs_debug.py`, `tests/test_web_runs_export.py`;
  modify `tests/test_web_runs_api.py` (resume owner).
- Frontend: `web/src/api/{schema.d.ts,types.ts,hooks.ts}`, `web/src/components/ui/{MenuButton,ConfirmDialog}.tsx`,
  `web/src/features/runs/{RunList,RunFilters,RunActions,runWords}.tsx|ts`, `web/src/pages/{RunsPage,RunDetailPage,RunComparePage}.tsx`
  and their tests, `web/src/App.tsx`, `web/src/styles.css`, `web/src/test/fixtures.ts`.
- Docs: `docs/web-app.md`.

---

### Task 1: Migration 0008 and models

**Files:** Create `src/research_agent/web/db/migrations/versions/0008_runs_management.py`; modify
`src/research_agent/web/db/models.py`; Test `tests/test_web_migration_runs.py`.

- [ ] Step 1: failing test — after upgrade the columns exist with defaults:

```python
def test_runs_management_columns(migrated_engine):
    cols = {c["name"]: c for c in sa.inspect(migrated_engine).get_columns("runs")}
    assert {"name", "note", "pinned", "started_at"} <= set(cols)
    assert "cancel_requested" in {c["name"] for c in sa.inspect(migrated_engine).get_columns("jobs")}
```
- [ ] Step 2: run `pytest tests/test_web_migration_runs.py -q` → FAIL.
- [ ] Step 3: add model columns (`name: String(200)|None`, `note: Text default ''`, `pinned: Boolean default false`,
  `started_at: DateTime|None`; `Job.cancel_requested: Boolean default false`), autogenerate against a scratch pgserver
  DB (`alembic revision --autogenerate` with `alembic_config(url)` upgraded to 0007), review, keep only these
  columns, server defaults `''`/`false`; downgrade drops them.
- [ ] Step 4: test passes. Step 5: commit.

### Task 2: Stage timings in progress.json

**Files:** modify `src/research_agent/runner.py` (`Progress.observe`), `src/research_agent/web/runner.py`
(`progress_snapshot` adds `timings`, `started_at`); Test `tests/test_progress_timings.py`.

```python
def observe(self, name, status):
    with self.lock:
        now = datetime.now(UTC).isoformat()
        self.data["stages"][name] = status
        t = self.data.setdefault("timings", {}).setdefault(name, {})
        if status == "running":
            t["started_at"], t.pop("finished_at", None) = now, None
        else:
            t["finished_at"] = now
        self.data["updated_at"] = now
        atomic_json(self.path, self.data)
```
Test: `Progress(tmp).observe("plan","running"); observe("plan","completed")` → timings has both, ordered.
Note `Progress.write()` must preserve `timings` (it only updates keys; a resume starts a fresh `Progress`, so the
writer reads the old file's `timings` first: `self.data["timings"] = read_json(path, {}).get("timings", {})`).

### Task 3: Cancel (jobs + worker)

**Files:** modify `web/jobs.py`, `web/worker.py`; Test `tests/test_web_run_cancel.py`.

```python
def request_cancel(db, run_id):
    """'cancelled' (a queued job, cancelled now), 'requested' (running: the worker stops it), or None."""
    job = db.scalar(select(Job).where(Job.kind == "research", Job.status.in_(("queued", "running")),
                    Job.payload["run_id"].astext == str(run_id)).with_for_update())
    if job is None: return None
    if job.status == "queued":
        job.status = "cancelled"; _set_run(db, job, status="cancelled", finished_at=func.now()); return "cancelled"
    job.cancel_requested = True; return "requested"
```
`claim` skips nothing new (status queued only). `requeue_stale`: a stale job with `cancel_requested` → `cancelled`.
Worker `_research`: after each `_still_owned`, `if self._cancel_requested(db, job): interrupted = "cancelled"`;
after `stop_child`: `_update_owned(... status="cancelled", locked_by=None)`, run `cancelled`, `finished_at`. Tests:
queued cancel; running cancel with a fake child (`poll()` returns None until terminated) and the `world` fixture;
stale + cancel → cancelled.

### Task 4: Service module and list/detail/patch

**Files:** create `web/runs.py`; modify `api/routers/runs.py`, `api/schemas.py`; Test `tests/test_web_runs_manage.py`.

`can_manage(user, run)`, `frozen_config(db, run)`, `timeline(progress, run)`, `resume_state(db, run)`,
`wall_seconds`. RunOut gains `name, note, pinned, created_by, created_by_name, topic`. RunDetailOut gains
`config, timeline, wall_seconds, resume, links{papers, evals[], library_count}, active_job_id`.
`GET /runs` filters and sort; `PATCH /runs/{id}` (owner/admin; name ≤ 200, note ≤ 5000).
Tests: list filters (status, mine, q, sort, pinned first); patch permissions (other member 403, admin ok);
detail config/timeline for an imported demo run; resume reason when manifest prompt version differs.

### Task 5: Re-run and resume rules

Route `POST /runs/{id}/rerun`; refactor `start_run` body into `_create_run(...)`. Resume: owner/admin, statuses
`failed|cancelled`, `prompt_version_changed` 409. Tests in `tests/test_web_runs_manage.py` and the touched
`tests/test_web_runs_api.py` resume test.

### Task 6: Cancel and delete routes

`POST /runs/{id}/cancel` (owner/admin; 409 otherwise), `DELETE /runs/{id}`, `POST /runs/delete`. `trash_folder`.
Tests: library item keeps snapshot with run_id null; eval referencing → 409; folder moved under `.trash`; folder
outside root untouched.

### Task 7: Log and calls

`GET /runs/{id}/log` (redacted tail, attempts, failed stage/reason, download), `GET /runs/{id}/calls`
(per role/model rows + totals + cost estimate). Test `tests/test_web_runs_debug.py` (secret in env redacted;
viewer 403).

### Task 8: Compare and export

`GET /runs/compare`, `GET /runs/{id}/export`, `GET /runs/export`. Test `tests/test_web_runs_export.py`
(bundle file list, no sqlite, licensed quotes blanked; compare differences on two imported demo runs).

### Task 9: Frontend API layer

`npm run gen:api`; types and hooks (`useRuns(params)` with polling, `useRun` polling while active, mutations for
rerun, resume, cancel, patch, delete, bulk delete, `useRunLog`, `useRunCalls`, `useRunCompare`).

### Task 10: MenuButton and ConfirmDialog

Accessible menu button (aria-haspopup, aria-expanded, arrow keys/Home/End/Escape, focus return) and a confirm
dialog (`<dialog>`-free modal with role="alertdialog", focus trap on two buttons, Escape cancels). Tests in
`web/src/components/ui/ui.test.tsx` (touched).

### Task 11: Runs list page

Filters (status incl. cancelled, field, only mine, from/to), search, sort, pinned first, checkboxes, bulk delete
and export, row menu, toasts, polling. Update `web/src/pages/RunsPage.test.tsx`.

### Task 12: Run detail page

Header (name inline rename, pin, note), actions, config, timeline, counts, cost/calls, log (members),
links. `web/src/pages/RunDetailPage.test.tsx`.

### Task 13: Run compare page and docs

`/runs/compare?ids=a,b`; `web/src/pages/RunComparePage.test.tsx`; update `docs/web-app.md`.

## Self-review

Every spec feature maps to a task (1→T4/T12, 2→T5, 3→T5, 4→T3/T6, 5→T6, 6→T7, 7→T8/T13, 8→T8, 9→T4, 10→T4/T7/T12,
list→T4/T11). Names used across tasks: `request_cancel`, `can_manage`, `trash_folder`, `frozen_config`, `timeline`.
