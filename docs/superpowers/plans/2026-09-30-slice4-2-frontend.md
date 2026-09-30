# Slice 4 · Plan 2: Frontend (keyword field editor, team library, app-wide UX pass) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make a field easy to define (Describe → Keywords & criteria → Preview & save), give the team a Library
(list + reading pane) fed from Papers by bulk "Save to library", and make every screen calmer and faster to use.

**Architecture:** React 18 + TanStack Query + react-router 7 (BrowserRouter kept). New feature folders
`features/library`, `features/fieldflow`, `components/ui` (toasts, skeletons, empty states, status, shortcuts).
API shapes come only from `web/src/api/schema.d.ts` (generated from the backend of plan 1). Jobs (`field_assist`,
`field_preview`, `criteria_test`) are followed with the existing `useJob` poller.

**Tech stack:** vite 8, vitest 5, @testing-library, Playwright + axe, TypeScript 5.6 strict, eslint 10.
Two small runtime additions, self-hosted font files only (no JS): `@fontsource-variable/newsreader`,
`@fontsource/ibm-plex-sans` (justification below). No UI kit.

Spec: `docs/superpowers/specs/2026-09-30-keywords-library-ux-design.md` (sections 1–3, Testing, Plans → 2).
Backend contract: `docs/superpowers/plans/2026-09-30-slice4-1-backend.md`, verified in
`src/research_agent/web/api/routers/{fields,library}.py` and `schemas.py`.

---

## Design direction (chosen with the frontend-design skill)

**"The reading room."** The people using this read papers for a living: the interface should feel like a quiet
well-lit library desk, not a dashboard. Concretely:

- **Type:** *Newsreader* (variable serif, optical sizes) for page titles, paper titles and the reading pane —
  papers are the protagonists and a serif makes titles readable and distinctive; *IBM Plex Sans* for UI text
  and data (neutral, excellent figures, tabular numerals); system monospace for queries. Self-hosted via
  @fontsource (woff2 in the bundle, `font-src 'self'`, no CDN, no JS). Scale 12 / 13 / 14 / 16 / 20 / 28 px,
  line-height 1.5 body, 1.2 titles.
- **Colour:** warm paper background (`#f7f5f0` light, `#16181b` dark), ink text, one deep teal accent
  (`#0f5c4d` / `#6fd1b4`) used only for primary actions, focus and "current"; status colours desaturated and
  always paired with an icon and a word. Library statuses: ○ To read, ◐ Read, ★ Relevant, ⊘ Rejected.
- **Space:** 4-px grid (`--s1`…`--s8`), generous gutters around reading text, dense-but-aligned tables.
- **Surfaces:** cards with a hairline border and a soft 1-px shadow; sticky headers (drawer, library pane,
  save bars) on a translucent paper tone; a subtle paper grain via layered gradients on the page background
  (CSS only).
- **Motion:** one calm entrance (fade + 4-px rise, staggered 40 ms) for page sections and toasts; skeleton
  shimmer; all disabled under `prefers-reduced-motion`.
- **Memorable thing:** the *stepper spine* of the field editor — three numbered steps joined by a line that
  fills as you complete them, with a live "index card" summary of the field beside it; and the Library's
  reading pane, set like a journal page.

Hard constraints kept: IA and every feature; axe clean; keyboard reachable; visible focus; labels; status never
by colour alone; CSP (no `style=`, no injected HTML — `security.test.ts`); light and dark (`prefers-color-scheme`).

## Decisions

1. **Leave guard for main navigation:** BrowserRouter has no blocker, so `DirtyGuardProvider` moves up into
   `Layout` (one app-wide guard); main-nav links, settings tabs, the brand link and "Sign out" call
   `confirmLeave()`; `beforeunload` covers reload/close. The field editor reports dirty too.
2. **Draft queries shown live:** `features/fieldflow/querybuild.ts` is a line-for-line port of
   `research_agent.querybuild` (read-only display; the server rebuilds on save/preview). Tests mirror the Python
   table tests.
3. **Synonyms:** accepting a synonym of an `any` or `none` term adds it to the same group; a synonym of an
   `all` term goes to "At least one of" (adding it to "Must include" would make the search stricter, not wider);
   the chip says where it goes.
4. **Optimistic library saves:** the bulk save patches the papers-page cache (`library` ref per row) before the
   request; on error it rolls back; the success toast offers **Undo**, which deletes the items that were
   *created* by that save (existing ones untouched). Status changes are optimistic with Undo (PATCH back).
