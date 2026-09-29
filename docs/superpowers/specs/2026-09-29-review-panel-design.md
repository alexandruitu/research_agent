# Peer-review panel, full text and configurable settings: design (web app slice 3)

Date: 2026-09-29 · Status: approved in brainstorming (user asked for the most user-friendly UI, no mockups)

## Goal

Simulate a peer-review process on the papers kept by screening:

- A **panel** of reviewers with distinct roles (default: Methodologist, Clinician, Statistician), each
  completing a **checklist** (items drawn from CLAIM and TRIPOD+AI) with an exact quote per answered item,
  plus a short free-text report and verdict.
- An **Editor** (replaces the adjudicator; always runs) synthesizes the reports, lists disagreements and
  gives the final verdict with a reason.
- **Scores and red flags are computed in code** from checklist answers, never taken from the model.
- Reviewers read the **full text where available** (PMC Open Access, then Unpaywall legal OA copies, then a
  PDF uploaded by a user), else the abstract; items the abstract cannot answer are `not_reported`, never `no`.
- **Settings** gains editable tabs: **Reviewers** (profiles and default panel), **AI models** (model per role),
  **Screening** (Jev thresholds), **Full text** (sources, contact, limits, upload rules). Admins edit;
  everything is versioned; every run freezes its settings.

## Decisions (from brainstorming)

| Question | Decision |
|---|---|
| Kind of peer review | Role-based panel + formal checklist per reviewer |
| Text reviewed | Full text where available + manual PDF upload; abstract fallback |
| Who defines reviewers | Predefined set, editable in the app (Settings → Reviewers) |
| Settings made configurable now | Reviewers, AI models, Screening thresholds, Full text |
| Later | Run limits/demo switch, scoring weights (not in this slice) |
| Config reaches the pipeline | Frozen snapshot `review.json` in the run folder (like `domain.json`) |

## Pipeline

Flow: `screen → fulltext → extract → reviewers (parallel, 1..5) → editor → score (code) → rank`.

**`review.json`** (validated `ReviewSpec`, unknown keys refused), written by the worker at start:

```json
{"schema": 1,
 "panel": [{"key": "methodologist", "name": "Methodologist", "version": 2, "perspective": "…",
            "model": "anthropic:claude-sonnet-5",
            "items": [{"key": "m1", "text": "Data were split at patient level, not image level.",
                       "weight": 2, "red_flag_if": "no"}]}],
 "editor": {"model": "anthropic:claude-opus-5-5", "instructions": "…"},
 "models": {"plan": "…", "screen": "…", "screen_criteria": "…", "extract": "…"},
 "screening": {"keep_min": 0.8, "include_fail_max": 0.05, "exclude_hit_min": 0.95, "exclude_clear_max": 0.2},
 "fulltext": {"sources": ["pmc_oa", "unpaywall", "upload"], "contact": "…", "max_chars": 60000}}
```

- Absent `review.json` → today's behaviour (review_a/review_b/adjudicate), so old runs and the eval harness
  keep working. `research-agent --review FILE` passes it on the CLI.
- **Full text** (`fulltext.py`): PMC OA via Europe PMC `fullTextXML` for PMCID papers; Unpaywall by DOI (needs
  contact email) for a legal OA PDF/HTML; uploaded PDFs from `<run>/uploads/<paper-id>.pdf` or a shared upload
  store passed by the worker. PDF → text with `pypdf`; sections detected where possible (Methods, Results…).
  Cached in `research.sqlite`; text truncated to `max_chars` with sections prioritised (Methods, Results first).
  A failed fetch is **not** fatal: the paper falls back to the abstract and records `text_source`.
- **Reviewer call** (role `review:<key>`): input = paper text + perspective + items; output per item
  `{key, answer: yes|no|unclear|not_reported, quote, section}` plus `verdict (include|exclude|uncertain)`,
  `strengths`, `weaknesses`, `summary`. Every non-empty quote is verified against the text used
  (snap + exact substring); `yes`/`no` require a quote; retries 3× then fail closed.
