# Partial search — design

Date: 2026-10-06 · branch `feat/papers-groups` · status: implemented

## Problem
Field runs failed at `discover` with `SourceUnavailable: semantic_scholar` whenever one source (here the
keyless Semantic Scholar pool, HTTP 429) did not answer, even though the other sources returned records.

## Rule
Fail closed, except optional search sources: a failing optional source is skipped with a recorded, visible
warning. The run still fails when **every** source fails or when a source marked `required: true` fails.
Screening, citations, schema and model errors stay fail-closed.

## Pipeline
- `SourceUnavailable` gains `reason`, a short safe text set by `fetch()` from the failure:
  `rate limited (HTTP 429)`, `server error (HTTP 5xx)`, `request refused (HTTP 4xx)`, `timed out`,
  `network error`, `unreadable response`. `SourceKeyMissing` has reason `API key missing`.
  No URL, header or body ever reaches the reason.
- `MultiSource` tries each source independently. On `SourceUnavailable` (incl. `SourceKeyMissing`) the
  source is skipped for the rest of the discover stage; records it returned before failing are kept.
  A `required` source re-raises at once. `check()` (called at the end of `discover`) raises
  `AllSourcesFailed` ("No search source answered: a (reason); b (reason)") when every source was skipped;
  with a single source it re-raises that source's own exception, so single-source and legacy runs fail
  exactly as before. Legacy topic runs (plain `EuropePMC`/`DemoConnector`) are unchanged.
- `SourceSpec.required: bool = False`; omitted from dumps when false, so old `domain.json` files, reports
  and anything keyed on them are unchanged.
- State / `report.json` (`state`): `search_warnings: [{source, error_type, reason, detail}]`,
  `sources_used`, `sources_skipped` (field runs only). `detail` is the fix: the env var to set
  (`Set S2_API_KEY in the worker environment …`) or "check Settings → Sources and retry later".
- `progress.json` gets the same three keys as soon as `discover` finishes (and `search_warnings` on an
  all-sources failure); `manifest.json` gets `search: {...}` at the end. `report.md` prints a
  "Partial search" line.
- **Stage status decision:** `discover` stays `completed`; the warnings travel as a separate list. No new
  status value, so every existing stage renderer, filter and test keeps working; the UI reads the list.
- Source check and field preview use the same wording via `connectors.describe()`:
  `SourceUnavailable: <source> — <reason>` (a missing key keeps `<source>: set VAR in the worker environment`).

## Web
- Field versions: per-source `required` is part of the stored `sources` JSON (no column; the JSON already
  holds `{name, max_results, contact}`), validated by `SourceSpec`; the editor's sources step has a
  "Required" toggle per selected source (default off; the hint suggests turning it on for Europe PMC).
- Runs: `search_warnings` JSON column on `runs` (migration), filled by the importer from `report.json`
  state or `progress.json`. `RunOut`/`RunDetailOut` expose optional `search_warnings`.
- Runs list: "⚠ Partial search" marker (icon + words) with a tooltip listing skipped sources and reasons.
- Run detail: warning panel listing each skipped source, the reason and the fix, with a link to
  Settings → Sources.
- Papers page: dismissible banner "Partial search: Semantic Scholar skipped (rate limited). Results may be
  missing papers from this source." (dismissal per run, session only).
- Evals: only where a run is the input (run-based reports); screening evals use gold sets and get no caveat.
