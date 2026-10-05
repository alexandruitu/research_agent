# Slice 6 · Plan 3: Live evals frontend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the Evals page into a living tool: report cards and in-flight jobs, a "New evaluation" wizard with
a cost estimate, report views per kind (screening, panel, ablation, human), compare mode, and a blind Rate view
for human reference ratings; Gemini in Settings → AI models; System map stage renamed "Review panel".

**Architecture:** Pure parsers in `features/evals/*.ts` turn the untyped `metrics` JSON (contract in
`2026-10-05-slice6-1-eval.md`, "Contract for Plan 2") into typed views; React components only render views.
Data hooks live in `api/hooks.ts` against the routes in `api/schema.d.ts` (authoritative, from Plan 2).
Routes: `/evals` (home), `/evals/new` (wizard), `/evals/compare?ids=a,b` (compare), `/evals/:evalId` (report
by kind), `/rate/:sampleId` (Rate view). Styling stays in `styles.css` (reading room tokens, light/dark).

**Tech Stack:** React 18, TanStack Query 5, React Router 7, Vitest + Testing Library.

Spec: `docs/superpowers/specs/2026-10-05-live-evals-design.md`. Backend: `2026-10-05-slice6-2-backend.md`.
Testing rule (user): only the test files a task adds or touches (`npx vitest run <paths>`), plus
`npm run typecheck && npm run lint`. No full vitest, no e2e.

## Decisions (made without asking, per the user)

1. **Home vs report**: `/evals` becomes a home (cards), no longer auto-opening the newest report. The screening
   report keeps its content and moves to `ScreeningReport.tsx`; its tests move to the `/evals/:id` route.
2. **Numbers in words**: every metric is rendered as a number plus a short phrase ("0.42 — moderate agreement",
   Landis–Koch bands) so status never depends on colour; chips carry an icon and a word.
3. **Human reports** reuse the panel view and add a "Against human ratings" section first.
4. **Wizard** is a single page with three numbered steps (kind → inputs → estimate & start) using the
   existing `.stepper` styles; the estimate is fetched only on demand ("Estimate cost"), Start is enabled after
   an estimate for live mode (demo starts directly). After Start the wizard follows the job and offers
   "Open report" when `progress.result.eval_id` appears.
5. **Gold set builder** is a disclosure inside the wizard's inputs step: name, citation, topic, query, included
   studies one per line (`DOI` or `DOI | title | year`), optional SR reference; it posts `/gold-sets` and shows
   the job; the gold set list refreshes when done. The SR DOI is a citation only (Plan 2 decision 5) — said in the form.
6. **Ablation chart**: native SVG, three grouped measures per subset size (verdict changed %, red flags missed %,
   cost calls) as dot rows on a 0–100% axis, `role="img"` with an `aria-label` summary, plus an equivalent table.
7. **Compare**: checkboxes on cards ("Select to compare"), a sticky compare bar enabled at 2–3 selections of one
   family; mixed families disable the button with a reason in words.
