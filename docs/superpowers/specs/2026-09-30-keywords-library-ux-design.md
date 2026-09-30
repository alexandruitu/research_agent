# Keyword fields, team library and a UX pass: design (web app slice 4)

Date: 2026-09-30 · Status: approved in brainstorming (user: no more questions; make the tool a pleasure to use)

## Goals

1. **Define a field easily**: optional free-text description → suggested keywords and criteria; keywords in
   three groups; synonyms suggested; per-source queries built in code; free Preview before any paid run.
2. **Team library**: save papers users choose after reading, into collections, with tags, notes, a team
   status (to read → read → relevant / rejected) and a frozen snapshot of the evidence at save time.
3. **UX pass over the whole app** with the frontend-design skill: easier, calmer, more pleasant; no feature
   removed, no contract broken.

## 1. Keyword fields

**Field version gains** (all optional, old versions keep working):
`description` (≤ 2000), `keywords: {all: [..], any: [..], none: [..]}` (each term 1–80 chars, ≤ 20 per group),
`query_override: {europepmc?, openalex?, arxiv?} | null`.

**Query builder (code, `research_agent.querybuild`)**: deterministic per-source query from keywords and years:
- Europe PMC: `(t1) AND (t2) AND (a1 OR a2) NOT (n1 OR n2)` with phrases quoted, fields TITLE_ABS;
- OpenAlex: `search` with the same boolean in `title_and_abstract.search` filter;
- arXiv: `abs:"t1" AND abs:"t2" AND (abs:a1 OR abs:a2) ANDNOT ...` plus categories.
Overrides replace the built query for that source. The pipeline receives the final queries in `domain.json`
(`queries: {source: str}`); when present, the plan step is skipped for those sources (planning by LLM stays for
legacy topic runs). `DomainSpec` accepts `keywords`, `description`, `queries` additively.

**Assist (worker job `field_assist`, one cheap LLM call, role `assist`)**: input = description and/or current
keywords; output = suggested keywords per group, synonyms per keyword, and 2–6 inclusion / 0–4 exclusion
criteria sentences. Suggestions are never auto-applied: the user accepts each (chip click / "accept all").
Cached like other calls; demo mode returns deterministic suggestions.

**Preview (API, no LLM, no key)**: `POST /fields/preview` with the draft → runs the built queries against
enabled sources with a small limit through the worker (job `field_preview`), returns per source: count (as
reported by the source), first 10 titles/years/ids, and the exact query used. Rate-limited per user.

## 2. Team library

Tables: `collections` (name, description, created_by, archived_at), `library_items` (paper_id unique,
status `to_read|read|relevant|rejected`, added_by, added_at, note, snapshot JSONB), `library_item_collections`
(M:N), `library_tags` / item tags (free-text, normalized lower-case), `library_events` (who changed status,
note, collections, tags, when).

**Snapshot at save**: paper metadata + abstract, source run/field version, screening decision and criteria,
panel score, editor verdict, red flags and reviewer summaries from that run, text_source; uploaded PDFs are
linked (paper_files already stored by hash). Re-saving from a newer run offers "update snapshot".

API: `GET /library` (filters: q full-text over title/abstract/note, collection, status, tag, field, min_score,
has_red_flags; sort; paging), `POST /library` (one or many paper ids from a run → items, optional
collection/tags/note/status), `PATCH /library/{id}` (status, note, tags, collections), `DELETE` (admin or
adder), `GET /library/{id}` (item + events), collections CRUD (member create/rename, admin archive),
`GET /library/export?format=csv|bibtex` (current filters). Paper table rows and drawer gain optional
`library: {item_id, status, collections[]} | null` so runs show "In library · relevant".

## 3. UX pass (frontend-design skill; applies to every page)

Principles: one primary action per screen; progressive disclosure (advanced options folded); plain words,
no jargon without an inline explanation; instant feedback (optimistic updates with undo toasts for
save-to-library, status, tags); empty states that teach the next step; keyboard shortcuts on Papers and
Library (j/k move, o open, s save, 1–4 status) with a "?" help sheet; consistent spacing/typography scale;
calmer colour usage (status by words + icons); loading skeletons instead of "Loading…"; confirmations only
for destructive actions; everything reachable in ≤ 2 clicks from Papers.

Specific: a **Home / onboarding** entry when there is no run ("Create your first field in 3 steps");
Fields editor as a 3-step flow (Describe → Keywords & criteria → Preview & save) with a live summary panel;
Papers: bulk select + "Save to library", saved-state badge, cleaner filter bar with active-filter chips and
"clear all"; drawer: sticky header with Save / status buttons; Library: list + reading pane layout.
The skill may propose further improvements; each must keep accessibility (axe clean, keyboard, no colour-only
state) and the CSP rules (no inline styles, no injected HTML).

## Testing

Query builder table tests per source (quoting, escaping, empty groups, overrides); DomainSpec additive
compatibility; assist and preview jobs with fakes; library API (roles, filters, export formats, snapshot
contents, idempotent save, events); frontend Vitest for the new editor steps, library page, bulk save,
shortcuts; Playwright: describe → accept suggestions → preview → save → demo run → save 2 papers to a
collection → set status → find them in Library → export; axe on all changed pages.

## Plans

1. Backend + pipeline: querybuild, DomainSpec additions, assist/preview jobs, library schema + API, importer
   and table/drawer additions.
2. Frontend: field editor flow, Library page, Papers/drawer integration, app-wide UX pass, e2e + a11y.
