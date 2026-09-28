# Configurable fields and sources: design (web app slice 2)

Date: 2026-09-28 · Status: approved in brainstorming, pending written review

## Goal

Let the team define what they screen for and where the system searches:

- **Fields** get their own page in the main menu. A field is a topic plus inclusion and exclusion criteria
  plus the sources it uses. Fields are versioned: every save is a new version, runs record the version they
  used, old versions are never deleted.
- **Settings** (new menu item) holds the administrative parts: **Sources** (Europe PMC, OpenAlex, arXiv:
  enable, limits, connection test), **AI models** (read-only status of the worker's keys) and **Users**
  (moved here from the main menu).
- Screening decides **per criterion**, so the Papers table and the drawer can say which criterion kept or
  dropped a paper.
- A **Test criteria** button runs only Jev on ~20 papers so wording can be tuned cheaply before a real run.

The app stays in English. Pipeline error messages that are still in Romanian become English.

## Decisions taken during brainstorming

| Question | Decision |
|---|---|
| Where do fields live? | Own page in the main menu; Settings is administrative only |
| What is a field's logic? | Inclusion criteria (all must hold) and exclusion criteria (any one drops) |
| Sources in this slice | Europe PMC (existing), OpenAlex, arXiv; all free, no keys |
| Who edits fields? | Members create and edit; admins archive; every save is a new version |
| Tuning criteria | "Test criteria" with Jev only on ~20 papers |
| How the pipeline gets the config | A frozen snapshot `domain.json` in the run folder (approach A) |
| Menu name | "Fields" (matches the existing "Field" label) |

## Non-goals

- Semantic Scholar, full text, citation snowballing (OpenAlex makes it possible later).
- Weighted criteria or free-text interests.
- Editing AI models from the UI (they stay in the worker's env file).
- Measuring custom criteria automatically: a field is "not measured" until someone runs an eval for it.

## Architecture

```
Fields page / Settings ──> API (members/admins) ──> PostgreSQL (fields, field_versions, sources, settings)
Start run ──> API writes job ──> Worker builds domain.json (field version + enabled sources + limits)
          ──> pipeline child: research-agent --domain domain.json ──> run folder ──> importer ──> DB
Test criteria ──> API writes job (kind "criteria_test") ──> Worker: search + Jev only ──> job result
Worker start-up ──> checks each provider key (present / accepted) ──> worker_status rows (no values)
```

The pipeline never reads the web database; the API never holds provider keys. Both rules are unchanged.

## `domain.json` (the contract between web and pipeline)

```json
{
  "schema": 1,
  "field": {"id": "…", "name": "ML CT-FFR", "version": 3},
  "topic": "machine learning or deep learning estimation of CT-derived fractional flow reserve",
  "criteria": {
    "include": [{"key": "i1", "text": "The study uses machine learning or deep learning."}],
    "exclude": [{"key": "e1", "text": "The paper is a review, editorial or commentary without original results."}]
  },
  "sources": [
    {"name": "europepmc", "max_results": 100},
    {"name": "openalex", "max_results": 100, "contact": "research-team@example.org"}
  ],
  "years": {"from": 2018, "to": null},
  "thresholds": {"keep_min": 0.8, "include_fail_max": 0.05, "exclude_hit_min": 0.95, "exclude_clear_max": 0.2}
}
```

- Validated by a Pydantic model in `research_agent.schemas` (`DomainSpec`); unknown keys are refused.
- Criteria keys are generated (`i1…`, `e1…`) and stable within a version; texts ≤ 500 characters;
  at most 10 inclusion and 10 exclusion criteria.
- The CLI accepts either the existing positional topic (legacy: one `topic_match` question, today's
  behaviour) or `--domain FILE`. `domain.json` is copied into the run folder and recorded in the manifest.

## Pipeline changes

**Connectors** (`connectors.py`): `EuropePMC` gains a year filter; new `OpenAlex` (works search, abstract
rebuilt from `abstract_inverted_index`, polite-pool `mailto`) and `ArXiv` (Atom API, categories cs.CV,
eess.IV, physics.med-ph). Each returns the existing `Paper` shape with a `source` field. Every HTTP response
is cached in `research.sqlite` like Europe PMC today, retries and timeouts are the same, and a failed source
fails the run (fail closed). `deduplicate` merges by DOI, then by normalized title, keeping the list of
sources that found each paper.

**Screening** (`jev.py`, `agents.py`, `graph.py`):

- Jev asks one Noul question per criterion (inclusion: "is this true of the paper?"; exclusion: same form).
- Decision from Jev probabilities:
  - **drop** if any inclusion p ≤ `include_fail_max` (0.05) or any exclusion p ≥ `exclude_hit_min` (0.95);
    the deciding criterion is recorded;
  - **keep** if every inclusion p ≥ `keep_min` (0.8) and every exclusion p ≤ `exclude_clear_max` (0.2);
  - otherwise **escalate** to the LLM.
- The LLM screen prompt receives the topic and the criteria and returns, per criterion, `yes | no | unclear`
  plus, for every `no` on an inclusion criterion and every `yes` on an exclusion criterion, a quote from the
  abstract. Quotes go through the same `snap_evidence` / exact-substring check as claims. Final decision:
  drop if an inclusion criterion is `no` or an exclusion criterion is `yes`; keep if all are clearly
  satisfied; otherwise `uncertain` (kept, as today).
- `PROMPT_VERSION` bumps; old cached calls remain valid for old runs.
- `report.json` screens gain `criteria: {key: {jev_p, llm, quote}}` and `decided_by: "i1" | "e1" | null`.
- User-facing failure messages in `runner.py`, `jobs.py` and `ui.py` are translated to English.

**Eval harness**: `research-eval screen --field domain.json` screens a gold set with a field's criteria;
`report` is unchanged apart from reading per-criterion decisions. Existing gold sets and reports keep working.

## Data model changes (one Alembic migration)

| Table | Change |
|---|---|
| `fields` | add `archived_at`, `current_version` (int); `topic` no longer unique (moves to versions) |
| `field_versions` (new) | `field_id`, `version`, `name`, `topic`, `sources` (JSONB: names + year range), `note`, `created_by`, `created_at`; unique `(field_id, version)` |
| `criteria` | add `kind` (`include` / `exclude` / `legacy`), `field_version_id`; existing `topic_match` rows become `legacy` of version 1 |
| `runs` | add `field_version_id` (nullable for old imports, backfilled to v1) |
| `screenings` | add `decided_by` (criterion key or null) |
| `criterion_scores` | add `llm_answer` (`yes`/`no`/`unclear`/null), `quote` (text, null) |
| `sources` (new) | `name` (pk), `enabled`, `max_results`, `last_check_at`, `last_check_ok`, `last_check_ms`, `last_check_error` |
| `app_settings` (new) | single row: `contact_email` |
| `worker_status` (new) | `provider`, `model`, `key_present`, `key_accepted`, `checked_at`, `worker_id`; never a key value |

Importers read `domain.json` when present (else legacy), link the run to the matching field version
(creating one on import if the snapshot is unknown, marked `note = "imported"`), and store per-criterion
scores, LLM answers and quotes.

## API

| Verb and path | Purpose | Role |
|---|---|---|
| `GET /fields?archived=` | Fields with current version summary and last run | viewer |
| `GET /fields/{id}` | Current version with criteria and sources, plus version list | viewer |
| `GET /fields/{id}/versions/{n}` | One version (for history and diff) | viewer |
| `POST /fields` | Create (v1) | member |
| `POST /fields/{id}/versions` | Save a new version (body: full field + `note`; `base_version` for optimistic concurrency → 409 if stale) | member |
| `POST /fields/{id}/archive`, `/unarchive` | Archive / restore | admin |
| `POST /fields/{id}/test` | Enqueue a criteria test (Jev only, ≤ 20 papers, the draft version in the body so unsaved edits can be tested) | member |
| `GET /jobs/{id}` | Test results arrive in `progress.result` | member (creator or admin) |
| `GET /sources`, `PATCH /sources/{name}` | List / enable, limits | viewer / admin |
| `POST /sources/{name}/check` | Enqueue a connection check (worker; 1-result search) | admin |
| `GET /settings`, `PATCH /settings` | Contact email | viewer / admin |
| `GET /workers/status` | Provider key status per role | viewer |

`POST /runs` keeps its shape; it now uses the field's current version and the enabled sources, refuses a
field with no enabled source (422) and an archived field (409). Paper table gains filters
`decided_by=<key>` and `source=<name>`; rows gain `sources` and per-criterion cells.

Security unchanged: role guard on every route (the enumeration test covers new routes), CSRF on writes,
criteria text is plain text (rendered as text, length-limited), connection checks and criteria tests run
only in the worker, which holds the keys.

## Screens

1. **Fields (list):** name, topic, version with author and date, criteria counts, sources, last run,
   Start run; "show archived".
2. **Field editor:** name, topic, inclusion list (reorder, remove, add), exclusion list, sources (only
   enabled ones selectable) and year range, change note, **Save as vN+1**, **Test criteria**; side panel:
   version history with notes and a text diff between versions, runs per version, and the measurement
   status ("screening for this field: not measured" unless an eval exists for it).
3. **Test criteria results:** one row per paper, one column per criterion (Jev p), the decision and the
   criterion that decided, a summary (kept / dropped / to LLM); nothing is written to Papers.
4. **Settings → Sources / AI models / Users** as in the approved mockup; Users moves from the main menu.
5. **Papers:** "Topic match" becomes **Criteria** (names the deciding criterion, or "all met"); new filters
   "Dropped by criterion" and "Source"; run picker shows "field · vN".
6. **Drawer:** the Screen step is a per-criterion table (Jev p, LLM answer, quote) and names the decider.

Mockups: `.superpowers/brainstorm/69621-1790603513/content/` (`domain-editor.html`,
`settings-sources-en.html`, `screening-criteria.html`).

## Errors

- Saving with a stale `base_version` → 409 "This field changed since you opened it (now vN)"; the editor
  offers to reload.
- A disabled or failing source during a run → the run fails with `failed at stage 'discover': SourceUnavailable: <source>`;
  resume after the source is back.
- Criteria test failures (Jev key rejected, source down) show the job's sanitized error in the test panel.
- Worker start-up key check failure is shown on Settings → AI models; runs still start (and would fail
  clearly) so a transient provider outage does not block the queue.

## Testing

- **Pipeline:** `DomainSpec` validation; connectors against recorded fixture responses (no network);
  dedup across sources; the decision rule table-tested (keep / drop by inclusion / drop by exclusion /
  escalate); LLM per-criterion output with quote verification and retry on a mangled quote; legacy topic
  runs give byte-identical decisions to today on the existing demo fixtures; `research-eval --field` on a
  toy gold set.
- **Backend:** migration with backfill of existing data; field versioning and optimistic concurrency;
  archive rules and roles; sources and settings admin-only writes; criteria test job end to end with a fake
  Jev; worker status never contains a key (sentinel test); importer for `domain.json` runs; paper filters.
- **Frontend:** Vitest for the field editor (add, reorder, remove, validation, 409 reload), the test
  results table, Settings pages and read-only states, the Criteria cell and drawer table; Playwright flow:
  create a field → test criteria (fake Jev in the e2e server) → start a demo run → see decided-by in Papers;
  axe on the new pages.

## Plans

1. **Pipeline:** `DomainSpec`, connectors (OpenAlex, arXiv, year filter), multi-source dedup, per-criterion
   Jev and LLM screening, report fields, English messages, `research-eval --field`.
2. **Web backend:** migration and models, fields/versions/archive API, sources and settings API, worker
   jobs (criteria test, source check, start-up key check), `domain.json` at start run, importer changes,
   paper table filters.
3. **Frontend:** Fields list and editor, test results, Settings (Sources, AI models, Users), Papers and
   drawer changes, e2e and a11y.

## Success criteria

- A member creates a field with 3 inclusion and 2 exclusion criteria, tests it (Jev only), saves v2, and
  starts a run; Papers shows which criterion dropped each dropped paper, with a verified quote when the LLM
  decided.
- An admin enables arXiv, runs its connection check, and a new run of that field lists arXiv in "Found by".
- The existing mlffrct-2024 / aiffr-slr-2023 / live-01 data still imports and shows the same numbers.
- Settings → AI models shows a rejected key clearly, without ever showing the key.
