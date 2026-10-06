# Slice 8 — Papers tab quality groups Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Group a run's papers into collapsible, rule-explained sections (Read first / Worth a look / Has problems / Not relevant / Not reviewed, or by source/year/criterion/library status), with a narrower title column and readable criteria values.

**Architecture:** The group of a paper is a SQL `CASE` expression built next to the existing paper-table query (`research_agent/web/papers.py`), so filtering (`group_by` + `group`) and counting (`/papers/groups`) reuse the same filtered statement. The frontend renders one `PaperTable` per group, each paging independently ("Show more"), with the open/closed state in `localStorage`.

**Tech Stack:** FastAPI + SQLAlchemy (PostgreSQL), pytest; React 18 + TanStack Query + Vitest + Testing Library.

Spec: `docs/superpowers/specs/2026-10-06-papers-groups-design.md`.

**Testing rule (user):** no full suites. Run only the test files touched, plus `ruff check .` and `cd web && npm run typecheck && npm run lint`.

## Decisions (taken without questions, per the user)
- Legacy A/B verdict = adjudicator verdict, else A when A = B, else `uncertain` when both present and disagree, else none.
- Legacy runs have no red-flag check: they can be "Worth a look" or "Has problems" (verdict exclude), never "Read first".
- Fifth group "Not reviewed": kept with no verdict, and never-screened papers (no abstract). Listed only when non-empty.
- Order of evaluation: not_relevant → has_problems → read_first → worth_a_look → not_reviewed.
- Groups honour every active filter (counts and rows).
- Default sort inside groups: score desc (nulls last) when the URL has no `sort`; flat view keeps title asc.
- Sections page 25 rows at a time with "Show more" (appends); the global pager is shown only in the flat view.
- Collapsed state key: `papers.collapsed.<userId>.<groupBy>`; "Not relevant" starts collapsed.
- `group` URL param: absent = quality, `none` = flat; values `source|year|decided_by|library`.

## File structure
- Modify `src/research_agent/web/papers.py` — `group_expr()`, `QUALITY_GROUPS`, `paper_groups()`, `group` in rows, filter in `paper_table`.
- Modify `src/research_agent/web/api/routers/papers.py` — shared filter dependency, `group_by`/`group` params, `GET /{run_id}/papers/groups`.
- Modify `src/research_agent/web/api/schemas.py` — `PaperRow.group`, `PaperGroupOut`.
- Create `tests/test_web_paper_groups.py`.
- Regenerate `web/src/api/schema.d.ts`; modify `web/src/api/types.ts`, `web/src/api/hooks.ts`.
- Create `web/src/features/papers/groups.ts` (+ `groups.test.ts`): icons, collapsed-state storage.
- Create `web/src/features/papers/PaperGroups.tsx` (+ `groups.test.tsx`): sections.
- Modify `cells.tsx` (`CriteriaValues`), `PaperTable.tsx` (title clamp, abstract-only marker), `papersState.ts`, `PapersPage.tsx`, `styles.css`.
- Modify `docs/web-app.md`.

---

### Task 1: Backend — quality group expression, `group` on rows, group filter

**Files:** Modify `src/research_agent/web/papers.py`, `src/research_agent/web/api/schemas.py`, `src/research_agent/web/api/routers/papers.py`; Test `tests/test_web_paper_groups.py`.

- [ ] **Step 1: failing tests** (`tests/test_web_paper_groups.py`)

```python
def rows(client, run_id, **params):
    r = client.get(f"/api/v1/runs/{run_id}/papers", params={"page_size": 50, **params})
    assert r.status_code == 200, r.text
    return {x["paper"]["source_id"]: x for x in r.json()["items"]}

def review(db, run_id, source_id, verdict, flags):  # a panel review on one paper
    paper = db.scalar(select(Paper).where(Paper.source_id == source_id))
    db.add(PaperReview(run_id=run_id, paper_id=paper.id, text_source="abstract",
                       editor_verdict=verdict, red_flag_count=flags, score=50.0))
    db.commit()

def test_legacy_rows_are_grouped_by_their_a_b_verdicts(sign_in, imported): ...
def test_panel_rows_use_the_editor_verdict_and_red_flags(sign_in, imported, db): ...
def test_filtering_on_one_group(sign_in, imported): ...
```
(complete tests in the test file; they assert: eval MED:5 → not_relevant; legacy kept include → worth_a_look never read_first;
panel include+0 → read_first, include+1 → worth_a_look, include+2 → has_problems, exclude → has_problems, null verdict → not_reviewed;
`group_by=quality&group=not_relevant` total equals `decision=exclude` total.)

