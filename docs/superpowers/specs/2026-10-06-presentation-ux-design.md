# Presentation UX (premortem fixes) — design

Date: 2026-10-06 · Branch: `feat/papers-groups` · Design system: the "reading room"
(`docs/superpowers/plans/2026-09-30-slice4-2-frontend.md`). CSP: no inline styles, no
`dangerouslySetInnerHTML`. Status never by colour alone; everything keyboard-reachable; light and dark.

Goal: colleagues seeing the tool for the first time must understand *why* a paper is where it is,
without reading pipeline jargon or mistaking pipeline measurements for the quality of their run.

## Decisions

1. **Simple / Detailed view** (Papers). Simple is the default. Stored per user in
   `localStorage["papers.view.<userId>"]` (`simple|detailed`), read and written in try/catch (blocked
   storage: the default, for this page only). A two-button toggle (`aria-pressed`) in the toolbar; shortcut
   `v`, listed in the `?` sheet. Simple columns: Paper (title clamped to 2 lines, full title in `title`,
   year · source) · Group (icon + word, from the row's quality group) · Criteria (compact line) · Why ·
   Library (badge, or a Save button for members). Detailed = the existing table.
2. **Compact criteria line** (`criteriaSummary`, pure): `✓ 4/4 met`, `✕ dropped by incl 2`,
   `? 2 unclear`, `not screened`. Each criterion's values (Jev p, LLM answer, decided marker) appear in an
   accessible disclosure-tooltip (`<Term>`-style button, `aria-describedby`, opens on focus/hover/click/tap,
   Escape closes) and in the drawer table. The full list stays visible in Detailed view, so nothing is
   ever truncated silently.
3. **Why sentence**: a frontend pure function `whySentence()` in `features/papers/why.ts`. Reason: every
   input is already on the row (decision, deciding criterion, LLM answer, quote, red-flag count, editor
   group, text source, coverage); computing it on the client keeps the API unchanged and makes it
   unit-testable without a database. The drawer passes the panel's red-flag texts so the drawer's sentence
   names them ("1 red flag (no external validation)"); the table names the count only. The sentence is
   "computed once" per render from a single function used by both places.
4. **Empty quality groups are hidden**; one line under the groups lists them, each with a "why?"
   disclosure (`emptyGroupReason`, pure). Read first's reason mentions provisional papers when Worth a look
   is non-empty (those are usually there because only the abstract was read).
5. **Panel score only at coverage ≥ 50 %** (the API's `provisional`): Simple view never shows the number
   for a provisional row, only "provisional" with the existing explanation (now a `<Term>`). Detailed
   view keeps the number, de-emphasised (`.is-provisional`, smaller, muted) next to "provisional".
6. **Pipeline strip removed from the Papers table header.** Replaced by one line above the table:
   "Pipeline measured on CT-FFR reviews → System map". Stage panels stay reachable from the System map.
   The `?stage=` URL keeps working (side panel) for old links.
7. **Run coverage line**: the API adds `coverage` to `RunOut`/`RunDetailOut`
   (`searched`, `skipped` (= search warnings), `max_papers`, `full_text`, `abstract_only`), computed from
   the run manifest and `paper_reviews.text_source` (null counts when no panel review). Shown in the run
   row tooltip (`title` + `sr-only` text) and as a line on the run detail page:
   "Searched: Europe PMC, OpenAlex · Skipped: Semantic Scholar (rate limited) · Max papers: 12 · Text: 3
   full text / 7 abstract only". Needs an API restart.
8. **`<Term>` + glossary**: `components/ui/Term.tsx` renders the term text plus a small "?" button;
   the definition is a `role="tooltip"` element referenced by `aria-describedby`, shown on hover, focus
   and click/tap (toggle), dismissed with Escape or outside click. Definitions live in one file,
   `components/ui/terms.ts`. A Glossary dialog lists every term; it is linked from every `?` help sheet
   and from a footer link present on every page.
9. **Drawer**: the head (title, Save/status) is sticky; the first content line is the Why sentence;
   "Show details" (a `details`/`summary`) wraps the timeline tables, collapsed by default in Simple view,
   open in Detailed view.
10. **Polish**: run pickers truncate long labels (`…`) with the full text in `title`; the Papers run picker
    uses the run's short name (`runLabel`) when set; sentence case for labels.

## Testing

TDD on the pure functions (`why.test.ts`, `criteriaSummary`, `emptyGroupReason`, `viewMode` storage),
component tests for `Term`, the view toggle and the drawer; one backend test file for run coverage.
No full suites (project rule): only touched test files, `ruff check .`, `npm run typecheck && npm run lint`.
