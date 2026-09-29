# Slice 3 · Plan 3: Frontend (review panel, settings tabs, full-text uploads) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Admins configure the peer-review panel, AI models, screening thresholds and full-text sources in
Settings (versioned, one Save per tab); everyone reads each paper's panel score, coverage, red flags and text
source in the Papers table and the full peer review in the drawer; members upload a PDF when only the abstract
was reviewed.

**Architecture:** Settings tabs share one `SettingsFrame` (intro, "Used by next run · vN" badge, read-only
explanation, change note, Reset to default, Save, 409 reload banner) and one unsaved-changes guard
(`DirtyGuard` context: tab links confirm, `beforeunload` warns). Every settings tab edits one slice of the
current `ReviewSettingsContent` and posts the whole content with `base_version`. Pure logic (threshold bands,
Evals mapping, model families, reviewer form, answer words, coverage text) lives in small `.ts` files with unit
tests; components stay thin. Uploads use `XMLHttpRequest` for progress (fetch has no upload progress), with the
same CSRF header as `api`.

**Tech Stack:** React 18, TypeScript 5.6 strict, react-router-dom 7 (BrowserRouter, so no `useBlocker`),
TanStack Query 5, Vitest 5 + Testing Library, Playwright + axe. CSP: no `style=` attributes and no injected HTML
(`src/security.test.ts`), so bars use native `<meter>`, sliders native `<input type="range">`.

**Spec:** `docs/superpowers/specs/2026-09-29-review-panel-design.md` (Frontend, Testing, Plans → 3). API shapes:
`web/src/api/schema.d.ts` (regenerated in Plan 2) and `docs/superpowers/plans/2026-09-29-slice3-2-backend.md`.

---

## Decisions this plan takes

1. **Visual language:** the existing tokens and components (`.card`, `.chip`, `.pill`, `.banner`, `.step`,
   `.tabs`); new classes only extend them (`.reviewer-card`, `.segmented`, `.band`, `.dropzone`, `.answer--*`).
   The one memorable element is the **band diagram** on the Screening tab: a `<meter>`-free, pure-CSS three-zone
   strip per criterion kind (drop · ask the LLM · keep) built from grid columns whose widths are set by CSS
   classes in 5 % steps (`.w-0`…`.w-100`), because inline widths are forbidden by the CSP.
2. **Unsaved-changes guard:** BrowserRouter has no `useBlocker`. `SettingsPage` provides a `DirtyGuard`
   context; tabs report `dirty`; tab `NavLink`s ask `window.confirm("Discard your unsaved changes?")` and a
   `beforeunload` listener warns on reload/close. The main nav is not guarded (documented weakness).
3. **Reviewer model in the AI models tab:** a reviewer's model lives in its reviewer version. Saving the AI
   models tab first saves a new version of each reviewer whose model changed (base_version, note from the
   form), then the settings version. The tab says so next to Save.
4. **Editor instructions** are edited on the Reviewers tab (an "Editor" card); the editor model on AI models.
5. **Default panel on/off** is edited on the Reviewers tab cards and saved as a settings version (1–5 enforced
   in the UI with the reason: "A panel needs 1 to 5 reviewers").
6. **Evals recommendation on Screening:** Evals measures the legacy Jev pair (`min_confidence`,
   `exclude_min_confidence`) on one topic-match criterion. The exact translation is for **inclusion
   criteria only**: keep at `p ≥ (1 + min_confidence) / 2`, drop at `p ≤ (1 − exclude_min_confidence) / 2`
   (same rule as `jev.decide_from_probabilities`). "Apply to inclusion criteria" sets `keep_min` and
   `include_fail_max`; exclusion bands have no measured counterpart, so they are only shown, with a note
   that the pair was measured on one gold set with a single topic criterion.
7. **Model dropdown:** options = available models (provider key accepted) + the current value even if not
   available (marked "(key not accepted)") + "Worker default". Family = provider prefix before `:`. Warning chip
   "All reviewers use one model family (anthropic): their errors may agree" when every panel reviewer resolves
   to the same known provider.
8. **Papers score column:** a panel run shows `score` ("72 · 8/10 answered"; coverage → answered out of 10,
   rounded) with a `<meter>`; legacy runs keep the rank score. Red flags: chip "2 red flags" (words, not
   colour only). Text: "full text · PMC" / "abstract".