8. **Rate view**: answer buttons are radio groups (arrow keys move within, `1`–`4` keyboard shortcuts set the
   focused item's answer, `n` goes to the next unanswered item), Submit enabled when every item is answered;
   after submit the reveal replaces the form. The sample header says "x of N papers have 2 raters".
9. **Models tab**: the one-family warning names a concrete fix: "make one reviewer (e.g. Statistician) use a
   Gemini model" when a `google_genai` model is available, else "add a GOOGLE_API_KEY to the worker".
10. **Stage title**: backend `stages.yaml` title becomes "Review panel"; fixtures, unit tests and the a11y e2e
    spec text follow (e2e not run).

## File map

- Modify `web/src/api/types.ts`, `web/src/api/hooks.ts`, `web/src/test/fixtures.ts`, `web/src/App.tsx`, `web/src/styles.css`.
- Create `web/src/features/evals/words.ts` (+ test), `panel.ts` (+ test), `ablation.ts` (+ test).
- Create `web/src/features/evals/ScreeningReport.tsx`, `ReportCard.tsx`, `EvalJobs.tsx`, `PanelReport.tsx`,
  `HumanSection.tsx`, `AblationReport.tsx`, `AblationChart.tsx`, `NewEvalWizard.tsx`, `GoldSetForm.tsx`, `goldForm.ts` (+ test),
  `RatingSamples.tsx`.
- Create pages `EvalsHomePage.tsx` (+ test), `EvalReportPage.tsx` (replaces `EvalsPage.tsx`; tests move),
  `NewEvalPage.tsx` (+ test), `ComparePage.tsx` (+ test), `RatePage.tsx` (+ test).
- Modify `web/src/features/settings/ModelsTab.tsx`, `models.ts` (+ test); `src/research_agent/web/stages.yaml`,
  `web/e2e/a11y.spec.ts`, `web/src/pages/SystemMapPage.test.tsx`, `web/src/features/papers/drawer.test.tsx`.

## Tasks

### Task 1: Types, hooks, fixtures
- [ ] Add types (`EvalJobOut, EvalRequest, EstimateOut, CompareOut, GoldSetOut, GoldSetRequest, RatingSampleOut,
  RatingNextOut, RatingSubmitIn, RatingSubmitOut, RevealOut, EvalKind`) and hooks `useEvals(kind?)`, `useEvalJobs()`
  (polls every 3 s while any job is queued/running), `useGoldSets`, `useCompare(ids)`, `useEstimate`, `useStartEval`,
  `useBuildGoldSet`, `useCreateRatingSample`, `useRatingSample`, `useRatingNext`, `useSubmitRatings`, `useReveal`.
- [ ] Fixtures: `panelMetrics()`, `ablationMetrics()`, `humanSection()`, `evalJob()`, `goldSet()`, `ratingSample()`, `ratingNext()`, `reveal()`.
- [ ] Covered by the page tests of later tasks; `npm run typecheck`. Commit.

### Task 2: Words and parsers (pure, table-tested)
- [ ] `words.ts`: `kappaWords(k)` (Landis–Koch: <0 "worse than chance", <0.2 slight, <0.4 fair, <0.6 moderate,
  <0.8 substantial, else almost perfect), `pct(x)`, `rateText(rate)`, `KIND_LABEL`, `familyOf(kind)`.
- [ ] `panel.ts`: `parsePanel(metrics) → PanelView` (agreement, editor, items worst-first, coverage rows, dispersion,
  auc, families, human|null). `ablation.ts`: `parseAblation(metrics) → AblationView` (sizes sorted, subsets, summary).
- [ ] Tests `words.test.ts`, `panel.test.ts`, `ablation.test.ts` with fixture metrics, missing sections → nulls. Commit.

### Task 3: Evals home, routes, screening report moved
- [ ] Test `EvalsHomePage.test.tsx`: cards show kind badge (word), date, chips, headline phrases; parent/child link;
  in-flight job row with "step 2 of 4 · 3/10"; failed job shows its error; kind filter calls `/evals?kind=panel`;
  empty state names "New evaluation"; viewers see no "New evaluation" button.
- [ ] Move `EvalsPage` content to `ScreeningReport` + `EvalReportPage` (dispatch by kind, header with chips,
  parent/children links); move its tests to `EvalReportPage.test.tsx` (route `/evals/:id`). Commit.

### Task 4: New evaluation wizard (+ gold set form)
- [ ] `goldForm.test.ts`: `parseIncluded("10.1/x | Title | 2020\n10.2/y")` → studies; blank lines ignored; errors for empty.
- [ ] `NewEvalPage.test.tsx`: choosing Panel shows gold-set/run choice, sample, settings version; Estimate posts the
  same body to `/evals/estimate` and shows calls/tokens/"unknown price"/notes; Start posts `/evals` and follows the
  job; done → "Open report" link to `/evals/<eval_id>`; ablation shows only panel reports + rerun-editor checkbox;
  demo toggle sets `mode: demo`; gold form posts `/gold-sets`. Commit.

### Task 5: Panel report (+ human section)
- [ ] `PanelReport` test (in `EvalReportPage.test.tsx`): agreement card "Fleiss kappa 0.42 — moderate" with raw
  agreement and prevalence; editor vs majority; items table worst-first with "candidate to reword" chip; coverage
  table cells read "80% answered (8 of 10)"; dispersion links to papers; AUC with CI and "inclusion ≠ quality";
  single family → explanation + link to `/settings/models`; human section per reviewer and Spearman; admin sees
  "Create rating sample", existing samples link to `/rate/<id>`. Commit.

### Task 6: Ablation report
- [ ] Test: summary sentence; SVG `role="img"` with label; table rows per size; per-subset table; parent link. Commit.

### Task 7: Compare mode
- [ ] Home test: selecting 2 same-family cards enables "Compare 2"; mixed families disable with reason.
- [ ] `ComparePage.test.tsx`: aligned table with report columns, rows with `differs` say "differs", config rows. Commit.

### Task 8: Rate view
- [ ] `RatePage.test.tsx`: shows "Paper 3 of 20", sample progress, text source; no model answers rendered;
  Submit disabled until all answered; keys `1`–`4` answer the focused item; submit posts the body; then reveal
  shows "You and the model agree on 1 of 2" with per item "agree"/"disagree"; Next paper refetches; done state. Commit.

### Task 9: Settings → AI models + stage rename
- [ ] `models.test.ts`: `familyAdvice(family, models)` mentions Gemini when a `google_genai` model is available.
- [ ] ModelsTab uses it; `stages.yaml` title "Review panel"; fixtures/tests/e2e text updated. Commit.

## Self-review
Spec coverage: home + jobs + filter + empty (3), wizard + estimate + gold builder (4), panel/human reports (5),
ablation (6), compare (7), Rate blind + reveal (8), Gemini + stage title (9). Typecheck/lint after every task.
Deviation: plan lists test intents rather than full code per step (UI-heavy, written TDD in-session).
