# Slice 3 · Plan 2: Web backend (review panel, settings, full-text uploads) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Versioned reviewer profiles and review settings (admins edit), PDF uploads per paper (members), every new
run frozen with a `review.json` built from the current settings and default panel, panel results imported into
normalized tables, and the paper table/drawer extended with score, coverage, red flags, text source and the panel —
all behind the existing API contracts, which only gain optional fields.

**Architecture:** Migration `0003` adds `reviewer_profiles`, `reviewer_versions`, `settings_versions`,
`paper_files`, `run_reviewers`, `paper_reviews`, `panel_reports`, `red_flags` and `runs.settings_version_id`, and
seeds the default panel (from `research_agent.panel`) and settings version 1. A service module `web/review.py`
owns versioning, building the run's `review.json` (validated by the pipeline's own `ReviewSpec`) and content
matching for the importer. `web/uploads.py` owns the blob store (by sha256 under `RESEARCH_UPLOADS_DIR`). `POST
/runs` stores the review request in the run; the worker writes `review.request.json`, hard-links (or copies) the
uploaded PDFs into `<run>/uploads/<safe-id>.pdf` and passes `--review`.

**Tech Stack:** Python 3.12, FastAPI (+ python-multipart), SQLAlchemy 2, Alembic, PostgreSQL 16 (`pgserver` in
tests), pytest, ruff; `openapi-typescript` for `web/src/api/schema.d.ts`.

**Spec:** `docs/superpowers/specs/2026-09-29-review-panel-design.md` (Web backend, Errors and safety, Testing,
Plans → 2). Pipeline facts: `docs/superpowers/plans/2026-09-29-slice3-1-pipeline.md` (Data shapes).

---

## Decisions this plan takes (the spec left them open)

1. **Uploads reach the run through the run folder, not `--uploads`.** The pipeline always reads
   `<run>/uploads/<safe-id>.pdf` first. At every start *and* resume the worker materializes the latest upload of
   every paper that has one there (hard link, copy when linking fails; existing files are kept), each blob path
   resolved and confined to the uploads root. The run folder is then self-contained (the audit trail keeps the
   exact PDF even if the upload is deleted later) and resume needs nothing in the manifest. `--uploads` stays a
   CLI feature only.
2. **Every new run is a panel run.** `POST /runs` builds `review.json` from the current settings version + the
   current version of each reviewer of the default panel; stored in `run.manifest["review_request"]` and the job
   payload `review`. Resume: `--resume` only when `manifest.json` exists (the contract holds the review), else
   start again with the saved request. Old runs import unchanged.
3. **Reviewer profiles** are keyed by `key` (`^[a-z][a-z0-9_]{1,29}$`; generated from the name when absent,
   409 `key_taken` when used). Versioning mirrors fields: `current_version` = last user-saved version,
   `base_version` mismatch → 409 `stale_version` "This reviewer changed since you opened it (now vN)", saving an
   archived reviewer → 409 `archived`. Archiving a reviewer that is in the current default panel → 409
   `in_default_panel` "Remove this reviewer from the default panel first". Item keys are optional in requests;
   missing ones are generated (`<first letter of reviewer key><n>`, skipping used keys). Writes: admin.
4. **Settings versions** (`settings_versions`, one row per save, number `max+1`; current = highest non-imported
   version). Content: `models {plan, screen, screen_criteria, extract}` (null = worker env), `screening`
   (Jev thresholds), `fulltext {sources, contact, max_chars, upload_max_mb}` (1–30, default 30),
   `default_panel` (1–5 reviewer keys, active), `editor {model, instructions}`. A save is validated by building
   the full `ReviewSpec` with the reviewers' current versions (422 `invalid_settings` with the pipeline's
   message), so a saved version is always runnable. Seed v1: thresholds = `Thresholds()` defaults, fulltext =
   `default_review(contact).fulltext` (+ `upload_max_mb: 30`) with contact = `app_settings.contact_email`,
   default panel = the three seeded reviewers, editor = `DEFAULT_EDITOR`, note `"default"`.