9. **Drawer "Peer review" step** replaces "Reviewers" when `panel` is present: editor verdict + reason first,
   disagreements in words, then one `<details>` per reviewer (verdict, score, coverage, checklist table with
   answer icon + word, quote + section, "red flag" in words), red flags list. Files section after it; upload
   shown to members when `upload` is enabled, prominently when `text_source` is `abstract`.

## File structure

| File | Responsibility |
|---|---|
| `web/src/api/types.ts` | aliases for the new schemas |
| `web/src/api/client.ts` (+ test) | `api.delete`, `uploadFile` (XHR, progress, CSRF, ApiError) |
| `web/src/api/hooks.ts` | reviewers, review settings, models available, paper files hooks + keys |
| `web/src/features/settings/SettingsFrame.tsx`, `dirtyGuard.tsx` | shared tab chrome, unsaved guard |
| `web/src/features/settings/useSettingsSave.ts` | save the whole settings content with base_version |
| `web/src/features/settings/screening.ts` (+ test), `ScreeningTab.tsx` | bands, validation, Evals mapping |
| `web/src/features/settings/FulltextTab.tsx` | sources, contact, limits |
| `web/src/features/settings/models.ts` (+ test), `ModelsTab.tsx` | options, families, role rows |
| `web/src/features/settings/reviewerForm.ts` (+ test), `ReviewersTab.tsx`, `ReviewerEditor.tsx` | cards, editor |
| `web/src/pages/SettingsPage.tsx`, `web/src/App.tsx` | tabs and routes |
| `web/src/features/papers/cells.tsx`, `PaperTable.tsx`, `FilterBar.tsx`, `papersState.ts` | columns, filter |
| `web/src/features/papers/panel.ts` (+ test), `PeerReview.tsx`, `PaperFiles.tsx`, `PaperDrawer.tsx` | drawer |
| `web/src/styles.css` | new classes, light/dark via tokens |
| `web/src/test/fixtures.ts` | settings, reviewers, models, panel fixtures |
| `web/src/pages/SettingsPage.test.tsx`, `ReviewerEditor.test.tsx`, `PapersPage.test.tsx`, `drawer.test.tsx` | tests |
| `web/e2e/flows.spec.ts`, `web/e2e/a11y.spec.ts`, `scripts/e2e_server.py` | e2e, isolated uploads dir |
| `docs/web-app.md` | frontend section |

Before every commit, in `web/`: `npm run typecheck && npm run lint && npm test && npm run build`. Stage exact
files. Commit with `-m "<subject>" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"`.

---

### Task 1: API layer

**Files:** Modify `web/src/api/types.ts`, `client.ts`, `client.test.ts`, `hooks.ts`.

- [ ] **Step 1: failing tests** (`client.test.ts`):

```ts
it("uploadFile posts multipart with the CSRF token and reports progress", async () => {
  // a fake XMLHttpRequest records open/send/headers, fires upload.onprogress(5/10) then load with 201 JSON
  setCsrfToken("t");
  const seen: number[] = [];
  const row = await uploadFile(`/papers/${PAPER_ID}/files`, new File(["%PDF-1.4"], "a.pdf"), (f) => seen.push(f));
  expect(fake.url).toBe(`/api/v1/papers/${PAPER_ID}/files`);
  expect(fake.headers["X-CSRF-Token"]).toBe("t");
  expect(fake.body).toBeInstanceOf(FormData);
  expect(seen).toContain(0.5);
  expect(row).toEqual({ id: "x" });
});
it("uploadFile turns an error body into ApiError", async () => { /* 413 {code:"too_large", message} */ });
it("api.delete sends DELETE with CSRF and returns undefined on 204", async () => { /* mockApi */ });
```

- [ ] **Step 2:** `npx vitest run src/api/client.test.ts` → FAIL (no `uploadFile`).
- [ ] **Step 3: implement**

```ts
export function uploadFile<T>(path: string, file: File, onProgress?: (fraction: number) => void): Promise<T> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", `/api/v1${path}`);
    xhr.withCredentials = true;
    xhr.setRequestHeader("Accept", "application/json");
    if (csrfToken) xhr.setRequestHeader("X-CSRF-Token", csrfToken);
    xhr.upload.onprogress = (e) => e.lengthComputable && onProgress?.(e.loaded / e.total);
    xhr.onerror = () => reject(new ApiError(0, "network", "Could not reach the server.", "-"));
    xhr.onload = () => { /* parse JSON; 2xx → resolve; else ApiError (401 → listeners) */ };
    const form = new FormData();
    form.append("file", file);
    xhr.send(form);
  });
}
// api.delete = (path) => request<void>("DELETE", path)
```

