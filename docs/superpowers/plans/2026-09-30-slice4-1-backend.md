# Slice 4 · Plan 1: Backend + pipeline (keyword fields, assist, preview, team library) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fields defined by keywords (three groups) with per-source queries built deterministically in code,
an LLM "assist" that suggests keywords/synonyms/criteria, a free source preview, and a team library of saved
papers (collections, tags, notes, status, frozen evidence snapshot, CSV/BibTeX export) — the existing API
contracts only gain optional fields and legacy runs stay byte-identical.

**Architecture:** A pure module `research_agent.querybuild` turns `{all, any, none}` keywords into one query per
source. `DomainSpec` gains optional `description`, `keywords`, `queries`; when `queries` covers a source the
pipeline searches it with that raw query, and when it covers every source the plan node makes no LLM call.
Connectors gain `search_with_total` (papers, source-reported total, effective query) and a `raw` flag.
Migration `0004` adds the three field-version columns; migration `0005` adds the library tables. Two new worker
jobs: `field_assist` (one LLM call, role `assist`, cached in a persistent store) and `field_preview` (no LLM, ≤10
papers per source). A service module `web/library.py` owns snapshots, saving, events and export; a router
`api/routers/library.py` exposes it; the paper table and drawer gain an optional `library` ref.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2, Alembic, PostgreSQL 16 (`pgserver` in tests), httpx
MockTransport fixtures, pytest, ruff; `openapi-typescript` for `web/src/api/schema.d.ts`.

**Spec:** `docs/superpowers/specs/2026-09-30-keywords-library-ux-design.md` (sections 1, 2, Testing, Plans → 1).

---

## Decisions this plan takes (the spec left them open)

1. **Query syntax per source** (all terms cleaned first, see 2):
   - Europe PMC: `TITLE_ABS:t1 AND TITLE_ABS:"t 2" AND (TITLE_ABS:a1 OR TITLE_ABS:"a 2") NOT (TITLE_ABS:n1 OR …)`.
     Fielded terms instead of the spec's bare `(t1)` so that the search stays on title+abstract. A trailing `*`
     on a single-word term is kept (Europe PMC supports it).
   - OpenAlex: the same boolean without field prefixes (`"t 1" AND t2 AND (a1 OR a2) NOT (n1 OR n2)`), sent as
     `filter=title_and_abstract.search:<query>` (plus the year filters) instead of `search=`. Verified against the
     live API once (fixture `tests/fixtures/openalex_total.json`, meta.count 491). No wildcards.
   - arXiv: `abs:t1 AND abs:"t 2" AND (abs:a1 OR abs:a2) AND (cat:cs.CV OR cat:eess.IV OR cat:physics.med-ph)
     ANDNOT (abs:n1 OR abs:n2)`; the connector appends the year clause. No wildcards.
   - A single-term group has no parentheses. `none` terms without any `all`/`any` term is an error
     (`QueryError`, API 422 `no_keywords` "Add at least one keyword to 'All of' or 'Any of'").
2. **Term cleaning:** NFKC; the characters `" ( ) [ ] { } : \ ^ ~ , ; < > | & ! ? = + /` become spaces; `*`
   survives only as the last character of a single word (Europe PMC); whitespace collapsed; empty terms dropped;
   case-insensitive duplicates dropped (first spelling kept). A term is bare only when it matches `^\w+\*?$` and
   is not an operator word (`AND OR NOT ANDNOT TO`); otherwise it is quoted. A built query longer than 2000
   characters is a `QueryError`.
3. **Overrides** (`query_override {europepmc?, openalex?, arxiv?}`) replace the built query for that source,
   used verbatim (≤ 2000 chars, plain text; an OpenAlex override may not contain `,`, which separates OpenAlex
   filters → 422). With keywords, every enabled source gets a query (override or built). Without keywords, only
   overridden sources get one and the others are planned by the LLM as before.
4. **Years are not part of the built query**; the connectors add them exactly as today (Europe PMC `PUB_YEAR`,
   OpenAlex date filters, arXiv `submittedDate`). Preview returns both the built query and the effective query
   the source received.
5. **DomainSpec additions are dropped from dumps when null** (wrap serializer), so legacy `domain.json`,
   `report.json` and cache keys are byte-identical. `queries` keys must be sources of the spec.