5. **Run links:** `runs.settings_version_id` and `run_reviewers(run_id, position, reviewer_version_id)`; set at
   start and, for imported runs without links, by content matching (a version with identical content — the
   version number the snapshot names first — else a new version with `note = "imported"`, which never becomes
   current unless it creates the profile).
6. **Imported panel data:** `paper_reviews` (one per run × paper: text source/reason/origin/sections/truncated/
   chars, editor verdict/reason/disagreements/call key, score, coverage, `red_flag_count`), `panel_reports` (one
   per reviewer: key, version link, name, version, verdict, strengths, weaknesses, summary, score, coverage,
   answers JSONB, call key), `red_flags` (per paper review: text, source, raised_by JSONB). Filters use
   `paper_reviews.red_flag_count`.
7. **Files:** `paper_files(paper_id, sha256, filename, size, uploaded_by, created_at)`, unique (paper, sha256):
   re-uploading the same bytes returns the existing row (200). Blob path `<root>/<sha[:2]>/<sha>.pdf`, written to
   a temp file then renamed, mode 0640. Limits: `%PDF-` magic (422 `not_pdf` "Only PDF files can be uploaded"),
   ≤ `min(upload_max_mb, 30)` MB (413 `too_large` "The PDF is larger than N MB"), empty → 422 `not_pdf`; when
   `upload` is not a full-text source → 409 `uploads_disabled` "Uploads are turned off in Settings → Full text".
   List = viewer (metadata only), download = member (attachment, `application/pdf`, nosniff), delete = uploader
   or admin (403 `not_owner` otherwise); a blob is removed when no row references it.
8. **Drawer:** `files` is a top-level `DrawerOut` field (useful for legacy runs too; the upload button lives
   there), `panel` is null for legacy runs. Each reviewer's answers carry the item text/source/weight/red_flag_if
   from the linked reviewer version.
9. **`GET /models/available`** = models configured in the worker (`worker_status`), the current settings and the
   current reviewer versions; each with `provider` (prefix before `:`), `available` (provider key accepted by
   the last worker check), `roles` (worker roles) — plus the provider list. Never a key value.
10. **Sort by score** uses `coalesce(paper_reviews.score, rankings.score)` so every reviewed paper of a panel run
    sorts, legacy runs as before.
11. `python-multipart` and `pypdf` join the `web` extra; `RESEARCH_UPLOADS_DIR` (default `<project>/uploads`,
    gitignored) is a new setting.

## File structure

| File | Responsibility |
|---|---|
| `pyproject.toml`, `.gitignore` | `python-multipart`, `pypdf` in `web`; ignore `uploads/` |
| `src/research_agent/web/settings.py` | `uploads_dir` |
| `src/research_agent/web/db/models.py` | new tables, `Run.settings_version_id` |
| `src/research_agent/web/db/migrations/versions/0003_review_panel.py` (new) | schema + seeds |
| `src/research_agent/web/review.py` (new) | reviewer/settings versioning, `review_for_run`, import linking |
| `src/research_agent/web/uploads.py` (new) | blob store, validation, materialize into a run |
| `src/research_agent/web/api/routers/review.py` (new) | `/reviewers…`, `/settings/review`, `/models/available` |
| `src/research_agent/web/api/routers/files.py` (new) | `/papers/{id}/files…` |
| `src/research_agent/web/api/routers/runs.py`, `runner.py`, `worker.py` | review request, `--review`, uploads |
| `src/research_agent/web/importer/research.py`, `common.py` | panel import, links, `clear_run` |
| `src/research_agent/web/papers.py`, `api/routers/papers.py`, `api/schemas.py` | row fields, filter, drawer |
| `tests/test_web_migration_review.py`, `test_web_reviewers.py`, `test_web_review_settings.py`, `test_web_paper_files.py`, `test_web_panel_runs.py` | new tests |
| `docs/web-app.md`, `web/src/api/schema.d.ts` | docs, regenerated types |

Before every commit: `. .venv/bin/activate && ruff format src tests && ruff check . && pytest -q` (green).
Stage exact files only. Commit with `-m "<subject>" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"`.

---