5. **Keyboard shortcuts** (Papers, Library): `j/k` move, `o`/Enter open, `x` select (Papers), `s` save (Papers)
   / focus status (Library), `1–4` status, `/` focus search, `?` help sheet, `Esc` close. Ignored when the
   event target is an input, textarea, select, contenteditable, or any modifier key is held.
6. **Export** is a plain `<a href download>` to `/api/v1/library/export?format=…&<filters>` (same origin,
   cookies; GET so no CSRF).
7. **Checklist answers:** the drawer loads the reviewer version the report used
   (`GET /reviewers/{key}/versions/{n}`) and, when `pass_if` is known, shows **meets / concern** beside the raw
   yes/no ("✓ yes · meets"); without it, the raw answer only.
8. **Home:** when there is no run, `/` shows "Create your first field in 3 steps" instead of an empty table.

## File structure

- `web/src/styles.css` — rewritten tokens + all component styles (one file, sections commented).
- `web/src/main.tsx` — font imports.
- `components/ui/Toast.tsx` (+test) — provider, `useToast()`, Undo action, `role=status` region.
- `components/ui/Skeleton.tsx`, `EmptyState.tsx`, `StatusMark.tsx` (+tests) — skeleton rows, teaching empty
  states, library status icon + word.
- `components/ui/shortcuts.ts`, `ShortcutsHelp.tsx` (+test) — `useShortcuts(map)`, `isTypingTarget`, help dialog.
- `components/Layout.tsx` — brand, nav (adds Library), guard, toasts.
- `features/settings/dirtyGuard.tsx` — unchanged API, mounted in Layout.
- `api/types.ts`, `api/hooks.ts` — library/collections/assist/preview types and hooks.
- `features/fieldflow/{querybuild,fieldForm,TagInput,Suggestions,QueryPanel,PreviewPanel,SummaryCard,Stepper}.tsx|ts`
  (+tests); `features/fields/fieldForm.ts` becomes a re-export of the extended model.
- `pages/FieldEditorPage.tsx` — the 3-step flow.
- `features/library/{libraryState,LibraryList,ReadingPane,StatusControl,TagsEditor,CollectionsEditor,SnapshotView,CollectionsManager,SaveDialog}.tsx|ts` (+tests)
- `pages/LibraryPage.tsx`, `pages/HomeEmpty.tsx`.
- `features/papers/{PaperTable,FilterBar,PaperDrawer}.tsx`, `pages/PapersPage.tsx` — selection, badges,
  active chips, sticky drawer header, shortcuts.
- `features/papers/PeerReview.tsx`, `panel.ts` — pass_if verdicts.
- `features/settings/ReviewersTab.tsx`, `ReviewerEditor.tsx` — archived toggle outside the disabled fieldset;
  version diff.
- `web/e2e/{flows,a11y,library}.spec.ts`, `docs/web-app.md`.

---

### Task 1: Design foundation and layout

**Files:** Modify `web/package.json`, `web/src/main.tsx`, `web/src/styles.css`, `components/Layout.tsx`,
`components/layout.test.tsx`, `App.tsx` (route `/library`).

- [ ] Test (layout.test): main nav is `["Papers","Library","Runs","Fields","Evals","System map","Settings"]`;
  the brand is a link to `/`; `security.test.ts` still passes.
- [ ] `npm i @fontsource-variable/newsreader @fontsource/ibm-plex-sans`; import
  `@fontsource-variable/newsreader/opsz.css`, `@fontsource/ibm-plex-sans/{400,500,600}.css` in `main.tsx`.
- [ ] Tokens in `:root` (light) and `@media (prefers-color-scheme: dark)`:
  ```css
  --paper:#f7f5f0; --card:#fffdf8; --ink:#1d2327; --ink-2:#4a545c; --rule:#dcd6cb; --accent:#0f5c4d;
  --s1:4px; --s2:8px; --s3:12px; --s4:16px; --s5:24px; --s6:32px; --s8:48px;
  --serif:"Newsreader Variable",Georgia,serif; --sans:"IBM Plex Sans",system-ui,sans-serif;
  ```
  Old names (`--bg --fg --muted --line --panel`) stay as aliases so untouched components keep working.
- [ ] Layout: `<Link className="brand">` with a small serif wordmark; `Library` NavLink after Papers.
- [ ] Commit `UX foundation: reading-room type, tokens, Library in the main navigation`.

### Task 2: UI primitives (toasts, skeletons, empty states, status mark)

**Files:** Create `components/ui/Toast.tsx`, `Skeleton.tsx`, `EmptyState.tsx`, `StatusMark.tsx`,
`components/ui/ui.test.tsx`; Modify `Layout.tsx` (mount `ToastProvider`), `test/render.tsx` (wrap in provider).