- **Editor call** (role `editor`): input = the reports; output `{verdict, reason, disagreements: [{item, reviewers, note}]}`.
- **Scoring in code**: per reviewer `score = 100 × Σ(weight × pass) / Σ(weight × answered)`, where pass = `yes`
  (or `no` for items phrased negatively via `pass_if`), `unclear`/`not_reported` excluded from the denominator
  and counted as **coverage**; paper score = mean of reviewers; red flags = items whose answer matches
  `red_flag_if`, deduplicated with the reviewers that raised them. Rank uses paper score, then editor verdict.
- `report.json` gains per paper: `text_source`, `reviews: {key: {...}}`, `editor`, `score`, `coverage`, `red_flags`.
  Existing keys stay. `PROMPT_VERSION` bumps.

Default panel (seeded, English, editable): Methodologist (study design, patient-level split, external
validation, reference standard, leakage), Clinician (population, clinical relevance, reference standard
applicability, workflow), Statistician (metrics with CIs, sample size, calibration, missing data, subgroups).
8–12 items each, each tagged with its CLAIM / TRIPOD+AI source item.

## Web backend

Tables: `reviewer_profiles` (key, active) + `reviewer_versions` (name, perspective, items JSONB, model, note,
author, created_at); `settings_versions` (models, screening, fulltext, default_panel, editor; one current);
`paper_files` (paper, sha256, filename, size, uploaded_by, created_at; stored under `RESEARCH_UPLOADS_DIR`).
Runs record the settings version and panel versions used (via `review.json` snapshot).

API: `GET/POST /reviewers`, `POST /reviewers/{key}/versions` (base_version → 409), archive/restore;
`GET /settings/review` + `POST /settings/review` (new version, admin); `GET /models/available` (from worker
status: models whose provider key was accepted); `POST /papers/{id}/files` (member; PDF only, ≤ 30 MB,
magic-byte check, stored by hash), `GET /papers/{id}/files`, `DELETE` (uploader or admin). Importers read the
new report fields; paper table gains `score`, `coverage`, `red_flags`, `text_source`; drawer gains the panel.

## Frontend (user-friendly principles)

- **Settings** tabs: Sources · **Reviewers** · **AI models** · **Screening** · **Full text** · Users. Each tab:
  plain-language intro line, sensible defaults, "Reset to default", a single Save that creates a new version
  with a note, and a visible "Used by next run" badge. Read-only with an explanation for non-admins.
- **Reviewers**: cards per reviewer (name, role summary, item count, model, on/off in default panel);
  editor with perspective text, item list (add, reorder, weight 1–3 as a segmented control, "red flag if"
  toggle, source tag CLAIM/TRIPOD+AI), live preview of how an item reads to the model.
- **AI models**: one row per role with a dropdown limited to available models and a warning chip when all
  reviewers share one family.
- **Screening**: four sliders with numeric inputs and the Evals recommendation shown next to them
  ("Evals recommends …, apply").
- **Full text**: toggles per source with a one-line explanation, contact email, max length, upload limits.
- **Papers**: new columns Score (with coverage bar and text), Red flags (chips), Text (full text / abstract);
  filter "Has red flags".
- **Drawer**: a "Peer review" step with the editor verdict first, then one collapsible report per reviewer
  (verdict, score, checklist table with answer icons+words, quotes with section), disagreements highlighted
  in words; "Upload full text (PDF)" when only the abstract was used.

## Errors and safety

Full-text fetch failures fall back silently to the abstract (recorded); reviewer quote failures fail closed
as today. Uploads: PDF magic bytes, size limit, stored by hash outside the web root, never executed, served
only to members. Only public/OA or user-provided text is sent to providers; uploads are marked as such.

## Testing

Pipeline: ReviewSpec validation; full-text resolvers against recorded fixtures (no network in tests); PDF
text extraction on a small fixture PDF; reviewer/editor schemas with quote verification and retries; scoring
and red-flag table tests; legacy runs unchanged. Backend: migration + seed of the default panel; versioning
and 409; upload validation and access rules; snapshot at start; importer. Frontend: Vitest for each Settings
tab, reviewer editor, Papers columns and drawer panel; Playwright: edit a reviewer → demo run → panel
visible in the drawer; axe on new pages.

## Plans

1. Pipeline: ReviewSpec, full text, panel reviewers, editor, scoring/red flags, CLI `--review`.
2. Backend: tables + seed, reviewers/settings/models/files API, worker snapshot, importer, paper fields.
3. Frontend: Settings tabs, reviewer editor, Papers/drawer, e2e + a11y.