Hooks: `keys.reviewers(archived)`, `keys.reviewer(key)`, `keys.reviewSettings`, `keys.models`,
`keys.paperFiles(id)`; `useReviewers`, `useReviewer`, `useSaveReviewer({key|null, baseVersion, body})`,
`useArchiveReviewer`, `useReviewSettings`, `useSaveReviewSettings`, `useModelsAvailable`, `usePaperFiles`,
`useUploadPaperFile`, `useDeletePaperFile` (both invalidate files and the paper drawer).

- [ ] **Step 4:** tests pass; full check; commit `API client: uploads with progress, delete, review settings and reviewer hooks`.

### Task 2: Settings shell, frame and guard

**Files:** Create `features/settings/SettingsFrame.tsx`, `dirtyGuard.tsx`, `useSettingsSave.ts`; Modify
`pages/SettingsPage.tsx`, `App.tsx`, `styles.css`, `test/fixtures.ts`, `pages/SettingsPage.test.tsx`.

- [ ] **Step 1: failing tests:** tabs in order Sources · Reviewers · AI models · Screening · Full text · Users
  (Users admin only); a dirty tab makes a tab click ask `confirm` and cancelling keeps the tab.
- [ ] **Step 3:** `SettingsFrame({title,intro,version,admin,dirty,onReset,onSave,saving,stale,problem,message,children})`
  renders `<h2>`, intro, badge "Used by next run · v3", read-only banner for non-admins ("Only admins change
  these settings. You can read them; runs use them as shown."), children, then note input + Reset + Save
  (admins). `useSettingsSave()` returns `save(patch, note)` = POST `{...current content, ...patch, note,
  base_version}`, maps 409 `stale_version` to `stale`, 422 to `problem`.
- [ ] **Step 5:** commit `Settings: tabs for reviewers, models, screening and full text; shared frame and unsaved guard`.

### Task 3: Screening tab

**Files:** Create `features/settings/screening.ts`, `screening.test.ts`, `ScreeningTab.tsx`; tests in `SettingsPage.test.tsx`.

- [ ] **Step 1: failing unit tests**

```ts
expect(fromEvals({ include: 0.6, exclude: 0.9 })).toEqual({ keep_min: 0.8, include_fail_max: 0.05 });
expect(validateScreening({ keep_min: 0.8, include_fail_max: 0.9, exclude_hit_min: 0.95, exclude_clear_max: 0.2 }))
  .toEqual(["“Drop below” for inclusion criteria must be lower than “Keep from”."]);
expect(bands(0.05, 0.8)).toEqual({ low: 5, middle: 75, high: 20 }); // 5 % steps, sums to 100
```

- [ ] **Step 3:** `fromEvals(pair) = { keep_min: round2((1+include)/2), include_fail_max: round2((1-exclude)/2) }`.
  Tab: two groups (Inclusion: "Keep from", "Drop at or below"; Exclusion: "Drop from", "Clear at or below"),
  each value a linked range + number input (step 0.01), a band strip with words ("drop · ask the LLM · keep"),
  the Evals card (latest eval with `headline.recommended`), "Apply to inclusion criteria" button when the
  mapped values differ.
- [ ] tests: admin edits via number input and saves `{screening:{...}}` with note; invalid band → alert and no
  POST; Apply sets 0.55/0.15 for pair 0.1/0.7; reset restores defaults; viewer read-only (inputs disabled).
- [ ] commit `Settings → Screening: four thresholds with bands, Evals recommendation mapped for inclusion criteria`.

### Task 4: Full text tab

- [ ] tests: toggles per source with explanation; Unpaywall on + empty contact → alert "Unpaywall needs a
  contact email"; max length 1000–500000 chars; upload limit 1–30 MB; save posts `fulltext`; 422 message shown.
- [ ] commit `Settings → Full text: sources, contact, length and upload limits`.

### Task 5: AI models tab

**Files:** `features/settings/models.ts` (+ test), rewrite `ModelsTab.tsx` (keeps the worker key table below).

- [ ] unit: `providerOf("anthropic:claude-x") === "anthropic"`; `sharedFamily(["anthropic:a","anthropic:b"]) === "anthropic"`,
  `null` when mixed or any unknown; `modelOptions(models, current)` includes current when unavailable.
- [ ] component: rows Plan, Screen, Screen (per criterion), Extract, one per panel reviewer, Editor; a select
  each; warning chip when one family; save changed reviewer models as reviewer versions, then settings.
- [ ] commit `Settings → AI models: a model per role from the available ones, one-family warning`.

### Task 6: Reviewers tab and editor

**Files:** `features/settings/reviewerForm.ts` (+ test), `ReviewersTab.tsx`, `ReviewerEditor.tsx`,
`pages/ReviewerEditor.test.tsx`; routes `/settings/reviewers`, `/settings/reviewers/new`, `/settings/reviewers/:key`.

- [ ] unit: `formFromVersion`, `toBody` (trims, drops empty items), `validateReviewer` (name, perspective, 1–20
  items, text ≤ 500), `previewText(form)` = perspective + numbered "key. text" only.
- [ ] cards: name, first sentence of perspective, "N items", model, "In default panel" switch (checkbox with
  words), panel count "3 of 5", refuse 0 with message; Editor card (instructions) saved with the settings;
  "New reviewer" link; archived list toggle with Restore.
- [ ] editor: name, perspective textarea, items (text, source select CLAIM/TRIPOD+AI/other, weight segmented
  radio 1·2·3 "low/normal/high", pass if yes/no, red flag if never/yes/no), add/move/remove; live preview
  region "What the model reads" with the note "Weights and red-flag rules are applied by code afterwards and
  are never shown to the model."; save `Save as vN` with note; 409 reload; Reset to default when `default`.
- [ ] commit `Settings → Reviewers: cards, default panel, editor with checklist items and a live model preview`.

### Task 7: Papers table

- [ ] tests: panel row shows "72 · 8/10 answered", "2 red flags", "full text"; legacy row shows rank score and
  "–"; "Has red flags" chip sends `has_red_flags=true` and survives reload (URL `flags=true`).
- [ ] commit `Papers: panel score with coverage, red flags and text source; Has red flags filter`.

### Task 8: Drawer peer review

**Files:** `features/papers/panel.ts` (+ test), `PeerReview.tsx`, `PaperDrawer.tsx`, `drawer.test.tsx`.

- [ ] unit: `answerWord("not_reported") === "not reported"`, icons ✓ ✗ ? –; `coverageText(0.8, answers)`.
- [ ] component: Editor verdict first ("Editor: include — reason"), disagreements "Methodologist and
  Statistician disagree on m3: note"; reviewer `<details>` with table; red flags; text source sentence
  ("Reviewed on the full text from PMC (Methods, Results; 41 000 characters, truncated)").
- [ ] commit `Paper drawer: peer review step with the editor first, reviewer checklists and red flags`.

### Task 9: Drawer files

- [ ] tests: member sees "Upload full text (PDF)" when text_source is abstract; choosing a file uploads with
  progress then lists it; 413 message shown; non-PDF refused client-side; delete asks confirm and calls DELETE;
  viewer sees the list without upload/download; download link for members.
- [ ] commit `Paper drawer: upload, list, download and delete full-text PDFs`.

### Task 10: e2e, a11y, docs

- [ ] `scripts/e2e_server.py`: `RESEARCH_UPLOADS_DIR` under the e2e base.
- [ ] flows: admin edits Methodologist (adds an item) → member starts a demo run → drawer shows "Peer review"
  with the editor verdict; member uploads a tiny PDF to a paper and sees it listed. a11y: each new tab (admin +
  viewer) and the drawer with the panel.
- [ ] `docs/web-app.md` frontend section; `npm run e2e` green; stop servers on 8000/4173.
- [ ] commit `E2E and docs for the review panel screens`.

## Self-review

- Spec coverage: tabs + intro/defaults/reset/one save/badge/read-only/guard (T2–T6); Reviewers cards, editor,
  weights, red flag, source, preview (T6); AI models dropdowns + family warning (T5); Screening sliders +
  Evals (T3); Full text (T4); Papers columns/filter/sort (T7); drawer panel (T8) and upload (T9); e2e + axe (T10).
- Types: every hook uses the aliases added in T1; `ReviewSettingsContent` is the one shape tabs patch.
- Deviation from the skill: tasks list test cases and key code rather than every line of JSX, which follows the
  existing components' patterns (FieldEditorPage, SourcesTab).
