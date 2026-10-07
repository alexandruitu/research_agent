# Review fixes (external UX review) — design

Date: 2026-10-07 · Branch: `feat/review-fixes` · Keeps the reading-room design
(`docs/superpowers/plans/2026-09-30-slice4-2-frontend.md`), CSP (no inline styles, no
`dangerouslySetInnerHTML`), status never by colour alone, light/dark.

## 1. Red flags read as the problem (correctness)

Bug: a red flag showed the checklist item ("The model was tested on external data") when the answer
matched `red_flag_if` ("no"), i.e. the opposite of the problem.

- `ChecklistItem.flag_text` (optional, ≤200 chars): the problem phrasing. Old review files stay valid.
- Every default panel item gets a `flag_text` (also items that raise no flag today, so an admin who
  turns a flag on gets sensible wording).
- `scoring.flag_problem_text(item_text, red_flag_if, flag_text)`: `flag_text` when set, else
  `"Not met: <item>"` (red_flag_if = no) or `"Concern: <item>"` (yes). Scoring's red flags carry
  `text` = problem, `item_text` = item. Prompts are unchanged (the model only sees key + text), so
  `PROMPT_VERSION` and the call cache are untouched.
- DB: migration 0010 adds `red_flags.item_text`; existing rows move their text to `item_text` and get
  the generated phrasing (answer of the first raiser decides the prefix). Library snapshots are
  rewritten by matching their run's flags; an unmatched snapshot flag (answer not kept) reads
  `"Flagged: <item>"`.
- Importer: reports from before `flag_text` use the contract item's `flag_text`, else the rule.
- API: `RedFlagOut.item_text`, `PanelAnswerOut.flag` (problem text when the answer raises a flag),
  `PaperRow.red_flags` (problem texts, null without a panel review), `ChecklistItemIn/Out.flag_text`;
  snapshot flags carry `item_text`, `quote`, `section` (first raiser).
- Web: reviewer editor shows "Red-flag wording" when a flag rule is set, with a hint showing the
  generated fallback. Drawer, Papers chip (first problem + "+N more"), Library snapshot and the Why
  sentence show the problem, then "Evidence: “quote”" (section), then "Checklist item: …".

## 2. Start point

Papers and Home show a purpose line ("Find, screen and appraise papers for your field — every
decision explained.") and a primary "Start a literature search": to `/runs?new=1&field=<id>` with the
field of the most recent run, or `/fields/new` when there is no field. The onboarding page for empty
installs stays.

## 3. Three axes, labelled

Screening = "Search match" (Kept / Dropped / Unsure), Quality = groups, Team decision = library status.
Library status `relevant` is labelled "Useful" in the UI (API value unchanged). Column headers
"Search match", "Quality", "Team decision"; a one-line legend on Papers with glossary Terms.

## 4. Simple view

Columns: Paper · Quality (icon + word) · Why (one plain sentence, `simpleWords.plainWhy`: no Jev, LLM,
escalation or thresholds; names the first red-flag problem) · Next action · Team decision (badge or Save).
Next action, first match wins: dropped → none; unsure or not screened → "Check the match"; red flags →
"Check red flag"; provisional or abstract only → "Upload full text"; not saved → "Save" (saves);
else "Read". Every action but Save opens the paper's drawer. The Criteria column and the mechanics stay in
Detailed (which also gains "Quality" and "Team decision" columns; "Decision" became "Search match" with
Kept/Dropped/Unsure). Group headers in Simple show name, count and a one-liner (`QUALITY_ONELINER`); the
rule sits behind a "?" tooltip ("How “Read first” is decided"); Detailed keeps the full rule line.

## 5. Run identification

`runIdentity`: `name or topic (≤40 chars) · field vN · 6 Oct, 11:25 · status` (en-GB short date, local
time; runs with neither name nor topic start with the field). Failed/cancelled carry their mark and word
("! failed", "⊘ cancelled"). Used by the Papers, Compare-runs and New-eval pickers (sorted newest first,
extra details such as paper count appended); the Runs list links the short name and shows
"field vN · date · status" under it. The Papers default run is still the first one (API order) with papers.

## Notes

- Backend changed (migration 0010, new response fields): the running API must be restarted and migrated.
- Report (`report.py`) prints the problem text for red flags.