- [ ] **Step 2:** `pytest tests/test_web_paper_groups.py -q` → FAIL (no `group` key).
- [ ] **Step 3: implement** in `papers.py`:

```python
QUALITY_GROUPS = (
    ("read_first", "Read first", "Kept by screening, editor verdict include and 0 red flags."),
    ("worth_a_look", "Worth a look", "Kept, verdict include or uncertain, at most 1 red flag (or red flags not checked: legacy A/B runs)."),
    ("has_problems", "Has problems", "Kept, but 2 or more red flags or verdict exclude."),
    ("not_relevant", "Not relevant", "Dropped by screening; the row names the criterion that dropped it."),
    ("not_reviewed", "Not reviewed", "Kept (or never screened: no abstract) but no review verdict yet."),
)

def quality_expr(ra, rb, rj):
    legacy = case((rj.verdict.is_not(None), rj.verdict),
                  (and_(ra.verdict.is_not(None), ra.verdict == rb.verdict), ra.verdict),
                  (and_(ra.verdict.is_not(None), rb.verdict.is_not(None)), literal("uncertain")))
    verdict = case((PaperReview.id.is_not(None), PaperReview.editor_verdict), else_=legacy)
    flags = PaperReview.red_flag_count  # null: no panel review, red flags not checked
    return case(
        (and_(Screening.decision == "exclude", Screening.tier != NOT_SCREENED), literal("not_relevant")),
        (or_(flags >= 2, verdict == "exclude"), literal("has_problems")),
        (and_(verdict == "include", flags == 0), literal("read_first")),
        (and_(verdict.in_(["include", "uncertain"]), or_(flags.is_(None), flags <= 1)), literal("worth_a_look")),
        else_=literal("not_reviewed"))
```
Select it as a column in `paper_table`, put it on each row (`"group": group`), add `PaperQuery.group_by="quality"`, `PaperQuery.group=None` and `stmt.where(expr == q.group)`.
Schema: `PaperRow.group: str | None = None` added to `ADDED`. Router: `group_by: Literal["quality","source","year","decided_by","library"] = "quality"`, `group: str | None = Query(None, pattern=r"^[a-z0-9_]{1,100}$")`.
- [ ] **Step 4:** run the file → PASS; `ruff check .`.
- [ ] **Step 5:** commit `papers.py schemas.py routers/papers.py tests/test_web_paper_groups.py`.

### Task 2: Backend — other dimensions and `GET /runs/{id}/papers/groups`

**Files:** same.

- [ ] **Step 1: failing tests:** groups endpoint for `by=quality` returns the 4 main groups in order with counts summing to total; `not_reviewed` absent when 0; `by=year` keys are years + `none`; `by=decided_by` has `kept` and the dropping criterion; `by=library` all `not_saved` until a paper is saved; `by=source` on research run has `demo`; filtering `group_by=year&group=<y>` matches counts; filters (`decision=exclude`) narrow counts; 404 on unknown run; 422 on unknown `by`.
- [ ] **Step 2:** run → FAIL (404 route).
- [ ] **Step 3: implement** `group_key(dim, ...)` per dimension (year: `coalesce(cast(Paper.year, String), 'none')`; decided_by: `case(rule→'not_screened', exclude→coalesce(decided_by,'unattributed'), else 'kept')`; library: outer join `LibraryItem` on paper id, `coalesce(status,'not_saved')`; source: membership filter `sources.contains([key])` / `cardinality = 0` for `none`, counts via `func.unnest`). Refactor `paper_table` into `_filtered(db, run, q)` returning `(stmt, columns)`; `paper_groups(db, run, q, by)` counts with `GROUP BY`. Labels: quality from `QUALITY_GROUPS`; criterion keys as-is (frontend labels them); `none`→"Unknown"/"No source"; rules: one sentence per dimension. Router: a `paper_filters` dependency shared by both endpoints; route `/{run_id}/papers/groups` declared before `/{run_id}/papers/{paper_id}`. Schema `PaperGroupOut{key,label,count,rule}`.
- [ ] **Step 4:** run → PASS; ruff.
- [ ] **Step 5:** commit.

