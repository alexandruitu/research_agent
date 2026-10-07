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

Columns: Paper · Quality (icon + word) · Why (one plain sentence without Jev/LLM/escalation/thresholds)
· Next action · Team decision. Next action, first match wins: dropped → "None"; red flags → "Check red
flag"; provisional or abstract-only → "Upload full text"; not reviewed → "Review by hand"; else "Read".
Mechanics (Jev, LLM, escalation, provisional detail) stay in Detailed. Simple group headers show name,
count and a short one-liner; the rule moves into a "?" Term.

## 5. Run identification

One label everywhere (Papers/Compare/Evals pickers, Runs list): `name or topic (≤40 chars) · field vN ·
6 Oct, 11:25 · status word`; failed/cancelled say so in words; most recent first.