6. **Pipeline:** `MultiSource(sources, raw={name: query})`; `search()` skips raw sources, `search_raw()` searches
   them once each with their own `max_results`. The plan node makes no LLM call when every source has a raw query
   and records `{"queries": [], "rationale": "...", "source_queries": {...}}`; the report lists the source queries.
7. **Field-version storage:** `description` (text, default ""), `keywords` (JSONB or null when every group is
   empty), `query_override` (JSONB of the non-empty overrides, or null). Content matching for imported runs also
   compares keywords (null = none), so legacy runs link exactly as before.
8. **Assist:** role `assist`, its own system prompt and instruction (not in `INSTRUCTIONS`, so worker key checks,
   `live_models` and `PROMPT_VERSION` are unchanged → existing runs still resume). Model from
   `RESEARCH_ASSIST_MODEL`, else `RESEARCH_MODEL`. Calls are cached in a persistent store under
   `RESEARCH_CACHE_DIR` (default `<project>/cache`, gitignored) `/assist/research.sqlite`; demo mode is
   deterministic and needs no key.
9. **Preview** runs in the worker as job `field_preview` (the worker is the only process that talks to sources);
   ≤ 10 papers per source; a failing source reports `error` without failing the others. Rate limit: 10 previews
   per user per 60 s, in-process (`RateLimiter`) → 429 `rate_limited`. Preview and assist also count toward the
   active-jobs cap (429 `too_many_active_runs`). Known limitation: with one worker a preview waits behind a
   running research job.