### Task 1: Migration 0003, models, seeds, settings

**Files:** Create `0003_review_panel.py`, `tests/test_web_migration_review.py`; Modify `models.py`,
`settings.py`, `pyproject.toml`, `.gitignore`, `tests/test_web_db.py` (TABLES).

- [ ] **Step 1: failing test** — upgrade a blank database to `0002`, set `app_settings.contact_email`, upgrade to
  head; assert three reviewer profiles (methodologist, clinician, statistician; `current_version 1`), their v1
  items equal `DEFAULT_PANEL`, one settings version (1, note `default`, contact from app_settings, sources
  include `unpaywall`, `upload_max_mb 30`, `default_panel` = three keys, screening = `Thresholds()` defaults), and
  that the result builds a valid `ReviewSpec`; without a contact, unpaywall is left out; downgrade to 0002 and
  back works. `tests/test_web_db.py` lists the new tables (drift check stays green).

```python
def test_upgrade_seeds_the_default_panel_and_settings_v1(blank_url):
    upgrade(blank_url, "0002")
    engine = sa.create_engine(blank_url)
    with engine.begin() as c:
        c.execute(sa.text("update app_settings set contact_email = 'team@example.org'"))
    upgrade(blank_url)
    ...
```

- [ ] **Step 2:** run → FAIL (no 0003).
- [ ] **Step 3: models** (see `models.py`: `ReviewerProfile`, `ReviewerVersion`, `SettingsVersion`, `PaperFile`,
  `RunReviewer`, `PaperReview`, `PanelReport`, `RedFlag`, `Run.settings_version_id`).
- [ ] **Step 4: migration** — autogenerate against a scratch DB at 0002
  (`alembic -x … revision --autogenerate --rev-id 0003`), review, append the seed (profiles + v1 from
  `research_agent.panel.default_panel()`, settings v1 from `default_review(contact)`).
- [ ] **Step 5:** `Settings.uploads_dir` from `RESEARCH_UPLOADS_DIR` (default `<project>/uploads`).
- [ ] **Step 6:** tests green; commit `Migration 0003: reviewer and settings versions, paper files, panel results; seed default panel`.

### Task 2: Review service and API (reviewers, settings, models)

**Files:** Create `web/review.py`, `api/routers/review.py`, `tests/test_web_reviewers.py`,
`tests/test_web_review_settings.py`; Modify `api/app.py`, `api/schemas.py`.

Service:
```python
class ReviewConflict(Exception): status, code, message
def item_dicts(reviewer_key, items) -> list[dict]      # keys generated for missing ones
def create_reviewer(db, body, user_id) -> ReviewerProfile
def save_reviewer(db, profile, body, base_version, user_id) -> ReviewerVersion
def set_reviewer_archived(db, profile, archived)
def current_settings(db) -> SettingsVersion
def save_settings(db, body, base_version, user_id) -> SettingsVersion   # validated via review_dict
def review_dict(settings_content, reviewer_versions) -> dict             # ReviewSpec-validated review.json
def review_for_run(db) -> (dict, SettingsVersion, [ReviewerVersion])
def link_review(db, review, created_by) -> (SettingsVersion, [ReviewerVersion])  # importer
def available_models(db) -> dict
```

Tests: viewer lists 3 reviewers with `in_default_panel`, `current`, items; admin creates (key from name),
member 403, duplicate key 409 `key_taken`; save v2 with `base_version 1`, stale → 409 `stale_version` message;
v1 still readable; invalid items (21 items, weight 4, bad key, duplicate keys) → 422; archive in default panel →
409 `in_default_panel`; archive other → hidden unless `?archived=true`, restore; saving archived → 409.
Settings: GET current v1 + versions + defaults; admin POST v2; stale → 409; unpaywall without contact → 422
`invalid_settings`; unknown/archived reviewer in default panel → 422; 6 reviewers → 422; member 403; no CSRF 403.
Models: worker_status rows (anthropic accepted, openai rejected) → models with `available`, provider list;
sentinel key never in the body.

Commit: `Reviewers and review settings API: versions, 409 on stale saves, archive rules, available models`.