Key code:
```ts
export type ToastInput = { text: string; tone?: "ok" | "bad" | "info"; action?: { label: string; run: () => void }; ms?: number };
export function useToast(): { show: (t: ToastInput) => void };
export const LIBRARY_STATUSES = ["to_read","read","relevant","rejected"] as const;
export const STATUS_META = { to_read:{icon:"○",word:"To read"}, read:{icon:"◐",word:"Read"}, relevant:{icon:"★",word:"Relevant"}, rejected:{icon:"⊘",word:"Rejected"} };
```
Tests: a toast appears in a `role=status` region with its text; its action button runs the callback and closes
it; it disappears after `ms` (fake timers); Escape dismisses; `StatusMark` renders icon (aria-hidden) and word;
`Skeleton` has `aria-busy` with a visually hidden label; `EmptyState` renders title, text and action.
Commit `UI primitives: toasts with undo, skeletons, teaching empty states, status marks`.

### Task 3: App-wide unsaved-changes guard

**Files:** Modify `features/settings/dirtyGuard.tsx` (doc only), `components/Layout.tsx`, `pages/SettingsPage.tsx`
(provider removed there), `components/layout.test.tsx`.
Tests: with a dirty settings tab, clicking main-nav "Runs" asks `confirm` and stays when refused, leaves when
accepted; clean → no question; Sign out also asks.
Commit `Unsaved-changes guard covers the main navigation and sign-out`.

### Task 4: Keyboard shortcuts and help sheet

**Files:** Create `components/ui/shortcuts.ts`, `components/ui/ShortcutsHelp.tsx`, `components/ui/shortcuts.test.tsx`.
```ts
export const isTypingTarget = (t: EventTarget | null) => t instanceof HTMLElement && (t.isContentEditable || ["INPUT","TEXTAREA","SELECT"].includes(t.tagName));
export function useShortcuts(map: Record<string, (e: KeyboardEvent) => void>, enabled = true): void;
```
Tests: `j` calls handler; `j` typed in an input does not; Ctrl/Meta/Alt + key ignored; `?` opens a dialog
listing shortcuts (role dialog, labelled, Escape closes, focus returns).
Commit `Keyboard shortcuts with a help sheet; never while typing`.

### Task 5: API types and hooks for library, collections, assist, preview

**Files:** Modify `api/types.ts`, `api/hooks.ts`; Create `api/libraryHooks.test.tsx`.
Types: `LibraryItemOut, LibraryItemDetail, LibraryPage, LibrarySaveOut, CollectionOut, LibraryRef, KeywordsIO,
QueryOverrideIO, AssistResult, PreviewResult`. Hooks: `useLibrary(params)`, `useLibraryItem(id)`,
`useCollections(archived)`, `useSaveToLibrary()`, `usePatchLibraryItem()`, `useDeleteLibraryItem()`,
`useSnapshotItem()`, `useCreateCollection()`, `usePatchCollection()`, `useArchiveCollection()`, `useAssist()`,
`usePreview()`, `exportUrl(params, format)`.
Tests: `useLibrary` sends the filters as query params; `exportUrl` builds `/api/v1/library/export?format=bibtex&status=relevant`
and drops empty values; `useSaveToLibrary` invalidates papers/paper/library keys.
Commit `API hooks for the library, collections, field assist and preview`.

### Task 6: Query builder port

**Files:** Create `features/fieldflow/querybuild.ts`, `querybuild.test.ts`.
Tests (mirroring `tests/test_querybuild.py`): phrase quoting (`"deep learning"`, bare `CT`), operator words
quoted (`"AND"`), syntax characters become spaces, case-insensitive duplicates dropped, wildcard kept only for
Europe PMC single words, arXiv categories and `ANDNOT`, `NOT` for others, single any term without parentheses,
empty all+any → error text, override replaces, OpenAlex override with comma → error.
Commit `Draft queries built in the browser exactly like the server builds them`.

### Task 7: Field form model with description, keywords, overrides