10. **Library search:** `q` uses ILIKE over title, abstract and note (every whitespace-separated word must match
    one of them; `%`, `_`, `\` escaped). Chosen over PostgreSQL full-text search because the library is small
    (hundreds to a few thousand items), users type partial words and mixed Romanian/English text, and ILIKE needs
    no text-search configuration or index maintenance. Revisit with pg_trgm if it grows past ~50k items.
11. **Library schema:** `collections` (name unique case-insensitively among all collections, 409 `name_taken`),
    `library_items` (paper unique; denormalized `field_id`, `run_id`, `score`, `red_flag_count` from the
    snapshot for filtering/sorting), `library_item_collections`, `library_tags` (lower-case, unique),
    `library_item_tags`, `library_events` (kind `added|status|note|tags|collections|snapshot|resaved`, detail JSON).
12. **Save is idempotent:** papers already in the library keep status/note/snapshot; requested collections and
    tags are merged (event only when something changed) and the item is reported in `existing`. Response 201 when
    at least one item was created, else 200. Every paper must belong to the run (422 `not_in_run`). Archived
    collections cannot receive items (422 `archived_collection`).
13. **Snapshot** = the drawer data at save time, trimmed: paper (+abstract), run (id, kind, dates), field
    (id, name, version), screening (decision, tier, reason, decided_by, criteria table), rank, panel (score,
    coverage, red_flag_count, text_source, editor verdict/reason, red flags text/source, reviewer key/name/version/
    verdict/score/summary), file refs (id, sha256, filename), `taken_at`, `schema: 1`.
14. **Permissions:** viewer reads the library, collections and export; member saves, patches, updates snapshots,
    creates/renames collections; delete = the adder or an admin (403 `not_owner`); archive/restore collection =
    admin.
15. **Export:** `GET /library/export?format=csv|bibtex` + the list filters, at most 5000 items, attachment.
    CSV cells beginning with `= + - @ \t \r` get a leading `'`. BibTeX escapes `\ { } & % $ # _ ~ ^`, strips
    control characters, keys `ra_<source id alnum>` (unique by suffix).

## File structure

| File | Responsibility |
|---|---|
| `src/research_agent/querybuild.py` (new) | term cleaning, per-source queries, overrides |
| `src/research_agent/connectors.py` | `SearchResult`, `search_with_total`, `raw`, `MultiSource.search_raw` |
| `src/research_agent/schemas.py` | `Keywords`, DomainSpec additions, `FieldSuggestions` |
| `src/research_agent/graph.py`, `report.py`, `web/checks.py` | raw queries: no plan call, discover, criteria test |
| `src/research_agent/agents.py` | `assist` role (instruction, system, demo) |
| `src/research_agent/web/db/models.py`, `migrations/versions/0004_field_keywords.py`, `0005_library.py` | schema |
| `src/research_agent/web/fields.py`, `api/routers/fields.py`, `api/schemas.py` | keywords in versions, assist and preview endpoints |
| `src/research_agent/web/assist.py`, `web/preview.py` (new), `web/worker.py`, `web/settings.py` | worker jobs, cache dir |
| `src/research_agent/web/library.py` (new), `api/routers/library.py` (new) | library service + API + export |
| `src/research_agent/web/papers.py`, `api/routers/papers.py` | `library` ref on rows and drawer |
| tests: `test_querybuild.py`, `test_connectors_total.py`, `test_domain_queries.py`, `test_web_field_keywords.py`, `test_web_assist.py`, `test_web_preview.py`, `test_web_library.py`, `test_web_library_export.py`, `test_web_guards.py`, `test_web_db.py` | |
| `docs/web-app.md`, `web/src/api/schema.d.ts`, `.gitignore` | docs, regenerated types |

Before every commit: `. .venv/bin/activate && ruff format src tests && ruff check . && pytest -q` (green).
Stage exact files. Commit with `-m "<subject>" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"`.

---

### Task 1: `research_agent.querybuild`

**Files:** Create `src/research_agent/querybuild.py`, `tests/test_querybuild.py`.

- [ ] **Step 1: failing table tests**

```python
import pytest
from research_agent.querybuild import QueryError, build, build_queries, check_override, clean_term, normalize_keywords

CASES = [
    ("europepmc", {"all": ["CT"], "any": [], "none": []}, "TITLE_ABS:CT"),
    ("europepmc", {"all": ["coronary angiography", "deep learning"], "any": ["segment*", "U-Net"], "none": ["review"]},
     'TITLE_ABS:"coronary angiography" AND TITLE_ABS:"deep learning" AND (TITLE_ABS:segment* OR TITLE_ABS:"U-Net") NOT TITLE_ABS:review'),
    ("openalex", {"all": ["deep learning"], "any": ["CT", "MRI"], "none": ["review", "case report"]},
     '"deep learning" AND (CT OR MRI) NOT (review OR "case report")'),
    ("arxiv", {"all": ["deep learning"], "any": ["CT"], "none": ["survey"]},
     'abs:"deep learning" AND abs:CT AND (cat:cs.CV OR cat:eess.IV OR cat:physics.med-ph) ANDNOT abs:survey'),
]

@pytest.mark.parametrize("source,keywords,expected", CASES)
def test_build(source, keywords, expected):
    assert build(source, keywords) == expected
```
plus: quotes/brackets/colons stripped (`'x" OR 1:(y)'` → `"x OR 1 y"` quoted), operator words quoted (`AND` →
`"AND"`), wildcard dropped for openalex/arxiv and inside phrases, duplicates case-insensitive, empty terms
dropped, none-only → `QueryError`, too long → `QueryError`, `build_queries` with overrides (override wins; without
keywords only overridden sources), `check_override("openalex", "a,b")` raises, `normalize_keywords` returns
`None` for all-empty.

- [ ] **Step 2:** `pytest tests/test_querybuild.py -q` → FAIL (module missing).
- [ ] **Step 3: implement** (complete module)

```python
"""Per-source search queries from a field's keywords. Deterministic code, no model involved."""
import re
import unicodedata

SOURCES = ("europepmc", "openalex", "arxiv")
GROUPS = ("all", "any", "none")
ARXIV_CATEGORIES = ("cs.CV", "eess.IV", "physics.med-ph")
MAX_QUERY = 2000
SYNTAX = re.compile(r'["()\[\]{}:\\^~,;<>|&!?=+/]')
BARE = re.compile(r"^\w+\*?$")
OPERATORS = {"AND", "OR", "NOT", "ANDNOT", "TO"}
WILDCARDS = {"europepmc"}
PREFIX = {"europepmc": "TITLE_ABS:", "openalex": "", "arxiv": "abs:"}

class QueryError(ValueError): ...

def clean_term(term, wildcard=False): ...          # decision 2
def normalize_keywords(keywords): ...               # {"all","any","none"} cleaned (no wildcard rules) or None
def has_terms(keywords): ...
def build(source, keywords): ...                   # decision 1
def check_override(source, text): ...              # returns stripped text or raises QueryError
def build_queries(keywords, sources, overrides=None): ...  # {source: query}
```
(the executed version is in the commit; every rule above has a test.)
- [ ] **Step 4:** tests pass. **Step 5:** commit `querybuild: deterministic per-source queries from keyword groups`.

### Task 2: Connectors report totals and accept raw queries

**Files:** Modify `connectors.py`; create `tests/test_connectors_total.py`; fixtures `tests/fixtures/{europepmc_total.json, openalex_total.json, arxiv_total.xml}` (recorded once from the public APIs, 2 results each).

`SearchResult = NamedTuple(papers, total, query)`. `EuropePMC.search_with_total(query, limit, raw=False)` →
total `hitCount`; `OpenAlex` raw → `filter=title_and_abstract.search:<q>[,from_…,to_…]`, no `search`, total
`meta.count`; `ArXiv` raw → `<q> AND submittedDate:[…]` (years only), total `opensearch:totalResults`;
`DemoConnector` total = len. `search()` = `search_with_total(...).papers` (unchanged requests for existing
callers). `MultiSource(sources, raw=None)`, `search_raw()`; `domain_connector` passes `domain.queries`.

Tests: each fixture parses to 2 papers with totals 258 / 491 / 26; request params for raw mode per source (years
included); non-raw requests unchanged (existing tests); MultiSource skips raw sources in `search` and searches
only them in `search_raw`; a missing total → `None` for Europe PMC when `hitCount` is absent.

Commit: `Connectors: source-reported totals and raw queries`.

### Task 3: DomainSpec additions and the pipeline

**Files:** Modify `schemas.py` (`Keywords`, DomainSpec `description`/`keywords`/`queries`, serializer), `graph.py`
(plan/discover), `report.py` (source queries), `web/checks.py` (criteria test uses queries); create
`tests/test_domain_queries.py`.

Tests: old domain.json validates and dumps without the new keys; unknown source in `queries` → invalid; demo run
with `queries` for every source → no `plan` call in `research.sqlite`, provenance query = the raw query,
`plan.source_queries` present; with queries for one of two sources → plan call made, raw source searched once;
existing characterization tests unchanged; criteria test with queries sends them raw (MockTransport).

Commit: `Field runs search with keyword-built queries and skip planning for them`.

### Task 4: Field versions with description, keywords, overrides (migration 0004)

**Files:** Create `0004_field_keywords.py`, `tests/test_web_field_keywords.py`; Modify `models.py`, `fields.py`,
`api/schemas.py`, `api/routers/fields.py`, `api/routers/runs.py` (no change needed beyond build_domain),
`tests/test_web_db.py` untouched (no new table).

API additions (all optional): `FieldDraft.description` (≤ 2000, text), `.keywords {all, any, none}` (each term
1–80, ≤ 20 per group), `.query_override {europepmc?, openalex?, arxiv?}`; `FieldVersionOut.description`,
`.keywords`, `.query_override`, `.queries` (built for the version's sources; null when none). `build_domain`
adds `description`, `keywords`, `queries`; `QueryError` → 422 `no_keywords`.

Tests: create with keywords → version stores normalized keywords; GET returns them and `queries`; old version
(no keywords) returns `description ""`, `keywords null`, `queries null`; none-only keywords → 422; OpenAlex
override with comma → 422; POST /runs stores `domain_request.queries` for enabled sources (override wins);
criteria test payload has queries; importing a run whose domain has keywords links to the version with the same
keywords; legacy import unchanged; migration upgrade/downgrade 0003↔0004.

Commit: `Field versions keep a description, keywords and query overrides; runs get built queries`.

### Task 5: `field_assist` job and `POST /fields/assist`

**Files:** Modify `schemas.py` (`KeywordSuggestion`, `FieldSuggestions`), `agents.py` (assist), `web/settings.py`
(`cache_dir`), `web/worker.py`, `api/routers/fields.py`, `api/schemas.py`, `.gitignore`; create `web/assist.py`,
`tests/test_web_assist.py`.

Tests: demo suggestions deterministic and schema-valid (2–6 include, ≤ 4 exclude); same input twice → one cached
call; live without a model → job fails "Set RESEARCH_ASSIST_MODEL or RESEARCH_MODEL in the worker"; live with a
stub chat model (monkeypatched `init_chat_model`) → suggestions; API: member 202 JobOut kind `field_assist`;
viewer 403; empty body → 422 `nothing_to_assist`; demo refused when demo is disabled; worker end-to-end (world
fixture) → `progress.result.suggestions`.

Commit: `Field assist: suggested keywords, synonyms and criteria from one cached call`.

### Task 6: `field_preview` job and `POST /fields/preview`

**Files:** Create `web/preview.py`, `tests/test_web_preview.py`; Modify `web/worker.py`, `api/routers/fields.py`,
`api/schemas.py`, `api/app.py` (`preview_limiter`).

Tests: preview function with MockTransport returns per source `{source, query, effective_query, count,
papers≤10, error}`; one source failing reports `error` and the others still work; demo mode offline; API 202 with
queries in the payload; 11th preview within a minute → 429 `rate_limited`; no enabled source → 422; no keywords →
422 `no_keywords`; worker end-to-end in demo.

Commit: `Field preview: source counts and first titles for a draft, no model involved`.

### Task 7: Library schema (migration 0005)

**Files:** Create `0005_library.py`; Modify `models.py`, `tests/test_web_db.py` (TABLES).

Tables per decision 11. Tests: drift check green; upgrade/downgrade 0004↔0005; unique paper.

Commit: `Migration 0005: team library tables`.

### Task 8: Library service and API

**Files:** Create `web/library.py`, `api/routers/library.py`, `tests/test_web_library.py`; Modify `api/app.py`,
`api/schemas.py`.

Service: `build_snapshot(db, run, paper)`, `save(db, user, body)`, `update(db, item, user, patch)`,
`refresh_snapshot(db, item, run, user)`, `search(db, filters)`, `normalize_tag`, `record_event`.

Tests: save 2 papers of the demo run into a new collection with tags → 201, snapshot has paper/abstract/
screening/field/run; save again with another collection and tag → 200, `existing` lists both, collections and
tags merged, status unchanged, events recorded; paper not in run → 422; filters q/status/collection/tag/field/
min_score/has_red_flags; sorts; paging; PATCH status/note/tags/collections with events; archived collection →
422; DELETE by another member → 403, by adder → 204, by admin → 204; snapshot refresh from another run; collections
create/rename (409 on duplicate name, case-insensitive), archive/restore admin only; viewer reads.

Commit: `Team library: collections, tags, notes, status, snapshots and history`.

### Task 9: Export

**Files:** Modify `web/library.py`, `api/routers/library.py`; create `tests/test_web_library_export.py`.

Tests: CSV header + rows, injection-safe (`=cmd` → `'=cmd`), filters honoured; BibTeX escaping (`{}%&_#$~^\`),
unique keys, attachment headers; unknown format → 422.

Commit: `Library export as CSV and BibTeX`.

### Task 10: Paper table and drawer `library` ref; guards; types; docs

**Files:** Modify `web/papers.py`, `api/routers/papers.py`, `api/schemas.py` (`LibraryRef`, `PaperRow.library`,
`DrawerOut.library`), `tests/test_web_guards.py` (matrix), `docs/web-app.md`, `web/src/api/schema.d.ts`
(regenerated with `cd web && npm run gen:api`).

Tests: rows of saved papers carry `{item_id, status, collections}`, others `null`; drawer likewise; guard
matrix lists every new route; `cd web && npm run typecheck && npm test` green.

Commit: `Papers and drawer show library state; guards, types and docs for slice 4 backend`.

---

## Self-review

- Spec 1 (description/keywords/overrides, builder per source, domain queries skip planning, assist, preview):
  Tasks 1–6. Spec 2 (tables, snapshot, API, export, table/drawer refs): Tasks 7–10. Testing section: table
  tests (1), DomainSpec compatibility (3), assist/preview with fakes (5, 6), library roles/filters/export/
  snapshot/idempotent save/events (8, 9). Frontend and e2e belong to plan 2.
- Names used across tasks: `build_queries`, `QueryError`, `SearchResult`, `search_with_total(raw=)`,
  `MultiSource.search_raw`, `field_assist`, `field_preview`, `LibraryRef`, `build_snapshot` — consistent.