### Task 3: Paper files

**Files:** Create `web/uploads.py`, `api/routers/files.py`, `tests/test_web_paper_files.py`; Modify `api/app.py`.

```python
MAX_MB = 30
def blob_path(root, sha256) -> Path            # confined to root
def store_pdf(root, stream, limit) -> (sha256, size)   # raises UploadRejected(status, code, message)
def remove_blob_if_unused(db, root, sha256)
def materialize(db, root, run_dir) -> list[str]  # safe-id names written
```

Tests: member uploads a tiny PDF → 201 row (sha256, size, filename), blob at `<root>/<ab>/<sha>.pdf` outside
the runs dir; same bytes again → 200 same id; text file → 422 `not_pdf`; > limit (setting lowered to 1 MB) → 413;
viewer POST 403; viewer lists; viewer download 403; member download → bytes equal, `content-disposition:
attachment`, `x-content-type-options: nosniff`, `content-type: application/pdf`; filename with `../` and quotes
sanitized; other member DELETE → 403 `not_owner`; uploader deletes → blob gone; admin deletes someone else's;
uploads disabled in settings → 409; unknown paper → 404; `materialize` links latest file per paper as
`<safe-id>.pdf` and refuses a blob outside the root.

Commit: `Paper files: PDF uploads by hash, member downloads, owner or admin deletes`.

### Task 4: Start runs with review.json; worker writes it and the uploads

**Files:** Modify `api/routers/runs.py`, `runner.py` (`RunSpec.review_file`, `--review`), `worker.py`,
`api/schemas.py` (`RunOut.settings_version`); tests in `tests/test_web_panel_runs.py`, update
`tests/test_web_runner.py` if needed.

`build_command`: `--review FILE` added when `review_file` (never with resume). Worker: `payload["review"]` or
`manifest["review_request"]` → `<run_dir>/review.request.json` when not resuming; `materialize(...)` always.
Tests: POST /runs stores `review_request` (validates as `ReviewSpec`, panel = current versions), links
`settings_version_id` and `run_reviewers`; end-to-end demo run through the worker with a real child imports a
panel run (paper_reviews for the kept papers); resume payload carries the review; a PDF uploaded for a paper is
hard-linked into `<run>/uploads/`.

Commit: `Start panel runs from the current settings and panel: review.json request, uploads in the run folder`.

### Task 5: Importer

**Files:** Modify `importer/research.py`, `importer/common.py` (`clear_run`); tests in `test_web_panel_runs.py`.

`contract.review` → `link_review` (unless the run is already linked); `state.review[pid]` → `PaperReview`,
`PanelReport` (call key `review:<key>`), `RedFlag`; editor call key. Tests: demo panel run imports with
counts, links to seeded versions (content identical → no new version), unknown panel → imported versions;
re-import unchanged; legacy fixtures unchanged (existing tests).

Commit: `Import panel runs: per-paper reviews, reviewer answers, red flags, settings and panel links`.

### Task 6: Paper table and drawer

**Files:** Modify `papers.py`, `api/routers/papers.py`, `api/schemas.py`; tests in `test_web_panel_runs.py`.

`PaperRow` + `score, coverage, red_flag_count, text_source` (optional); filter `has_red_flags`; sort `score`
coalesced; `DrawerOut` + `panel`, `files`. Tests for each.

Commit: `Paper table and drawer: panel score, coverage, red flags, text source, files`.

### Task 7: Guards, types, docs

Guard matrix gains every new route; `cd web && npm run gen:api && npm run typecheck && npm test`;
`docs/web-app.md` gains Reviewers, review settings, uploads.

Commit: `Regenerate API types; document the review panel backend`.

## Self-review

- Spec coverage: tables + seed (T1); reviewers/settings/409/archive/admin writes, models available (T2); uploads
  PDF-only, ≤30 MB, magic, by hash, members-only download, uploader/admin delete (T3); snapshot at start, worker,
  resume (T4); importer + links + roles (T5); paper fields + filter + drawer (T6); guards/types (T7).
- Compatibility: every response change is an added optional field; `POST /runs` keeps its shape.