### Task 3: Frontend API layer

- [ ] `npm run gen:api` (venv active) → `schema.d.ts`; add `PaperGroupOut` to `types.ts`; `PaperParams.group_by?/group?`; `usePaperGroups(runId, by, params)` (key `["paper-groups", runId, by, params]`), invalidated together with papers (prefix `papers`… use key `["papers", runId, "groups", by, params]` so existing `invalidateQueries(["papers"])` covers it).
- [ ] typecheck; commit.

### Task 4: Group helpers (pure) — `groups.ts` + `groups.test.ts`

```ts
export const GROUP_BYS = ["quality", "source", "year", "decided_by", "library", "none"] as const;
export const QUALITY_ICON: Record<string, string> = { read_first: "★", worth_a_look: "◐", has_problems: "⚑", not_relevant: "⊘", not_reviewed: "○" };
export function readCollapsed(userId, by): Set<string>  // try/catch; default {not_relevant} for quality
export function writeCollapsed(userId, by, keys): void   // try/catch
export function groupLabel(by, group): string            // criterion/source/library labels
```
Tests: defaults, round-trip, a throwing `localStorage` returns defaults and does not throw. Run `npx vitest run src/features/papers/groups.test.ts`. Commit.

### Task 5: URL state — `papersState.ts`

`parseView` returns `groupBy` (`group` param; default `quality`); in grouped mode with no `sort` param: `sort=score, direction=desc`. `patchView` accepts `group`. Tests in `papersState.test.ts`. Commit.

### Task 6: Readable cells — title clamp, abstract-only marker, criteria values

`CriteriaValues` in `cells.tsx`: `<ul class="crit-values">` one `<li>` per key with `criterionLabel(key)` and `p 0.83` / `LLM yes`; decider gets `◆ decided` text. `PaperTable`: title button `className="title-clamp" title={full}`; `abstract only` chip when `text_source === "abstract"`; colgroup widths (paper 22rem max). Tests in `cells.test.tsx`. Commit.

### Task 7: `PaperGroups` sections

`PaperGroups` props: runId, groupBy, params, groups, userId, table props. Each section: header `<button aria-expanded aria-controls>` with icon (aria-hidden) + label + count + rule (`<p class="group-rule">`, also `title=`); body `GroupBody` uses `usePapers(runId, {...params, group_by, group: key, page})` for pages 1..n, renders one `PaperTable`, "Show more (k of n)". Expand all / Collapse all. Reports visible rows up (`onRows`) so the page's j/k/x/s and select-all work across groups. Test (`groups.test.tsx`, MSW/mocked hooks per existing test style): header shows count and rule, toggling hides rows and persists, collapse all. Commit.

### Task 8: Page wiring + "Group by" select

`PapersPage`: `<label>Group by <select>` (Quality groups | Source | Year | Dropped by criterion | Library status | None (flat list)); grouped mode renders `PaperGroups`, flat mode the old table + pager. Shortcuts operate on `visibleRows` (concatenated in group order). Update `PAPERS_SHORTCUTS` text unchanged. Typecheck, lint, run `selection.test.tsx`. Commit.

### Task 9: Styles + docs

`styles.css`: `.title-clamp` (2-line clamp), `.paper-group` header, `.crit-values`. `docs/web-app.md`: short "Groups" paragraph. Commit.