**Files:** Modify `features/fields/fieldForm.ts`, `fieldForm.test.ts`.
`FieldForm` gains `description: string; keywords: {all:string[];any:string[];none:string[]}; overrides: {europepmc:string;openalex:string;arxiv:string}`.
Rules: name required; topic optional when keywords exist (the topic defaults to the description's first sentence
or the keywords joined, ≥ 3 chars); at least one criterion; `none` alone is an error ("Add a keyword to Must
include or At least one of"); ≤ 20 terms per group, 1–80 chars; overrides ≤ 2000, no comma for OpenAlex;
`toDraft` sends `keywords` only when a term exists and `query_override` only when an override is set; legacy
versions load with empty keyword groups.
Commit `Field form carries description, keyword groups and query overrides`.

### Task 8–10: The 3-step field editor

**Files:** Create `features/fieldflow/{Stepper,TagInput,Suggestions,QueryPanel,PreviewPanel,SummaryCard}.tsx`,
`features/fieldflow/fieldflow.test.tsx`; rewrite `pages/FieldEditorPage.tsx`, update `pages/FieldEditorPage.test.tsx`.

- Step 1 **Describe**: name, description (textarea with counter), "Suggest keywords & criteria" (assist job, demo
  checkbox shared across the page), results as chips per group: each chip is a toggle button
  `aria-pressed` "Accept <term>"; synonyms as small chips "+ synonym → At least one of"; criteria sentences as
  chips; **Accept all**; nothing applied until clicked; errors `nothing_to_assist` shown inline.
- Step 2 **Keywords & criteria**: three `TagInput`s (Enter/comma adds, Backspace on empty removes last, each tag
  has a remove button "Remove <term> from Must include"), criteria lists (existing `CriteriaList`), sources,
  years, then per-source built query (read-only `<output>`), `<details>` "Advanced: override query" with one
  textarea per source.
- Step 3 **Preview & save**: "Preview search" (preview job) → per source: count, up to 10 titles with years,
  the exact query, the error when a source failed; 429 → "Too many previews; try again in a minute"; Test
  criteria (existing panel, saved fields only); change note; **Save as vN+1** / **Create field**.
- Steps are a `<nav aria-label="Steps">` of buttons with `aria-current="step"`; each step is a section with a
  heading; Back/Next buttons; the step is kept in `?step=` so reload stays; all steps remain editable.
- **SummaryCard** (aside "Field summary"): name, description excerpt, keyword counts per group, criteria counts,
  sources, years, overrides count, save state ("Unsaved changes").
- Legacy fields: open on step 2 with the legacy banner; everything editable.
- Dirty state reported to the app guard.

Tests: stepper moves and marks current; assist request body carries description + keywords + mode; accepting one
chip adds only that term; accept all adds all groups and criteria; synonym of an `all` term lands in `any`; tag
input add/remove/Backspace; built query updates live; override replaces displayed query; preview renders counts,
titles and per-source error; 429 message; create posts keywords/description; save posts `base_version`; legacy
field loads on step 2 with the banner; viewer sees a read-only editor; leaving with edits asks.
Commits: `Field editor step 1: describe and accept suggestions`, `… step 2: keyword groups, criteria and the
built queries`, `… step 3: preview per source and save, with a live summary`.

### Task 11: Library page

**Files:** Create `pages/LibraryPage.tsx`, `features/library/*`, `features/library/library.test.tsx`,
`pages/LibraryPage.test.tsx`.

Layout: header (title, count, Export CSV / BibTeX links, "Collections" manager toggle), toolbar (search box with
`/` hint, sort select + direction), filter row (collection select, status segmented buttons with icon+word, tag
select from visible items + free text, field select, min score number, "Has red flags" toggle), active-filter chips
with "Clear all"; body: list (`role=listbox`-free simple list of buttons, `aria-current` on the open one) +
reading pane (`aside` "Reading pane"): sticky header with title, status control (radio group), delete (with
confirm, only when `can_delete`); tabs Overview / Evidence / History; Overview: meta line, abstract (serif),
collections editor (checkbox list + create), tags editor (TagInput), note (textarea + Save note), files;
Evidence: snapshot (screening decision and criteria table, panel score, editor verdict, red flags, reviewer
summaries, taken at, run link); "Update snapshot from the newest run" when the latest run of that field
(from `useRuns`) is newer than the snapshot's run and contains the paper (tried; 422 shown politely); History:
events list in words. Filters live in the URL (`q, collection, status, tag, field, min, flags, sort, dir, page,
item`). Shortcuts: j/k, o/Enter, 1–4, `/`, `?`, Esc.

Tests: list renders items with status marks; filters go to the API params; active chips + clear all; open item
shows the pane with abstract and events; status change PATCHes optimistically and toast Undo PATCHes back;
tags/note/collections PATCH; delete asks and DELETEs; export links carry the filters; snapshot view shows
verdict/red flags; update snapshot posts `run_id`; collections manager create (409 name_taken message), rename,
archive (admin only); empty library teaches ("Save papers from a run: select them in Papers and press Save to
library"); viewer: no edit controls.
Commit `Library: list and reading pane with status, tags, notes, collections, evidence and history`.

### Task 12: Papers and drawer integration

**Files:** Modify `features/papers/PaperTable.tsx`, `pages/PapersPage.tsx`, `features/papers/PaperDrawer.tsx`;
Create `features/library/SaveDialog.tsx`, `features/papers/selection.test.tsx`.
Checkbox column (members) with "Select all on this page"; a selection bar ("3 selected · Save to library ·
Clear"); Save dialog (`role=dialog`, labelled): collection checkboxes + "New collection" name, tags, status radio,
note; optimistic badge; toast "Saved 2 papers to <collection>" with Undo; row badge "In library · ★ Relevant"
(link to `/library?item=`); drawer sticky header: title, badge or "Save to library" button, status radio when
saved. Tests: select two rows → bar; dialog posts `{run_id, paper_ids, new_collection, tags, status}`; badges
appear before the response; error rolls back + alert toast; Undo deletes created ids; drawer save and status.
Commit `Save to library from Papers: bulk selection, optimistic badges, undo; drawer header actions`.

### Task 13: Papers polish, Home onboarding, shortcuts, skeletons, empty states

**Files:** Modify `pages/PapersPage.tsx`, `features/papers/FilterBar.tsx`, `pages/RunsPage.tsx`,
`pages/FieldsPage.tsx`, `features/runs/RunList.tsx`; Create `pages/HomeEmpty.tsx`.
Active-filter chips + Clear all; Papers shortcuts (j/k/o/x/s/1–4/?); skeleton tables instead of "Loading…";
Home onboarding (no runs): three numbered cards (Describe your field → Preview the search → Run and save what
matters) with "Create your first field" (members) or "Ask a member…" (viewers); teaching empty states in Runs,
Fields, Papers. Tests for each.
Commit `Papers shortcuts and filter chips; home onboarding; skeletons and teaching empty states`.

### Task 14: Known weaknesses

**Files:** `features/papers/panel.ts`, `PeerReview.tsx`, `features/settings/ReviewersTab.tsx`,
`features/settings/ReviewerEditor.tsx`, tests alongside.
pass_if verdicts (Decision 7); archived-reviewers toggle outside the disabled fieldset (viewers/members can open
it); reviewer version diff (compare two versions: perspective, model, items added/removed/changed).
Commit `Checklist answers say meets or concern; archived reviewers visible to all; reviewer version diff`.

### Task 15: End-to-end, accessibility, docs

**Files:** `web/e2e/flows.spec.ts`, `web/e2e/a11y.spec.ts`, `web/e2e/library.spec.ts`, `docs/web-app.md`.
Flow: New field → describe → Suggest (demo) → Accept all → step 2 → Preview (demo) shows counts → Create field →
Start demo run (3 papers) → Papers: select 2 → Save to library → new collection "E2E reading" → status
Relevant → Library filtered by collection shows both → export CSV link responds 200 text/csv. Shortcuts smoke on
Papers (`j`, `o`, `?`) and Library (`j`, `2`). axe on: home, papers (+selection bar, save dialog), drawer, field
editor steps 1–3, library (list, pane, each tab), collections manager, settings reviewers (archived open).
Existing tests updated for the new editor labels. Run `npm run e2e` until green.
Commit `e2e: describe to library flow, shortcuts smoke, axe on every changed page; docs`.

---

## Commands (before every commit, in `web/`)

`npm run typecheck && npm run lint && npm test && npm run build`

## Self-review

- Spec §1 editor (describe, suggestions accept/decline/accept-all, three groups, synonyms, criteria editable,
  built query read-only + override, preview per source with count/10 titles/errors, Test criteria kept, save
  vN+1 with note, live summary, legacy editable): Tasks 6–10.
- Spec §2 library UI (list + pane, search, filters, sort, status icon+word, tags, note, collections, events,
  snapshot, files, update snapshot, export with filters, collections management): Task 11; Papers/drawer: Task 12.
- Spec §3 UX (home onboarding, empty states, skeletons, filter chips + clear all, shortcuts + help sheet,
  type/space scale, calmer colour, toasts, confirmation only for destructive, guard on main nav, known
  weaknesses): Tasks 1–4, 13, 14.
- Testing section: Vitest per task; Playwright flow + axe: Task 15.
- Types: every hook uses names from `api/types.ts` defined in Task 5; `STATUS_META` (Task 2) is used by
  Tasks 11–12; `FieldForm` fields from Task 7 are used by Tasks 8–10.
