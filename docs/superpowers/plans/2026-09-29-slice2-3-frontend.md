# Web app slice 2, plan 3: Frontend (fields, sources, settings) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The React app gets Fields (list, editor with versions, criteria test), Settings (Sources, AI models, Users), and Papers/drawer views that name the criterion that decided each paper.

**Architecture:** Pages stay thin (`web/src/pages/*`) and delegate to feature folders (`web/src/features/fields`, `web/src/features/settings`, `web/src/features/papers`). Pure logic (form validation, version diff, labels, URL state) lives in `.ts` modules with unit tests; components use TanStack Query hooks from `web/src/api/hooks.ts` and only the generated types in `web/src/api/schema.d.ts`. Fields added by slice 2 to existing responses are optional in TS and read with `?? default`, so legacy data (only `topic_match`) keeps rendering as today.

**Tech Stack:** React 18, react-router-dom 7, TanStack Query 5, TypeScript 5.6 strict, Vitest 5 + Testing Library, Playwright + axe.

**Spec:** `docs/superpowers/specs/2026-09-28-fields-and-sources-design.md` (Screens, Testing → Frontend, Plans → 3, Success criteria). Mockups: `.superpowers/brainstorm/69621-1790603513/content/{domain-editor,settings-sources-en,screening-criteria}.html` (UI text in English; "Domenii" is "Fields").

## Decisions (taken without asking, per the user's instruction)

1. **Routes.** `/fields` (list, all roles), `/fields/new` (members), `/fields/:fieldId` (editor; read-only for viewers and for archived fields), `/settings` → `/settings/sources`, `/settings/models`, `/settings/users` (admins only). `/users` redirects to `/settings/users`. Settings is visible to every role; only admins see write controls and the Users tab.
2. **Start run per field** links to `/runs?field=<id>`; the Runs start form preselects that field. The start form lists non-archived fields as `name · vN`.
3. **Criteria test** needs a saved field (the API test endpoint is per field id), but always sends the editor's *current form* as `draft`, so unsaved edits are what gets tested. A "Demo mode" box sends `mode: "demo"` (offline stand-in for Jev). The form is validated before testing.
4. **Saving needs at least one inclusion or exclusion criterion.** A legacy field (only `topic_match`) is shown with a notice; adding criteria and saving creates v2.
5. **Stale save (409 `stale_version`)** shows the server message and a "Reload the latest version" button that refetches the field; the editor remounts on the new version (unsaved edits are discarded, and the notice says so).
6. **Measurement notice.** "Screening for this field (vN): measured against <gold set>" only when an eval exists whose run belongs to this field *and* the current version; otherwise "not measured". Computed from `/runs` and `/evals` (no new endpoint).
7. **Version diff** is a set diff per section (name, topic, inclusion, exclusion, legacy, sources, years); every line carries the word `added`, `removed` or `unchanged` (not colour only). A reworded criterion shows as removed + added.
8. **Criterion names** are derived from keys: `i1` → "incl 1", `e2` → "excl 2", anything else → key with spaces ("topic match"). A run is "legacy" when none of its criteria keys look like `i<n>`/`e<n>`; legacy runs render exactly as before (probability, sortable column, topic-match range filter).
9. **Papers Criteria cell:** "dropped by incl 1 (0.01)" when Jev decided, "dropped by excl 1 (LLM: yes)" when the LLM decided, "all met" when kept, "not screened" for tier `rule`, otherwise "no single criterion decided". The criteria of a run come from `GET /fields/{id}/versions/{run.field_version}`; without a version, from the keys in the visible rows.
10. **Deciding cell** in the test table and the drawer table carries the word "decided" and an outline (never colour alone).
11. **Source check** polls the job and then refetches the sources; the Last check cell says `✓ OK · 0.8 s · <time>` / `✗ failed: <error>` / `never checked` in words.
12. **e2e dataset:** the existing `scripts/e2e_server.py` dataset (imported demo run + toy eval, `europepmc` enabled by the migration) is enough: the Playwright flow creates its own field, tests it in demo mode and starts a demo run. No dataset change unless a test proves it needed.

## File structure

Create:
- `web/src/features/fields/labels.ts` (+ `labels.test.ts`): source and criterion labels, dates.
- `web/src/features/fields/fieldForm.ts` (+ `fieldForm.test.ts`): editor state, validation, request bodies, reorder.
- `web/src/features/fields/versionDiff.ts` (+ `versionDiff.test.ts`): diff of two versions.
- `web/src/features/fields/CriteriaList.tsx`: one editable criteria list.
- `web/src/features/fields/FieldSidePanel.tsx`: history, runs per version, measurement, diff.
- `web/src/features/fields/CriteriaTestPanel.tsx` (+ `CriteriaTestPanel.test.tsx`).
- `web/src/pages/FieldsPage.tsx` (+ test), `web/src/pages/FieldEditorPage.tsx` (+ test).
- `web/src/pages/SettingsPage.tsx` (+ test), `web/src/features/settings/SourcesTab.tsx`, `web/src/features/settings/ModelsTab.tsx`.

Modify: `web/src/api/types.ts`, `web/src/api/hooks.ts`, `web/src/App.tsx`, `web/src/components/Layout.tsx`, `web/src/pages/UsersPage.tsx`, `web/src/pages/RunsPage.tsx`, `web/src/features/runs/StartRunForm.tsx`, `web/src/features/runs/RunList.tsx`, `web/src/features/papers/{cells.tsx,PaperTable.tsx,FilterBar.tsx,papersState.ts,PaperDrawer.tsx}`, `web/src/pages/PapersPage.tsx`, `web/src/styles.css`, `web/src/test/fixtures.ts`, existing tests, `web/e2e/*.spec.ts`, `docs/web-app.md`.

Every commit in `web/` is preceded by: `cd web && npm run typecheck && npm run lint && npm test && npm run build`.
Commits stage exact paths and end with the trailer `-m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"`.

---

### Task 1: API types, hooks, labels and fixtures

**Files:**
- Modify: `web/src/api/types.ts`, `web/src/api/hooks.ts`, `web/src/pages/RunsPage.tsx` (new `useFields` signature), `web/src/test/fixtures.ts`
- Create: `web/src/features/fields/labels.ts`, `web/src/features/fields/labels.test.ts`

- [ ] **Step 1: Write the failing test**

**File: `web/src/features/fields/labels.test.ts`**

```ts
import { describe, expect, it } from "vitest";

import { criterionLabel, isFieldCriterion, sourceLabel } from "./labels";

describe("labels", () => {
  it("names field criteria by kind and position, and anything else by its key", () => {
    expect(criterionLabel("i1")).toBe("incl 1");
    expect(criterionLabel("e12")).toBe("excl 12");
    expect(criterionLabel("topic_match")).toBe("topic match");
    expect(isFieldCriterion("i3")).toBe(true);
    expect(isFieldCriterion("topic_match")).toBe(false);
  });

  it("names the sources, and passes unknown names through", () => {
    expect(sourceLabel("europepmc")).toBe("Europe PMC");
    expect(sourceLabel("openalex")).toBe("OpenAlex");
    expect(sourceLabel("arxiv")).toBe("arXiv");
    expect(sourceLabel("somewhere")).toBe("somewhere");
  });
});
```

- [ ] **Step 2: Run it to verify it fails** — `cd web && npx vitest run src/features/fields/labels.test.ts` → FAIL (cannot resolve `./labels`).

- [ ] **Step 3: Implement**

**File: `web/src/features/fields/labels.ts`**

```ts
export const SOURCE_NAMES = ["europepmc", "openalex", "arxiv"] as const;
export type SourceName = (typeof SOURCE_NAMES)[number];

const SOURCE_LABEL: Record<string, string> = { europepmc: "Europe PMC", openalex: "OpenAlex", arxiv: "arXiv", demo: "demo" };

export const sourceLabel = (name: string) => SOURCE_LABEL[name] ?? name;
export const isSourceName = (name: string): name is SourceName => (SOURCE_NAMES as readonly string[]).includes(name);

const FIELD_KEY = /^([ie])(\d+)$/;

/** True for the keys a field's criteria get on save (i1.., e1..); false for legacy keys such as topic_match. */
export const isFieldCriterion = (key: string) => FIELD_KEY.test(key);

/** "i1" -> "incl 1", "e2" -> "excl 2", "topic_match" -> "topic match". */
export function criterionLabel(key: string): string {
  const match = FIELD_KEY.exec(key);
  if (!match) return key.replace(/_/g, " ");
  return `${match[1] === "i" ? "incl" : "excl"} ${match[2]}`;
}

export const shortDate = (iso: string) => new Date(iso).toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
```

**File: `web/src/api/types.ts`**

```ts
import type { components } from "./schema";

type S = components["schemas"];

export type UserOut = S["UserOut"];
export type SessionOut = S["SessionOut"];
export type FieldOut = S["FieldOut"];
export type FieldVersionOut = S["FieldVersionOut"];
export type FieldVersionSummary = S["FieldVersionSummary"];
export type FieldDraft = S["FieldDraft"];
export type RunOut = S["RunOut"];
export type RunDetailOut = S["RunDetailOut"];
export type RunCounts = S["RunCounts"];
export type PaperRow = S["PaperRow"];
export type PaperPage = S["PaperPage"];
export type ScreenCell = S["ScreenCell"];
export type DrawerOut = S["DrawerOut"];
export type ScreeningOut = S["ScreeningOut"];
export type CriterionRowOut = S["CriterionRowOut"];
export type CallOut = S["CallOut"];
export type StageOut = S["StageOut"];
export type EvalSummaryOut = S["EvalSummaryOut"];
export type EvalDetailOut = S["EvalDetailOut"];
export type JobOut = S["JobOut"];
export type StartRunOut = S["StartRunOut"];
export type ReviewOut = S["ReviewOut"];
export type SourceOut = S["SourceOut"];
export type SettingsOut = S["SettingsOut"];
export type WorkerStatusOut = S["WorkerStatusOut"];

/** A job's `progress` while running ({status, done, total}) and when done ({status, result}). */
export type JobProgressData = { status?: string; done?: number; total?: number; result?: unknown };

export type TestDecision = "include" | "exclude" | "escalate" | "not_screened";
export type CriteriaTestPaper = {
  source_id: string; title: string; year: number | null; sources: string[];
  probabilities: Record<string, number>; decision: TestDecision; decided_by: string | null;
};
/** `progress.result` of a finished criteria_test job. */
export type CriteriaTestResult = {
  mode: string; topic: string; criteria: { key: string; kind: "include" | "exclude"; text: string }[]; sources: string[];
  model_version: string | null; papers: CriteriaTestPaper[];
  summary: { total: number; kept: number; dropped: number; to_llm: number; not_screened: number };
  field_id: string | null; version: number | null;
};
/** `progress.result` of a finished source_check job. */
export type SourceCheckResult = { ok: boolean; ms: number; count: number; error: string | null };

export type Role = "viewer" | "member" | "admin";
export const ROLE_ORDER: Record<Role, number> = { viewer: 0, member: 1, admin: 2 };
export const hasRole = (user: { role: string } | null | undefined, minimum: Role): boolean =>
  !!user && (ROLE_ORDER[user.role as Role] ?? -1) >= ROLE_ORDER[minimum];
```

**File: `web/src/api/hooks.ts`**

```ts
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "./client";
import type {
  CallOut, DrawerOut, EvalDetailOut, EvalSummaryOut, FieldDraft, FieldOut, FieldVersionOut, JobOut, PaperPage, RunDetailOut, RunOut,
  SettingsOut, SourceOut, StageOut, StartRunOut, UserOut, WorkerStatusOut,
} from "./types";

export type PaperParams = {
  page: number; page_size: number; sort: string; direction: "asc" | "desc";
  decision?: string; tier?: string; escalated?: boolean; in_sr?: boolean; criterion?: string; p_min?: number; p_max?: number;
  decided_by?: string; source?: string;
};

export const keys = {
  allFields: ["fields"] as const,
  fields: (archived: boolean) => ["fields", { archived }] as const,
  field: (id: string) => ["field", id] as const,
  fieldVersion: (id: string, version: number) => ["field", id, "version", version] as const,
  runs: ["runs"] as const,
  run: (id: string) => ["run", id] as const,
  papers: (runId: string, params: PaperParams) => ["papers", runId, params] as const,
  paper: (runId: string, paperId: string) => ["paper", runId, paperId] as const,
  stages: ["stages"] as const,
  evals: ["evals"] as const,
  eval: (id: string) => ["eval", id] as const,
  job: (id: string) => ["job", id] as const,
  call: (runId: string, key: string) => ["call", runId, key] as const,
  users: ["users"] as const,
  sources: ["sources"] as const,
  settings: ["settings"] as const,
  workers: ["workers"] as const,
};

export const newIdempotencyKey = () =>
  globalThis.crypto?.randomUUID?.() ?? `k-${Date.now()}-${Math.random().toString(16).slice(2)}`;

export const useFields = ({ enabled = true, archived = false }: { enabled?: boolean; archived?: boolean } = {}) =>
  useQuery({ queryKey: keys.fields(archived), enabled, queryFn: () => api.get<FieldOut[]>("/fields", { archived }) });
export const useField = (id: string | null) =>
  useQuery({ queryKey: keys.field(id ?? ""), enabled: !!id, queryFn: () => api.get<FieldOut>(`/fields/${id}`) });
export const useFieldVersion = (id: string | null, version: number | null | undefined) =>
  useQuery({
    queryKey: keys.fieldVersion(id ?? "", version ?? 0), enabled: !!id && !!version, retry: false,
    queryFn: () => api.get<FieldVersionOut>(`/fields/${id}/versions/${version}`),
  });
export const useRuns = () => useQuery({ queryKey: keys.runs, queryFn: () => api.get<RunOut[]>("/runs") });
export const useRun = (id: string | null) =>
  useQuery({ queryKey: keys.run(id ?? ""), enabled: !!id, queryFn: () => api.get<RunDetailOut>(`/runs/${id}`) });
export const usePapers = (runId: string | null, params: PaperParams) =>
  useQuery({
    queryKey: keys.papers(runId ?? "", params), enabled: !!runId, placeholderData: keepPreviousData,
    queryFn: () => api.get<PaperPage>(`/runs/${runId}/papers`, params),
  });
export const usePaper = (runId: string | null, paperId: string | null) =>
  useQuery({ queryKey: keys.paper(runId ?? "", paperId ?? ""), enabled: !!runId && !!paperId, queryFn: () => api.get<DrawerOut>(`/runs/${runId}/papers/${paperId}`) });
export const useStages = () => useQuery({ queryKey: keys.stages, queryFn: () => api.get<StageOut[]>("/stages") });
export const useEvals = () => useQuery({ queryKey: keys.evals, queryFn: () => api.get<EvalSummaryOut[]>("/evals") });
export const useEval = (id: string | null) =>
  useQuery({ queryKey: keys.eval(id ?? ""), enabled: !!id, queryFn: () => api.get<EvalDetailOut>(`/evals/${id}`) });
export const useCall = (runId: string, key: string | null) =>
  useQuery({ queryKey: keys.call(runId, key ?? ""), enabled: !!key, retry: false, queryFn: () => api.get<CallOut>(`/runs/${runId}/calls/${key}`) });
export const useUsers = () => useQuery({ queryKey: keys.users, queryFn: () => api.get<UserOut[]>("/users") });
export const useSources = () => useQuery({ queryKey: keys.sources, queryFn: () => api.get<SourceOut[]>("/sources") });
export const useSettings = () => useQuery({ queryKey: keys.settings, queryFn: () => api.get<SettingsOut>("/settings") });
export const useWorkers = () => useQuery({ queryKey: keys.workers, queryFn: () => api.get<WorkerStatusOut[]>("/workers/status") });

/** Polls every 2 seconds while the job is queued or running. */
export const useJob = (id: string | null) =>
  useQuery({
    queryKey: keys.job(id ?? ""), enabled: !!id, queryFn: () => api.get<JobOut>(`/jobs/${id}`),
    refetchInterval: (query) => (["queued", "running"].includes(query.state.data?.status ?? "") ? 2000 : false),
  });

export function useStartRun() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body: { field_id: string; max_papers: number; mode: "live" | "demo" }) =>
      api.post<StartRunOut>("/runs", { body, headers: { "Idempotency-Key": newIdempotencyKey() } }),
    onSuccess: () => client.invalidateQueries({ queryKey: keys.runs }),
  });
}

export function useResumeRun() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (runId: string) => api.post<StartRunOut>(`/runs/${runId}/resume`),
    onSuccess: () => client.invalidateQueries({ queryKey: keys.runs }),
  });
}

export type FieldBody = FieldDraft & { note: string };

/** Creates a field (fieldId null) or saves its next version against `baseVersion` (409 stale_version if it moved on). */
export function useSaveField() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ fieldId, baseVersion, body }: { fieldId: string | null; baseVersion: number | null; body: FieldBody }) =>
      fieldId
        ? api.post<FieldOut>(`/fields/${fieldId}/versions`, { body: { ...body, base_version: baseVersion } })
        : api.post<FieldOut>("/fields", { body }),
    onSuccess: (field) => {
      client.setQueryData(keys.field(field.id), field);
      void client.invalidateQueries({ queryKey: keys.allFields });
    },
  });
}

export function useArchiveField() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ fieldId, archive }: { fieldId: string; archive: boolean }) => api.post<FieldOut>(`/fields/${fieldId}/${archive ? "archive" : "unarchive"}`),
    onSuccess: (field) => {
      client.setQueryData(keys.field(field.id), field);
      void client.invalidateQueries({ queryKey: keys.allFields });
    },
  });
}

export const useTestCriteria = () =>
  useMutation({
    mutationFn: ({ fieldId, draft, mode }: { fieldId: string; draft: FieldDraft; mode: "live" | "demo" }) =>
      api.post<JobOut>(`/fields/${fieldId}/test`, { body: { draft, mode } }),
  });

export function usePatchSource() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ name, ...body }: { name: string; enabled?: boolean; max_results?: number }) => api.patch<SourceOut>(`/sources/${name}`, { body }),
    onSuccess: () => client.invalidateQueries({ queryKey: keys.sources }),
  });
}

export const useCheckSource = () => useMutation({ mutationFn: (name: string) => api.post<JobOut>(`/sources/${name}/check`) });

export function usePatchSettings() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body: { contact_email: string | null }) => api.patch<SettingsOut>("/settings", { body }),
    onSuccess: (settings) => client.setQueryData(keys.settings, settings),
  });
}

export function useCreateUser() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body: { email: string; name: string; role: string; password: string }) => api.post<UserOut>("/users", { body }),
    onSuccess: () => client.invalidateQueries({ queryKey: keys.users }),
  });
}

export function usePatchUser() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ id, ...body }: { id: string; role?: string; active?: boolean; name?: string; password?: string }) => api.patch<UserOut>(`/users/${id}`, { body }),
    onSuccess: () => client.invalidateQueries({ queryKey: keys.users }),
  });
}
```

`web/src/pages/RunsPage.tsx`: replace `const fields = useFields(canRun);` with `const fields = useFields({ enabled: canRun });`.

Append to `web/src/test/fixtures.ts` (and add `CriteriaTestResult, FieldVersionOut, SourceOut, WorkerStatusOut` to its type import):

```ts
export const versionOut = (over: Partial<FieldVersionOut> = {}): FieldVersionOut => ({
  version: 2, name: "ML CT-FFR", topic: "deep learning CT-FFR",
  include: [{ key: "i1", text: "The study uses machine learning or deep learning." }, { key: "i2", text: "FFR is estimated from coronary CT angiography." }],
  exclude: [{ key: "e1", text: "The paper is a review or an editorial." }],
  legacy: [], sources: ["europepmc"], years: { from: 2018, to: null }, note: "added the exclusion", imported: false,
  created_by_name: "Mia Member", created_at: "2026-09-28T10:00:00Z", run_count: 1, ...over,
});

export const legacyVersion = (): FieldVersionOut => versionOut({
  version: 1, include: [], exclude: [], legacy: [{ key: "topic_match", text: "The paper's central subject is the topic." }],
  years: { from: null, to: null }, note: "imported", imported: true, created_by_name: null, created_at: "2026-09-26T08:00:00Z", run_count: 3,
});

export const fieldDetail = (over: Partial<FieldOut> = {}): FieldOut => ({
  ...fieldOut(), current_version: 2, archived_at: null, current: versionOut(),
  last_run: { id: RUN_ID, kind: "research", status: "done", created_at: "2026-09-28T11:00:00Z", field_version: 2 },
  versions: [
    { version: 2, note: "added the exclusion", imported: false, created_by_name: "Mia Member", created_at: "2026-09-28T10:00:00Z", run_count: 1, include_count: 2, exclude_count: 1 },
    { version: 1, note: "imported", imported: true, created_by_name: null, created_at: "2026-09-26T08:00:00Z", run_count: 3, include_count: 0, exclude_count: 0 },
  ],
  ...over,
});

export const legacyField = (): FieldOut => fieldDetail({
  current_version: 1, current: legacyVersion(), last_run: null,
  versions: [{ version: 1, note: "imported", imported: true, created_by_name: null, created_at: "2026-09-26T08:00:00Z", run_count: 3, include_count: 0, exclude_count: 0 }],
});

export const sourceRows = (): SourceOut[] => [
  { name: "europepmc", label: "Europe PMC", enabled: true, max_results: 100, last_check_at: "2026-09-28T10:12:00Z", last_check_ok: true, last_check_ms: 800, last_check_error: null },
  { name: "openalex", label: "OpenAlex", enabled: false, max_results: 100, last_check_at: null, last_check_ok: null, last_check_ms: null, last_check_error: null },
  { name: "arxiv", label: "arXiv", enabled: false, max_results: 50, last_check_at: "2026-09-28T10:13:00Z", last_check_ok: false, last_check_ms: 30000, last_check_error: "SourceUnavailable: arxiv" },
];

export const workerRows = (): WorkerStatusOut[] => [
  { role: "screen", provider: "anthropic", model: "claude-sonnet-5", key_present: true, key_accepted: true, detail: "", checked_at: "2026-09-28T10:00:00Z", worker_id: "w1" },
  { role: "adjudicate", provider: "openai", model: "gpt-6", key_present: true, key_accepted: false, detail: "rejected (401)", checked_at: "2026-09-28T10:00:00Z", worker_id: "w1" },
  { role: "jev", provider: "typesafe", model: "jev-latest", key_present: false, key_accepted: null, detail: "", checked_at: "2026-09-28T10:00:00Z", worker_id: "w1" },
];

export const testResult = (over: Partial<CriteriaTestResult> = {}): CriteriaTestResult => ({
  mode: "demo", topic: "deep learning CT-FFR",
  criteria: [{ key: "i1", kind: "include", text: "The study uses machine learning or deep learning." }, { key: "e1", kind: "exclude", text: "The paper is a review or an editorial." }],
  sources: ["europepmc"], model_version: "demo-jev",
  papers: [
    { source_id: "MED:1", title: "Deep learning CT-FFR against invasive FFR", year: 2020, sources: ["europepmc"], probabilities: { i1: 0.97, e1: 0.02 }, decision: "include", decided_by: null },
    { source_id: "MED:2", title: "Machine learning in cardiac imaging: a review", year: 2021, sources: ["europepmc"], probabilities: { i1: 0.93, e1: 0.96 }, decision: "exclude", decided_by: "e1" },
    { source_id: "MED:3", title: "A paper without an abstract", year: 2019, sources: ["europepmc"], probabilities: {}, decision: "not_screened", decided_by: null },
  ],
  summary: { total: 3, kept: 1, dropped: 1, to_llm: 0, not_screened: 1 }, field_id: FIELD_ID, version: null, ...over,
});
```

- [ ] **Step 4: Run** `npx vitest run src/features/fields/labels.test.ts` → PASS; then the full pre-commit check.
- [ ] **Step 5: Commit** `git add web/src/api/types.ts web/src/api/hooks.ts web/src/pages/RunsPage.tsx web/src/test/fixtures.ts web/src/features/fields/labels.ts web/src/features/fields/labels.test.ts && git commit -m "Web: types, hooks and labels for fields, sources, settings and workers" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"`

---

### Task 2: Navigation, routes and the Settings shell (Users moves under Settings)

**Files:**
- Modify: `web/src/App.tsx`, `web/src/components/Layout.tsx`, `web/src/pages/UsersPage.tsx` (heading becomes `h2`), `web/src/components/layout.test.tsx`, `web/src/styles.css`
- Create: `web/src/pages/SettingsPage.tsx`, placeholder-free stubs are not used: the Sources and AI models tabs arrive in Tasks 3–4, so this task routes `sources` and `models` to them after they exist. To keep this task self-contained, Task 2 creates `SettingsPage` and routes only `users`; Tasks 3 and 4 add their routes.

- [ ] **Step 1: Failing tests** — in `layout.test.tsx` replace the two Users tests and the nav check with:

```tsx
  it("shows the main navigation, the user and a skip link", async () => {
    mockApi({ "GET /api/v1/auth/me": { body: session("member") } });
    renderApp("/");
    const nav = await screen.findByRole("navigation", { name: "Main" });
    expect(within(nav).getAllByRole("link").map((link) => link.textContent)).toEqual(["Papers", "Runs", "Fields", "Evals", "System map", "Settings"]);
    expect(screen.getByRole("link", { name: "Skip to content" })).toHaveAttribute("href", "#main");
    expect(screen.getByText("Member")).toBeInTheDocument();
  });

  it("offers the Users tab under Settings to admins only", async () => {
    mockApi({ "GET /api/v1/auth/me": { body: session("admin") }, "GET /api/v1/users": { body: [] } });
    renderApp("/users");
    const tabs = await screen.findByRole("navigation", { name: "Settings sections" });
    expect(within(tabs).getByRole("link", { name: "Users" })).toHaveAttribute("aria-current", "page");
    expect(await screen.findByRole("heading", { name: "Users" })).toBeInTheDocument();
  });

  it("blocks the Users tab for members and does not offer it", async () => {
    mockApi({ "GET /api/v1/auth/me": { body: session("member") } });
    renderApp("/users");
    expect(await screen.findByRole("heading", { name: "Not allowed" })).toBeInTheDocument();
    expect(within(screen.getByRole("navigation", { name: "Settings sections" })).queryByRole("link", { name: "Users" })).not.toBeInTheDocument();
  });
```
(import `within` from `@testing-library/react`). Run `npx vitest run src/components/layout.test.tsx` → FAIL.

- [ ] **Step 2: Implement**

**File: `web/src/pages/SettingsPage.tsx`**

```tsx
import { NavLink, Outlet } from "react-router-dom";

import { hasRole } from "../api/types";
import { useAuth } from "../auth/AuthProvider";

export function SettingsPage() {
  const { user } = useAuth();
  const admin = hasRole(user, "admin");
  return (
    <section>
      <h1>Settings</h1>
      <nav aria-label="Settings sections" className="tabs">
        <NavLink to="/settings/sources">Sources</NavLink>
        <NavLink to="/settings/models">AI models</NavLink>
        {admin && <NavLink to="/settings/users">Users</NavLink>}
      </nav>
      {!admin && <p className="sub">Read-only: only admins change settings.</p>}
      <Outlet />
    </section>
  );
}
```

**File: `web/src/components/Layout.tsx`** — the nav becomes:

```tsx
        <nav aria-label="Main">
          <NavLink to="/" end>Papers</NavLink>
          <NavLink to="/runs">Runs</NavLink>
          <NavLink to="/fields">Fields</NavLink>
          <NavLink to="/evals">Evals</NavLink>
          <NavLink to="/system">System map</NavLink>
          <NavLink to="/settings">Settings</NavLink>
        </nav>
```
(remove the `hasRole` import).

**File: `web/src/App.tsx`** (final form after Tasks 2–7; in Task 2 only the `settings` subtree with `users` and the `/users` redirect are added):

```tsx
import { Navigate, Route, Routes } from "react-router-dom";

import { RequireAuth, RequireRole } from "./auth/RequireAuth";
import { AuthProvider } from "./auth/AuthProvider";
import { Layout } from "./components/Layout";
import { ModelsTab } from "./features/settings/ModelsTab";
import { SourcesTab } from "./features/settings/SourcesTab";
import { EvalsPage } from "./pages/EvalsPage";
import { FieldEditorPage } from "./pages/FieldEditorPage";
import { FieldsPage } from "./pages/FieldsPage";
import { LoginPage } from "./pages/LoginPage";
import { PapersPage } from "./pages/PapersPage";
import { RunsPage } from "./pages/RunsPage";
import { SettingsPage } from "./pages/SettingsPage";
import { SystemMapPage } from "./pages/SystemMapPage";
import { UsersPage } from "./pages/UsersPage";

export function App() {
  return (
    <AuthProvider>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route element={<RequireAuth />}>
          <Route element={<Layout />}>
            <Route path="/" element={<PapersPage />} />
            <Route path="/runs" element={<RunsPage />} />
            <Route path="/fields" element={<FieldsPage />} />
            <Route element={<RequireRole role="member" />}>
              <Route path="/fields/new" element={<FieldEditorPage />} />
            </Route>
            <Route path="/fields/:fieldId" element={<FieldEditorPage />} />
            <Route path="/evals" element={<EvalsPage />} />
            <Route path="/evals/:evalId" element={<EvalsPage />} />
            <Route path="/system" element={<SystemMapPage />} />
            <Route path="/settings" element={<SettingsPage />}>
              <Route index element={<Navigate to="sources" replace />} />
              <Route path="sources" element={<SourcesTab />} />
              <Route path="models" element={<ModelsTab />} />
              <Route element={<RequireRole role="admin" />}>
                <Route path="users" element={<UsersPage />} />
              </Route>
            </Route>
            <Route path="/users" element={<Navigate to="/settings/users" replace />} />
          </Route>
        </Route>
      </Routes>
    </AuthProvider>
  );
}
```

`UsersPage.tsx`: `<h1>Users</h1>` → `<h2>Users</h2>`.

Append to `web/src/styles.css`:

```css
.tabs { display: flex; gap: 4px; margin: 0 0 12px; border-bottom: 1px solid var(--line); }
.tabs a { padding: 6px 10px; color: var(--fg); text-decoration: none; }
.tabs a[aria-current="page"] { font-weight: 600; box-shadow: inset 0 -2px 0 var(--accent); }
h2 { font-size: 16px; margin: 12px 0 8px; }
```

- [ ] **Step 3:** layout tests PASS; full check. **Commit** the listed files: "Web: Fields and Settings in the main menu; Users moves under Settings".

---

### Task 3: Settings → Sources (admin writes, read-only for others, Test with job polling)

**Files:** Create `web/src/features/settings/SourcesTab.tsx`, `web/src/pages/SettingsPage.test.tsx`; modify `web/src/App.tsx` (route `sources`), `web/src/styles.css`.

- [ ] **Step 1: Failing test**

**File: `web/src/pages/SettingsPage.test.tsx`**

```tsx
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import { setCsrfToken } from "../api/client";
import { ModelsTab } from "../features/settings/ModelsTab";
import { SourcesTab } from "../features/settings/SourcesTab";
import { JOB_ID, jobOut, session, sourceRows, workerRows } from "../test/fixtures";
import { mockApi } from "../test/mockApi";
import { renderWithProviders } from "../test/render";
import { SettingsPage } from "./SettingsPage";

afterEach(() => {
  vi.unstubAllGlobals();
  setCsrfToken(null);
});

function setup(role: "viewer" | "member" | "admin", route: string, extra: Parameters<typeof mockApi>[0] = {}) {
  const api = mockApi({
    "GET /api/v1/auth/me": { body: session(role) },
    "GET /api/v1/sources": { body: sourceRows() },
    "GET /api/v1/settings": { body: { contact_email: "lab@example.org" } },
    "GET /api/v1/workers/status": { body: workerRows() },
    ...extra,
  });
  renderWithProviders(
    <Routes>
      <Route path="/settings" element={<SettingsPage />}>
        <Route path="sources" element={<SourcesTab />} />
        <Route path="models" element={<ModelsTab />} />
      </Route>
    </Routes>,
    { route },
  );
  return api;
}

describe("Settings → Sources", () => {
  it("lists every source with its status and last check in words", async () => {
    setup("admin", "/settings/sources");
    const table = await screen.findByRole("table");
    const europe = within(table).getByRole("row", { name: /Europe PMC/ });
    expect(europe).toHaveTextContent("✓ OK · 0.8 s");
    expect(within(table).getByRole("row", { name: /OpenAlex/ })).toHaveTextContent("never checked");
    expect(within(table).getByRole("row", { name: /arXiv/ })).toHaveTextContent("✗ failed: SourceUnavailable: arxiv");
  });

  it("admins enable a source", async () => {
    const { calls } = setup("admin", "/settings/sources", { "PATCH /api/v1/sources/openalex": { body: { ...sourceRows()[1], enabled: true } } });
    await userEvent.click(await screen.findByRole("checkbox", { name: /OpenAlex/ }));
    await waitFor(() => expect(calls.find((c) => c.method === "PATCH")?.body).toEqual({ enabled: true }));
  });

  it("admins change max results, and a value outside 1 to 200 is refused before calling the server", async () => {
    const { calls } = setup("admin", "/settings/sources", { "PATCH /api/v1/sources/europepmc": { body: { ...sourceRows()[0], max_results: 50 } } });
    const input = await screen.findByLabelText("Max results per run for Europe PMC");
    await userEvent.clear(input);
    await userEvent.type(input, "500");
    await userEvent.click(screen.getByRole("button", { name: "Save max results for Europe PMC" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("1 to 200");
    expect(calls.some((c) => c.method === "PATCH")).toBe(false);
    await userEvent.clear(input);
    await userEvent.type(input, "50");
    await userEvent.click(screen.getByRole("button", { name: "Save max results for Europe PMC" }));
    await waitFor(() => expect(calls.find((c) => c.method === "PATCH")?.body).toEqual({ max_results: 50 }));
  });

  it("Test runs a check job and shows its result", async () => {
    const { calls } = setup("admin", "/settings/sources", {
      "POST /api/v1/sources/openalex/check": { status: 202, body: jobOut({ kind: "source_check", run_id: null }) },
      "GET /api/v1/jobs/:id": { body: jobOut({ kind: "source_check", status: "done", run_id: null, progress: { status: "done", result: { ok: true, ms: 1200, count: 1, error: null } } }) },
    });
    await userEvent.click(await screen.findByRole("button", { name: "Test OpenAlex" }));
    expect(await screen.findByText(/✓ OK · 1.2 s/)).toBeInTheDocument();
    expect(calls.some((c) => c.path === `/api/v1/jobs/${JOB_ID}`)).toBe(true);
  });

  it("saves the contact address, and an empty address clears it", async () => {
    const { calls } = setup("admin", "/settings/sources", { "PATCH /api/v1/settings": ({ body }) => ({ body }) });
    const input = await screen.findByLabelText("Contact address for public APIs");
    await userEvent.clear(input);
    await userEvent.click(screen.getByRole("button", { name: "Save contact address" }));
    await waitFor(() => expect(calls.find((c) => c.method === "PATCH")?.body).toEqual({ contact_email: null }));
  });

  it("is read-only for members and viewers", async () => {
    setup("member", "/settings/sources");
    await screen.findByRole("table");
    expect(screen.getByText(/Read-only/)).toBeInTheDocument();
    expect(screen.queryByRole("checkbox")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Test/ })).not.toBeInTheDocument();
    expect(screen.getByText(/lab@example.org/)).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Users" })).not.toBeInTheDocument();
  });
});
```

(Task 4 adds the AI models tests to this file.)

- [ ] **Step 2: Implement**

**File: `web/src/features/settings/SourcesTab.tsx`**

```tsx
import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useState, type FormEvent } from "react";

import { ApiError } from "../../api/client";
import { keys, useCheckSource, useJob, usePatchSettings, usePatchSource, useSettings, useSources } from "../../api/hooks";
import { hasRole, type SourceCheckResult, type SourceOut } from "../../api/types";
import { useAuth } from "../../auth/AuthProvider";
import { sourceLabel } from "../fields/labels";

const COVERS: Record<string, string> = {
  europepmc: "PubMed, PMC and biomedical preprints",
  openalex: "Anything with a DOI, including MICCAI, IEEE and SPIE",
  arxiv: "Preprints in cs.CV, eess.IV and physics.med-ph",
};
const errorText = (error: unknown) => (error instanceof ApiError ? error.message : "Could not reach the server.");
const seconds = (ms: number | null) => (ms === null ? "" : ` · ${(ms / 1000).toFixed(1)} s`);

function lastCheck(source: SourceOut): string {
  if (!source.last_check_at) return "never checked";
  const when = new Date(source.last_check_at).toLocaleString();
  return source.last_check_ok
    ? `✓ OK${seconds(source.last_check_ms)} · ${when}`
    : `✗ failed: ${source.last_check_error ?? "no details"}${seconds(source.last_check_ms)} · ${when}`;
}

function CheckStatus({ source, jobId }: { source: SourceOut; jobId: string | null }) {
  const job = useJob(jobId);
  const client = useQueryClient();
  const finished = job.data?.status === "done" || job.data?.status === "failed";
  useEffect(() => {
    if (finished) void client.invalidateQueries({ queryKey: keys.sources });
  }, [finished, client]);
  if (jobId && job.isError) return <span>✗ could not read the check</span>;
  if (jobId && !finished) return <span role="status">checking…</span>;
  if (job.data?.status === "failed") return <span>✗ the check could not run: {job.data.error ?? "no details"}</span>;
  const result = (job.data?.progress as { result?: SourceCheckResult } | undefined)?.result;
  if (result) return <span>{result.ok ? `✓ OK${seconds(result.ms)} · ${result.count} result` : `✗ failed: ${result.error ?? "no details"}${seconds(result.ms)}`}</span>;
  return <span>{lastCheck(source)}</span>;
}

type RowProps = { source: SourceOut; admin: boolean; jobId: string | null; onPatch: (body: { enabled?: boolean; max_results?: number }) => void; onCheck: () => void };

function SourceRow({ source, admin, jobId, onPatch, onCheck }: RowProps) {
  const label = sourceLabel(source.name);
  const [max, setMax] = useState(String(source.max_results));
  const [problem, setProblem] = useState<string | null>(null);
  const saveMax = (event: FormEvent) => {
    event.preventDefault();
    const value = Number(max);
    if (!Number.isInteger(value) || value < 1 || value > 200) return setProblem("Max results must be a whole number from 1 to 200.");
    setProblem(null);
    onPatch({ max_results: value });
  };
  const state = source.enabled ? "enabled" : "disabled";
  return (
    <tr>
      <th scope="row">{label}</th>
      <td>{COVERS[source.name] ?? "–"}</td>
      <td>
        {admin ? (
          <label className="check">
            <input type="checkbox" checked={source.enabled} onChange={(e) => onPatch({ enabled: e.target.checked })} /> {state}
            <span className="sr-only"> ({label})</span>
          </label>
        ) : state}
      </td>
      <td>
        {admin ? (
          <form className="inline" onSubmit={saveMax} noValidate>
            <label><span className="sr-only">Max results per run for {label}</span>
              <input type="number" min={1} max={200} value={max} onChange={(e) => setMax(e.target.value)} />
            </label>
            <button type="submit">Save<span className="sr-only"> max results for {label}</span></button>
            {problem && <span role="alert" className="form-error">{problem}</span>}
          </form>
        ) : source.max_results}
      </td>
      <td><CheckStatus source={source} jobId={jobId} /></td>
      <td>{admin && <button type="button" onClick={onCheck}>Test<span className="sr-only"> {label}</span></button>}</td>
    </tr>
  );
}

function ContactForm({ admin, value }: { admin: boolean; value: string | null }) {
  const patch = usePatchSettings();
  const [email, setEmail] = useState(value ?? "");
  const [message, setMessage] = useState<string | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  if (!admin) return <p>Contact address for public APIs: {value ?? "not set"}</p>;
  const submit = async (event: FormEvent) => {
    event.preventDefault();
    const text = email.trim();
    setMessage(null);
    if (text && !/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(text)) return setProblem("Enter an email address, or leave it empty.");
    setProblem(null);
    try {
      await patch.mutateAsync({ contact_email: text || null });
      setMessage("Saved.");
    } catch (error) {
      setProblem(errorText(error));
    }
  };
  return (
    <form className="inline" onSubmit={submit} noValidate aria-label="Contact address">
      <label>Contact address for public APIs <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} /></label>
      <button type="submit" disabled={patch.isPending}>Save contact address</button>
      {message && <span role="status">{message}</span>}
      {problem && <span role="alert" className="form-error">{problem}</span>}
    </form>
  );
}

export function SourcesTab() {
  const { user } = useAuth();
  const admin = hasRole(user, "admin");
  const sources = useSources();
  const settings = useSettings();
  const patch = usePatchSource();
  const check = useCheckSource();
  const [jobs, setJobs] = useState<Record<string, string>>({});
  const [problem, setProblem] = useState<string | null>(null);
  const act = async (work: () => Promise<unknown>) => {
    setProblem(null);
    try {
      await work();
    } catch (error) {
      setProblem(errorText(error));
    }
  };

  if (sources.isLoading) return <p role="status">Loading…</p>;
  if (sources.isError) return <p role="alert" className="form-error">{errorText(sources.error)}</p>;
  return (
    <section aria-labelledby="sources-heading">
      <h2 id="sources-heading">Sources</h2>
      {problem && <p role="alert" className="form-error">{problem}</p>}
      <table className="runs">
        <thead>
          <tr><th scope="col">Source</th><th scope="col">Covers</th><th scope="col">Status</th><th scope="col">Max results per run</th><th scope="col">Last check</th><th scope="col"><span className="sr-only">Actions</span></th></tr>
        </thead>
        <tbody>
          {sources.data?.map((source) => (
            <SourceRow
              key={`${source.name}:${source.max_results}`} source={source} admin={admin} jobId={jobs[source.name] ?? null}
              onPatch={(body) => void act(() => patch.mutateAsync({ name: source.name, ...body }))}
              onCheck={() => void act(async () => {
                const job = await check.mutateAsync(source.name);
                setJobs((current) => ({ ...current, [source.name]: job.id }));
              })}
            />
          ))}
        </tbody>
      </table>
      <p className="legend">Test runs one real search for one result. No keys are needed; OpenAlex receives the contact address below, as it recommends. A field can only pick enabled sources.</p>
      {settings.isLoading ? <p role="status">Loading…</p> : settings.isError ? <p role="alert" className="form-error">{errorText(settings.error)}</p> : <ContactForm admin={admin} value={settings.data?.contact_email ?? null} />}
    </section>
  );
}
```

Append to `styles.css`:

```css
.check { display: inline-flex; gap: 6px; align-items: center; }
form.inline { display: inline-flex; gap: 6px; align-items: center; flex-wrap: wrap; }
form.inline input[type="number"] { width: 80px; }
table.runs th[scope="row"] { font-weight: 600; }
```

In `App.tsx` add `<Route path="sources" element={<SourcesTab />} />` and the index redirect.

- [ ] **Step 3:** Sources tests PASS; full check; **commit** "Web: Settings → Sources (enable, max results, connection test, contact address)".

---

### Task 4: Settings → AI models

**Files:** Create `web/src/features/settings/ModelsTab.tsx`; modify `web/src/pages/SettingsPage.test.tsx`, `web/src/App.tsx` (route `models`).

- [ ] **Step 1: Failing tests** (append to `SettingsPage.test.tsx`):

```tsx
describe("Settings → AI models", () => {
  it("shows each role's model and whether its key was accepted, in words", async () => {
    setup("viewer", "/settings/models");
    const table = await screen.findByRole("table");
    expect(within(table).getByRole("row", { name: /Screen/ })).toHaveTextContent("✓ accepted");
    expect(within(table).getByRole("row", { name: /Adjudicator/ })).toHaveTextContent("✗ rejected: rejected (401)");
    expect(within(table).getByRole("row", { name: /Jev/ })).toHaveTextContent("✗ missing");
    expect(screen.getByText(/Key values never leave the worker/)).toBeInTheDocument();
  });

  it("says so when no worker has reported", async () => {
    setup("admin", "/settings/models", { "GET /api/v1/workers/status": { body: [] } });
    expect(await screen.findByText(/No worker has reported yet/)).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Implement**

**File: `web/src/features/settings/ModelsTab.tsx`**

```tsx
import { ApiError } from "../../api/client";
import { useWorkers } from "../../api/hooks";
import type { WorkerStatusOut } from "../../api/types";

const ROLE_LABEL: Record<string, string> = {
  plan: "Plan", screen: "Screen", screen_criteria: "Screen (per criterion)", extract: "Extract",
  review_a: "Reviewer A", review_b: "Reviewer B", adjudicate: "Adjudicator", jev: "Jev",
};

function keyText(worker: WorkerStatusOut): string {
  const detail = worker.detail ? `: ${worker.detail}` : "";
  if (!worker.key_present) return `✗ missing${detail || ": no key in the worker"}`;
  if (worker.key_accepted === true) return "✓ accepted";
  if (worker.key_accepted === false) return `✗ rejected${detail}`;
  return `present, not checked${detail}`;
}

export function ModelsTab() {
  const workers = useWorkers();
  if (workers.isLoading) return <p role="status">Loading…</p>;
  if (workers.isError) return <p role="alert" className="form-error">{workers.error instanceof ApiError ? workers.error.message : "Could not reach the server."}</p>;
  const rows = workers.data ?? [];
  return (
    <section aria-labelledby="models-heading">
      <h2 id="models-heading">AI models</h2>
      {rows.length === 0 ? (
        <p>No worker has reported yet. A worker checks its keys when it starts.</p>
      ) : (
        <table className="runs">
          <thead><tr><th scope="col">Role</th><th scope="col">Model</th><th scope="col">Key in worker</th><th scope="col">Checked</th></tr></thead>
          <tbody>
            {rows.map((worker) => (
              <tr key={`${worker.worker_id}:${worker.role}`}>
                <th scope="row">{ROLE_LABEL[worker.role] ?? worker.role}</th>
                <td>{worker.provider ?? "–"}{worker.model ? ` · ${worker.model}` : ""}</td>
                <td>{keyText(worker)}</td>
                <td>{new Date(worker.checked_at).toLocaleString()}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <p className="legend">Reported by the worker at start-up: only whether a key is present and whether a test call accepted it. Key values never leave the worker. Models are changed in the worker's environment file, not here.</p>
    </section>
  );
}
```

- [ ] **Step 3:** PASS, full check, **commit** "Web: Settings → AI models (worker key status, never a key)".

---

### Task 5: Fields list

**Files:** Create `web/src/pages/FieldsPage.tsx`, `web/src/pages/FieldsPage.test.tsx`; modify `App.tsx` (route `/fields`), `styles.css`.

- [ ] **Step 1: Failing test**

**File: `web/src/pages/FieldsPage.test.tsx`**

```tsx
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { setCsrfToken } from "../api/client";
import { fieldDetail, FIELD_ID, legacyField, session } from "../test/fixtures";
import { mockApi } from "../test/mockApi";
import { renderWithProviders } from "../test/render";
import { FieldsPage } from "./FieldsPage";

afterEach(() => {
  vi.unstubAllGlobals();
  setCsrfToken(null);
});

const LEGACY_ID = "12121212-1212-4212-8212-121212121212";
const ARCHIVED = { ...fieldDetail({ id: "34343434-3434-4434-8434-343434343434", name: "Old field", archived_at: "2026-09-27T10:00:00Z" }) };

function setup(role: "viewer" | "member" = "member") {
  const api = mockApi({
    "GET /api/v1/auth/me": { body: session(role) },
    "GET /api/v1/fields": ({ url }) => ({
      body: url.searchParams.get("archived") === "true"
        ? [fieldDetail(), { ...legacyField(), id: LEGACY_ID, name: "Legacy topic" }, ARCHIVED]
        : [fieldDetail(), { ...legacyField(), id: LEGACY_ID, name: "Legacy topic" }],
    }),
  });
  renderWithProviders(<FieldsPage />);
  return api;
}

describe("FieldsPage", () => {
  it("lists fields with version, criteria, sources, last run and Start run", async () => {
    setup();
    const row = (await screen.findAllByRole("row")).find((r) => r.textContent?.includes("ML CT-FFR"))!;
    expect(row).toHaveTextContent("v2 · Mia Member");
    expect(row).toHaveTextContent("2 incl · 1 excl");
    expect(row).toHaveTextContent("Europe PMC");
    expect(row).toHaveTextContent("done · research · v2");
    expect(within(row).getByRole("link", { name: "Start run for ML CT-FFR" })).toHaveAttribute("href", `/runs?field=${FIELD_ID}`);
    expect(within(row).getByRole("link", { name: "ML CT-FFR" })).toHaveAttribute("href", `/fields/${FIELD_ID}`);
    expect(screen.getByRole("row", { name: /Legacy topic/ })).toHaveTextContent("topic match (legacy)");
    expect(screen.getByRole("link", { name: "New field" })).toHaveAttribute("href", "/fields/new");
  });

  it("shows archived fields on request, without Start run", async () => {
    const { calls } = setup();
    await screen.findByRole("table");
    expect(screen.queryByText("Old field")).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("checkbox", { name: "Show archived fields" }));
    const row = await screen.findByRole("row", { name: /Old field/ });
    expect(row).toHaveTextContent("archived");
    expect(within(row).queryByRole("link", { name: /Start run/ })).not.toBeInTheDocument();
    await waitFor(() => expect(calls.some((c) => c.search.includes("archived=true"))).toBe(true));
  });

  it("viewers read the list but cannot create fields or start runs", async () => {
    setup("viewer");
    await screen.findByRole("table");
    expect(screen.queryByRole("link", { name: "New field" })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /Start run/ })).not.toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Implement**

**File: `web/src/pages/FieldsPage.tsx`**

```tsx
import { useState } from "react";
import { Link } from "react-router-dom";

import { ApiError } from "../api/client";
import { useFields } from "../api/hooks";
import { hasRole, type FieldOut } from "../api/types";
import { useAuth } from "../auth/AuthProvider";
import { shortDate, sourceLabel } from "../features/fields/labels";

const criteriaText = (field: FieldOut) => {
  const current = field.current;
  if (!current || current.include.length + current.exclude.length === 0) return "topic match (legacy)";
  return `${current.include.length} incl · ${current.exclude.length} excl`;
};

const versionText = (field: FieldOut) => {
  const current = field.current;
  if (!current) return `v${field.current_version ?? 1}`;
  return `v${current.version} · ${current.imported ? "imported" : (current.created_by_name ?? "unknown author")} · ${shortDate(current.created_at)}`;
};

const lastRunText = (field: FieldOut) => {
  const run = field.last_run;
  if (!run) return "none yet";
  return `${run.status} · ${run.kind}${run.field_version ? ` · v${run.field_version}` : ""} · ${shortDate(run.created_at)}`;
};

export function FieldsPage() {
  const { user } = useAuth();
  const [archived, setArchived] = useState(false);
  const fields = useFields({ archived });
  const canEdit = hasRole(user, "member");
  const rows = fields.data ?? [];
  return (
    <section>
      <div className="page-head">
        <h1>Fields</h1>
        {canEdit && <Link className="button-link" to="/fields/new">New field</Link>}
      </div>
      <label className="check"><input type="checkbox" checked={archived} onChange={(e) => setArchived(e.target.checked)} /> Show archived fields</label>
      {fields.isLoading ? (
        <p role="status">Loading…</p>
      ) : fields.isError ? (
        <p role="alert" className="form-error">{fields.error instanceof ApiError ? fields.error.message : "Could not load the fields."}</p>
      ) : rows.length === 0 ? (
        <p>No fields yet.</p>
      ) : (
        <table className="runs">
          <thead>
            <tr><th scope="col">Field</th><th scope="col">Version</th><th scope="col">Criteria</th><th scope="col">Sources</th><th scope="col">Last run</th><th scope="col"><span className="sr-only">Actions</span></th></tr>
          </thead>
          <tbody>
            {rows.map((field) => (
              <tr key={field.id}>
                <td><Link to={`/fields/${field.id}`}>{field.name}</Link><span className="sub">{field.topic}</span></td>
                <td>{versionText(field)}</td>
                <td>{criteriaText(field)}</td>
                <td>{field.current?.sources.map(sourceLabel).join(", ") || "–"}</td>
                <td>{lastRunText(field)}</td>
                <td>
                  {field.archived_at ? <span className="pill">archived</span>
                    : canEdit ? <Link to={`/runs?field=${field.id}`}>Start run<span className="sr-only"> for {field.name}</span></Link> : null}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}
```

Append to `styles.css`:

```css
.page-head { display: flex; gap: 12px; align-items: center; justify-content: space-between; }
.button-link { padding: 4px 10px; border: 1px solid var(--accent); border-radius: 6px; color: var(--accent); text-decoration: none; font-weight: 600; }
```

- [ ] **Step 3:** PASS, full check, **commit** "Web: Fields list (versions, criteria, sources, last run, show archived, Start run)".

---

### Task 6: Field form logic and version diff (pure modules)

**Files:** Create `web/src/features/fields/{fieldForm.ts,fieldForm.test.ts,versionDiff.ts,versionDiff.test.ts}`.

- [ ] **Step 1: Failing tests**

**File: `web/src/features/fields/fieldForm.test.ts`**

```ts
import { describe, expect, it } from "vitest";

import { legacyVersion, versionOut } from "../../test/fixtures";
import { emptyForm, formFromVersion, moveItem, toBody, validate, type FieldForm } from "./fieldForm";

const good = (): FieldForm => ({ ...emptyForm(["europepmc"]), name: "Plaque", topic: "AI plaque on CCTA", include: ["Uses deep learning."] });

describe("field form", () => {
  it("accepts a complete form", () => {
    expect(validate(good())).toEqual([]);
  });

  it("lists every problem in form order", () => {
    expect(validate({ ...emptyForm([]), include: ["ok", " "], exclude: [""] })).toEqual([
      "Give the field a name.", "Describe the topic.", "Inclusion criterion 2 is empty.", "Exclusion criterion 1 is empty.", "Choose at least one source.",
    ]);
  });

  it("needs at least one criterion", () => {
    expect(validate({ ...good(), include: [] })).toEqual(["Add at least one inclusion or exclusion criterion."]);
  });

  it("checks the years", () => {
    expect(validate({ ...good(), yearFrom: "18" })).toEqual(["Years must be four-digit years between 1900 and 2100."]);
    expect(validate({ ...good(), yearFrom: "2022", yearTo: "2019" })).toEqual(["The first year is after the last year."]);
    expect(validate({ ...good(), yearFrom: "2018" })).toEqual([]);
  });

  it("builds the request body with trimmed texts and numeric years", () => {
    expect(toBody({ ...good(), exclude: [" A review. "], yearFrom: "2018", note: " first " })).toEqual({
      name: "Plaque", topic: "AI plaque on CCTA", include: [{ text: "Uses deep learning." }], exclude: [{ text: "A review." }],
      sources: ["europepmc"], years: { from: 2018, to: null }, note: "first",
    });
  });

  it("loads a saved version; a legacy version has nothing to edit", () => {
    expect(formFromVersion(versionOut())).toEqual({
      name: "ML CT-FFR", topic: "deep learning CT-FFR",
      include: ["The study uses machine learning or deep learning.", "FFR is estimated from coronary CT angiography."],
      exclude: ["The paper is a review or an editorial."], sources: ["europepmc"], yearFrom: "2018", yearTo: "", note: "",
    });
    expect(formFromVersion(legacyVersion())).toMatchObject({ include: [], exclude: [], yearFrom: "", yearTo: "" });
  });

  it("moves an item and ignores moves past either end", () => {
    expect(moveItem(["a", "b", "c"], 2, -1)).toEqual(["a", "c", "b"]);
    expect(moveItem(["a", "b"], 0, -1)).toEqual(["a", "b"]);
    expect(moveItem(["a", "b"], 1, 1)).toEqual(["a", "b"]);
  });
});
```

**File: `web/src/features/fields/versionDiff.test.ts`**

```ts
import { describe, expect, it } from "vitest";

import { legacyVersion, versionOut } from "../../test/fixtures";
import { diffVersions, hasChanges } from "./versionDiff";

describe("version diff", () => {
  it("says, section by section, what was added and removed", () => {
    const sections = diffVersions(legacyVersion(), versionOut());
    const find = (title: string) => sections.find((s) => s.title === title)?.lines;
    expect(find("Name")).toEqual([{ change: "unchanged", text: "ML CT-FFR" }]);
    expect(find("Inclusion criteria")).toEqual([
      { change: "added", text: "The study uses machine learning or deep learning." },
      { change: "added", text: "FFR is estimated from coronary CT angiography." },
    ]);
    expect(find("Legacy topic match")).toEqual([{ change: "removed", text: "The paper's central subject is the topic." }]);
    expect(find("Sources")).toEqual([{ change: "unchanged", text: "Europe PMC" }]);
    expect(find("Years")).toEqual([{ change: "removed", text: "any year – now" }, { change: "added", text: "2018 – now" }]);
    expect(hasChanges(sections)).toBe(true);
  });

  it("finds nothing between a version and itself, and a reworded criterion is removed plus added", () => {
    expect(hasChanges(diffVersions(versionOut(), versionOut()))).toBe(false);
    const reworded = versionOut({ exclude: [{ key: "e1", text: "The paper is a review." }] });
    expect(diffVersions(versionOut(), reworded).find((s) => s.title === "Exclusion criteria")?.lines).toEqual([
      { change: "removed", text: "The paper is a review or an editorial." },
      { change: "added", text: "The paper is a review." },
    ]);
  });
});
```

- [ ] **Step 2: Implement**

**File: `web/src/features/fields/fieldForm.ts`**

```ts
import type { FieldBody } from "../../api/hooks";
import type { FieldDraft, FieldVersionOut } from "../../api/types";
import { isSourceName } from "./labels";

/** What the editor holds: everything as typed, so validation can name each problem. */
export type FieldForm = {
  name: string; topic: string; include: string[]; exclude: string[]; sources: string[]; yearFrom: string; yearTo: string; note: string;
};

export const emptyForm = (sources: string[]): FieldForm => ({ name: "", topic: "", include: [], exclude: [], sources, yearFrom: "", yearTo: "", note: "" });

/** Legacy criteria (topic_match) are not editable: a legacy version loads with empty lists. */
export const formFromVersion = (version: FieldVersionOut): FieldForm => ({
  name: version.name,
  topic: version.topic,
  include: version.include.map((c) => c.text),
  exclude: version.exclude.map((c) => c.text),
  sources: [...version.sources],
  yearFrom: version.years.from == null ? "" : String(version.years.from),
  yearTo: version.years.to == null ? "" : String(version.years.to),
  note: "",
});

const YEAR = /^\d{4}$/;
const year = (text: string) => (text.trim() === "" ? null : Number(text.trim()));

/** Every problem in form order; empty when the form can be saved or tested. */
export function validate(form: FieldForm): string[] {
  const problems: string[] = [];
  if (!form.name.trim()) problems.push("Give the field a name.");
  if (!form.topic.trim()) problems.push("Describe the topic.");
  form.include.forEach((text, i) => {
    if (!text.trim()) problems.push(`Inclusion criterion ${i + 1} is empty.`);
  });
  form.exclude.forEach((text, i) => {
    if (!text.trim()) problems.push(`Exclusion criterion ${i + 1} is empty.`);
  });
  if (form.include.length + form.exclude.length === 0) problems.push("Add at least one inclusion or exclusion criterion.");
  if (!form.sources.some(isSourceName)) problems.push("Choose at least one source.");
  const years = [form.yearFrom, form.yearTo].map((text) => text.trim()).filter(Boolean);
  if (years.some((text) => !YEAR.test(text) || Number(text) < 1900 || Number(text) > 2100)) {
    problems.push("Years must be four-digit years between 1900 and 2100.");
  } else {
    const from = year(form.yearFrom);
    const to = year(form.yearTo);
    if (from !== null && to !== null && from > to) problems.push("The first year is after the last year.");
  }
  return problems;
}

export const toDraft = (form: FieldForm): FieldDraft => ({
  name: form.name.trim(),
  topic: form.topic.trim(),
  include: form.include.map((text) => ({ text: text.trim() })),
  exclude: form.exclude.map((text) => ({ text: text.trim() })),
  sources: form.sources.filter(isSourceName),
  years: { from: year(form.yearFrom), to: year(form.yearTo) },
});

export const toBody = (form: FieldForm): FieldBody => ({ ...toDraft(form), note: form.note.trim() });

export function moveItem<T>(items: T[], index: number, delta: number): T[] {
  const target = index + delta;
  if (index < 0 || index >= items.length || target < 0 || target >= items.length) return items;
  const next = [...items];
  const [item] = next.splice(index, 1);
  next.splice(target, 0, item as T);
  return next;
}
```

**File: `web/src/features/fields/versionDiff.ts`**

```ts
import type { FieldVersionOut } from "../../api/types";
import { sourceLabel } from "./labels";

export type DiffLine = { change: "added" | "removed" | "unchanged"; text: string };
export type DiffSection = { title: string; lines: DiffLine[] };

function listDiff(before: string[], after: string[]): DiffLine[] {
  const kept: DiffLine[] = before.map((text) => ({ change: after.includes(text) ? "unchanged" : "removed", text }));
  const added: DiffLine[] = after.filter((text) => !before.includes(text)).map((text) => ({ change: "added", text }));
  return [...kept, ...added];
}

const years = (v: FieldVersionOut) => `${v.years.from ?? "any year"} – ${v.years.to ?? "now"}`;
const texts = (items: { text: string }[]) => items.map((c) => c.text);

/** What changed from `before` to `after`, per section. A reworded criterion shows as removed plus added. */
export function diffVersions(before: FieldVersionOut, after: FieldVersionOut): DiffSection[] {
  const sections: DiffSection[] = [
    { title: "Name", lines: listDiff([before.name], [after.name]) },
    { title: "Topic", lines: listDiff([before.topic], [after.topic]) },
    { title: "Inclusion criteria", lines: listDiff(texts(before.include), texts(after.include)) },
    { title: "Exclusion criteria", lines: listDiff(texts(before.exclude), texts(after.exclude)) },
    { title: "Legacy topic match", lines: listDiff(texts(before.legacy), texts(after.legacy)) },
    { title: "Sources", lines: listDiff(before.sources.map(sourceLabel), after.sources.map(sourceLabel)) },
    { title: "Years", lines: listDiff([years(before)], [years(after)]) },
  ];
  return sections.filter((section) => section.lines.length > 0);
}

export const hasChanges = (sections: DiffSection[]) => sections.some((s) => s.lines.some((line) => line.change !== "unchanged"));
```

- [ ] **Step 3:** PASS, full check, **commit** "Web: field form validation, request bodies and version diff".

---

### Task 7: Field editor (lists, sources, years, save as vN+1, 409 reload, archive, history panel)

**Files:** Create `web/src/features/fields/CriteriaList.tsx`, `web/src/features/fields/FieldSidePanel.tsx`, `web/src/pages/FieldEditorPage.tsx`, `web/src/pages/FieldEditorPage.test.tsx`; modify `App.tsx` (field routes), `styles.css`.

- [ ] **Step 1: Failing test**

**File: `web/src/pages/FieldEditorPage.test.tsx`**

```tsx
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import { setCsrfToken } from "../api/client";
import { evalSummary, fieldDetail, FIELD_ID, legacyField, legacyVersion, RUN_ID, runOut, session, sourceRows, versionOut } from "../test/fixtures";
import { mockApi } from "../test/mockApi";
import { renderWithProviders } from "../test/render";
import { FieldEditorPage } from "./FieldEditorPage";

afterEach(() => {
  vi.unstubAllGlobals();
  setCsrfToken(null);
});

function setup(role: "viewer" | "member" | "admin" = "member", extra: Parameters<typeof mockApi>[0] = {}, route = `/fields/${FIELD_ID}`) {
  const api = mockApi({
    "GET /api/v1/auth/me": { body: session(role) },
    "GET /api/v1/fields/:id": { body: fieldDetail() },
    "GET /api/v1/sources": { body: sourceRows() },
    "GET /api/v1/runs": { body: [] },
    "GET /api/v1/evals": { body: [] },
    "GET /api/v1/fields/:id/versions/1": { body: legacyVersion() },
    "GET /api/v1/fields/:id/versions/2": { body: versionOut() },
    ...extra,
  });
  renderWithProviders(
    <Routes>
      <Route path="/fields/new" element={<FieldEditorPage />} />
      <Route path="/fields/:fieldId" element={<FieldEditorPage />} />
    </Routes>,
    { route },
  );
  return api;
}

const form = () => screen.findByRole("form", { name: "Field editor" });

describe("FieldEditorPage", () => {
  it("loads the current version into the form", async () => {
    setup();
    expect(await screen.findByRole("heading", { name: "ML CT-FFR (v2)" })).toBeInTheDocument();
    expect(screen.getByLabelText("Name")).toHaveValue("ML CT-FFR");
    expect(screen.getByLabelText("incl 1")).toHaveValue("The study uses machine learning or deep learning.");
    expect(screen.getByLabelText("excl 1")).toHaveValue("The paper is a review or an editorial.");
    expect(screen.getByLabelText("From year")).toHaveValue("2018");
    expect(screen.getByRole("button", { name: "Save as v3" })).toBeInTheDocument();
  });

  it("adds, reorders and removes criteria", async () => {
    setup();
    await form();
    await userEvent.click(screen.getByRole("button", { name: "Add inclusion criterion" }));
    await userEvent.type(screen.getByLabelText("incl 3"), "Results are compared with invasive FFR.");
    await userEvent.click(screen.getByRole("button", { name: "Move incl 3 up" }));
    expect(screen.getByLabelText("incl 2")).toHaveValue("Results are compared with invasive FFR.");
    expect(screen.getByRole("button", { name: "Move incl 1 up" })).toBeDisabled();
    await userEvent.click(screen.getByRole("button", { name: "Remove incl 1" }));
    expect(screen.getByLabelText("incl 1")).toHaveValue("Results are compared with invasive FFR.");
    expect(screen.queryByLabelText("incl 3")).not.toBeInTheDocument();
  });

  it("validates before saving and does not call the server", async () => {
    const { calls } = setup();
    await form();
    await userEvent.clear(screen.getByLabelText("Name"));
    await userEvent.click(screen.getByRole("button", { name: "Save as v3" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Give the field a name.");
    expect(calls.some((c) => c.method === "POST")).toBe(false);
  });

  it("saves the next version against the version it opened", async () => {
    const saved = fieldDetail({ current_version: 3, current: versionOut({ version: 3, note: "tightened" }) });
    const { calls } = setup("member", { "POST /api/v1/fields/:id/versions": { status: 201, body: saved } });
    await form();
    await userEvent.type(screen.getByLabelText("Change note"), "tightened");
    await userEvent.click(screen.getByRole("button", { name: "Save as v3" }));
    expect(await screen.findByRole("heading", { name: "ML CT-FFR (v3)" })).toBeInTheDocument();
    const post = calls.find((c) => c.method === "POST")!;
    expect(post.body).toMatchObject({ base_version: 2, note: "tightened", sources: ["europepmc"], years: { from: 2018, to: null } });
    expect((post.body as { include: unknown[] }).include).toHaveLength(2);
  });

  it("a stale save offers to reload the latest version", async () => {
    let loads = 0;
    setup("member", {
      "GET /api/v1/fields/:id": () => ({ body: ++loads === 1 ? fieldDetail() : fieldDetail({ current_version: 3, current: versionOut({ version: 3 }) }) }),
      "POST /api/v1/fields/:id/versions": { status: 409, body: { code: "stale_version", message: "This field changed since you opened it (now v3)", request_id: "r" } },
    });
    await form();
    await userEvent.click(screen.getByRole("button", { name: "Save as v3" }));
    expect(await screen.findByText("This field changed since you opened it (now v3)")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Reload the latest version" }));
    expect(await screen.findByRole("heading", { name: "ML CT-FFR (v3)" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Save as v4" })).toBeInTheDocument();
  });

  it("creates a new field and opens it", async () => {
    const { calls } = setup("member", { "POST /api/v1/fields": { status: 201, body: fieldDetail({ current_version: 1, current: versionOut({ version: 1 }) }) } }, "/fields/new");
    expect(await screen.findByRole("heading", { name: "New field" })).toBeInTheDocument();
    await userEvent.type(screen.getByLabelText("Name"), "ML CT-FFR");
    await userEvent.type(screen.getByLabelText(/^Topic/), "deep learning CT-FFR");
    await userEvent.click(screen.getByRole("button", { name: "Add inclusion criterion" }));
    await userEvent.type(screen.getByLabelText("incl 1"), "Uses deep learning.");
    await userEvent.click(screen.getByRole("button", { name: "Create field" }));
    expect(await screen.findByRole("heading", { name: "ML CT-FFR (v1)" })).toBeInTheDocument();
    expect(calls.find((c) => c.method === "POST")?.body).toMatchObject({ name: "ML CT-FFR", include: [{ text: "Uses deep learning." }], sources: ["europepmc"] });
    expect(screen.getByText(/Save the field first/)).toBeInTheDocument();
  });

  it("offers only enabled sources", async () => {
    setup();
    await form();
    expect(screen.getByRole("checkbox", { name: "Europe PMC" })).toBeChecked();
    expect(screen.getByRole("checkbox", { name: "OpenAlex (disabled in Settings)" })).toBeDisabled();
  });

  it("is read-only for viewers", async () => {
    setup("viewer");
    await form();
    expect(screen.getByLabelText("Name")).toBeDisabled();
    expect(screen.queryByRole("button", { name: /Save as/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Archive" })).not.toBeInTheDocument();
  });

  it("admins archive a field, which makes it read-only", async () => {
    const { calls } = setup("admin", { "POST /api/v1/fields/:id/archive": { body: fieldDetail({ archived_at: "2026-09-29T10:00:00Z" }) } });
    await form();
    await userEvent.click(screen.getByRole("button", { name: "Archive" }));
    expect(await screen.findByRole("button", { name: "Restore" })).toBeInTheDocument();
    expect(screen.getByText(/This field is archived/)).toBeInTheDocument();
    expect(screen.getByLabelText("Name")).toBeDisabled();
    expect(calls.some((c) => c.method === "POST" && c.path.endsWith("/archive"))).toBe(true);
  });

  it("a legacy field explains how to add criteria", async () => {
    setup("member", { "GET /api/v1/fields/:id": { body: legacyField() } });
    expect(await screen.findByText(/legacy topic match/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Save as v2" })).toBeInTheDocument();
  });

  it("the history lists versions with notes and runs, and says the screen is not measured", async () => {
    setup();
    const panel = await screen.findByRole("complementary", { name: "Field history" });
    expect(within(panel).getByText(/not measured/)).toBeInTheDocument();
    expect(within(panel).getByText("added the exclusion")).toBeInTheDocument();
    expect(within(panel).getByText(/3 runs/)).toBeInTheDocument();
    expect(await within(panel).findByText("The study uses machine learning or deep learning.")).toBeInTheDocument();
    expect(within(panel).getAllByText("added").length).toBeGreaterThan(0);
    expect(within(panel).getAllByText("removed").length).toBeGreaterThan(0);
  });

  it("says the screen is measured when an eval ran on this version", async () => {
    setup("member", {
      "GET /api/v1/runs": { body: [runOut({ id: RUN_ID, field_id: FIELD_ID, field_version: 2 })] },
      "GET /api/v1/evals": { body: [evalSummary()] },
    });
    const panel = await screen.findByRole("complementary", { name: "Field history" });
    await waitFor(() => expect(panel).toHaveTextContent("measured against mlffrct-2024"));
  });
});
```

- [ ] **Step 2: Implement**

**File: `web/src/features/fields/CriteriaList.tsx`**

```tsx
import { moveItem } from "./fieldForm";

type Props = { kind: "include" | "exclude"; items: string[]; onChange: (items: string[]) => void };

const TEXT = {
  include: { legend: "Inclusion criteria: a paper must meet all of them", prefix: "incl", noun: "inclusion" },
  exclude: { legend: "Exclusion criteria: any one of them drops the paper", prefix: "excl", noun: "exclusion" },
};

/** One ordered list of criteria. Keys follow the position (i1, i2… on save), so the labels do too. */
export function CriteriaList({ kind, items, onChange }: Props) {
  const { legend, prefix, noun } = TEXT[kind];
  const set = (index: number, text: string) => onChange(items.map((item, i) => (i === index ? text : item)));
  return (
    <fieldset className="criteria">
      <legend>{legend}</legend>
      {items.length === 0 && <p className="sub">None yet.</p>}
      <ol>
        {items.map((text, index) => {
          const name = `${prefix} ${index + 1}`;
          return (
            <li key={index}>
              <label>{name}<input value={text} onChange={(e) => set(index, e.target.value)} /></label>
              <button type="button" aria-label={`Move ${name} up`} disabled={index === 0} onClick={() => onChange(moveItem(items, index, -1))}>↑</button>
              <button type="button" aria-label={`Move ${name} down`} disabled={index === items.length - 1} onClick={() => onChange(moveItem(items, index, 1))}>↓</button>
              <button type="button" aria-label={`Remove ${name}`} onClick={() => onChange(items.filter((_, i) => i !== index))}>Remove</button>
            </li>
          );
        })}
      </ol>
      <button type="button" onClick={() => onChange([...items, ""])}>Add {noun} criterion</button>
    </fieldset>
  );
}
```

**File: `web/src/features/fields/FieldSidePanel.tsx`**

```tsx
import { useState } from "react";

import { useEvals, useFieldVersion, useRuns } from "../../api/hooks";
import type { FieldOut } from "../../api/types";
import { shortDate } from "./labels";
import { diffVersions, hasChanges } from "./versionDiff";

const runCount = (n: number) => (n === 1 ? "1 run" : `${n} runs`);

/** Measured only when an eval exists for a run of this field at its current version. */
function Measurement({ field }: { field: FieldOut }) {
  const runs = useRuns();
  const evals = useEvals();
  const current = field.current_version ?? 1;
  if (runs.isLoading || evals.isLoading) return <p className="sub">Checking measurements…</p>;
  const runIds = new Set((runs.data ?? []).filter((r) => r.field_id === field.id && (r.field_version ?? 1) === current).map((r) => r.id));
  const golds = [...new Set((evals.data ?? []).filter((e) => runIds.has(e.run_id)).map((e) => e.gold_set.name))];
  if (golds.length > 0) return <p className="banner">Screening for this field (v{current}): measured against {golds.join(", ")}.</p>;
  return <p className="banner banner--warn">Screening for this field (v{current}): not measured. No eval against a published review has used this version yet.</p>;
}

function VersionDiff({ fieldId, versions }: { fieldId: string; versions: number[] }) {
  const [from, setFrom] = useState(versions[1] ?? versions[0] ?? 1);
  const [to, setTo] = useState(versions[0] ?? 1);
  const before = useFieldVersion(fieldId, from);
  const after = useFieldVersion(fieldId, to);
  const sections = before.data && after.data ? diffVersions(before.data, after.data) : null;
  const options = versions.map((v) => <option key={v} value={v}>v{v}</option>);
  return (
    <div className="diff">
      <h3>Compare versions</h3>
      <div className="actions">
        <label>Compare from <select value={from} onChange={(e) => setFrom(Number(e.target.value))}>{options}</select></label>
        <label>to <select value={to} onChange={(e) => setTo(Number(e.target.value))}>{options}</select></label>
      </div>
      {before.isError || after.isError ? (
        <p role="alert" className="form-error">Could not load a version.</p>
      ) : !sections ? (
        <p className="sub">Loading…</p>
      ) : !hasChanges(sections) ? (
        <p>No differences.</p>
      ) : (
        sections.filter((s) => s.lines.some((line) => line.change !== "unchanged")).map((section) => (
          <div key={section.title}>
            <h4>{section.title}</h4>
            <ul className="diff-lines">
              {section.lines.map((line, i) => (
                <li key={i}><span className={`diff-tag diff-tag--${line.change}`}>{line.change}</span> {line.text}</li>
              ))}
            </ul>
          </div>
        ))
      )}
    </div>
  );
}

export function FieldSidePanel({ field }: { field: FieldOut }) {
  const versions = field.versions ?? [];
  return (
    <aside aria-label="Field history" className="side-panel">
      <h2>History</h2>
      <Measurement field={field} />
      <ol className="versions">
        {versions.map((v) => (
          <li key={v.version}>
            <strong>v{v.version}</strong> · {v.imported ? "imported" : (v.created_by_name ?? "unknown author")} · {shortDate(v.created_at)}
            <span className="sub">{v.note || "No change note."}</span>
            <span className="sub">{v.include_count + v.exclude_count === 0 ? "topic match" : `${v.include_count} incl · ${v.exclude_count} excl`} · {runCount(v.run_count)}</span>
          </li>
        ))}
      </ol>
      {versions.length > 1 && <VersionDiff fieldId={field.id} versions={versions.map((v) => v.version)} />}
    </aside>
  );
}
```

**File: `web/src/pages/FieldEditorPage.tsx`** (Task 8 adds the test panel lines marked there)

```tsx
import { useState, type FormEvent } from "react";
import { useNavigate, useParams } from "react-router-dom";

import { ApiError } from "../api/client";
import { useArchiveField, useField, useSaveField, useSources, useTestCriteria } from "../api/hooks";
import { hasRole, type FieldOut, type SourceOut } from "../api/types";
import { useAuth } from "../auth/AuthProvider";
import { CriteriaList } from "../features/fields/CriteriaList";
import { CriteriaTestPanel } from "../features/fields/CriteriaTestPanel";
import { FieldSidePanel } from "../features/fields/FieldSidePanel";
import { emptyForm, formFromVersion, toBody, toDraft, validate, type FieldForm } from "../features/fields/fieldForm";
import { SOURCE_NAMES, sourceLabel } from "../features/fields/labels";

const errorText = (error: unknown) => (error instanceof ApiError ? error.message : "Could not reach the server.");

export function FieldEditorPage() {
  const { fieldId } = useParams();
  const field = useField(fieldId ?? null);
  const sources = useSources();
  if ((fieldId && field.isLoading) || sources.isLoading) return <p role="status">Loading…</p>;
  if (field.isError) return <p role="alert" className="form-error">{errorText(field.error)}</p>;
  if (sources.isError) return <p role="alert" className="form-error">{errorText(sources.error)}</p>;
  const data = fieldId ? (field.data ?? null) : null;
  // Keyed by version: a save or a reload puts the editor back on the saved text.
  return <FieldEditor key={data ? `${data.id}:${data.current_version}` : "new"} field={data} sources={sources.data ?? []} onReload={() => void field.refetch()} />;
}

function FieldEditor({ field, sources, onReload }: { field: FieldOut | null; sources: SourceOut[]; onReload: () => void }) {
  const { user } = useAuth();
  const navigate = useNavigate();
  const save = useSaveField();
  const archive = useArchiveField();
  const test = useTestCriteria();
  const current = field?.current ?? null;
  const archived = !!field?.archived_at;
  const member = hasRole(user, "member");
  const admin = hasRole(user, "admin");
  const canEdit = member && !archived;
  const enabled = new Set(sources.filter((s) => s.enabled).map((s) => s.name));
  const [form, setForm] = useState<FieldForm>(() => (current ? formFromVersion(current) : emptyForm([...enabled])));
  const [errors, setErrors] = useState<string[]>([]);
  const [problem, setProblem] = useState<string | null>(null);
  const [stale, setStale] = useState<string | null>(null);
  const [testJob, setTestJob] = useState<string | null>(null);
  const [demo, setDemo] = useState(false);
  const update = (patch: Partial<FieldForm>) => setForm((f) => ({ ...f, ...patch }));
  const legacy = !!current && current.include.length + current.exclude.length === 0 && current.legacy.length > 0;
  const nextVersion = (field?.current_version ?? 0) + 1;

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    const found = validate(form);
    setErrors(found);
    if (found.length > 0) return;
    setProblem(null);
    setStale(null);
    try {
      const saved = await save.mutateAsync({ fieldId: field?.id ?? null, baseVersion: field?.current_version ?? null, body: toBody(form) });
      if (!field) navigate(`/fields/${saved.id}`, { replace: true });
    } catch (error) {
      if (error instanceof ApiError && error.code === "stale_version") setStale(error.message);
      else setProblem(errorText(error));
    }
  };

  const runTest = async () => {
    const found = validate(form);
    setErrors(found);
    if (found.length > 0 || !field) return;
    setProblem(null);
    try {
      const job = await test.mutateAsync({ fieldId: field.id, draft: toDraft(form), mode: demo ? "demo" : "live" });
      setTestJob(job.id);
    } catch (error) {
      setProblem(errorText(error));
    }
  };

  const toggleArchive = async () => {
    if (!field) return;
    setProblem(null);
    try {
      await archive.mutateAsync({ fieldId: field.id, archive: !archived });
    } catch (error) {
      setProblem(errorText(error));
    }
  };

  const toggleSource = (name: string, on: boolean) =>
    update({ sources: on ? [...form.sources, name] : form.sources.filter((s) => s !== name) });

  return (
    <section>
      <div className="page-head">
        <h1>{field ? `${field.name} (v${field.current_version ?? 1})` : "New field"}</h1>
        {admin && field && <button type="button" onClick={toggleArchive} disabled={archive.isPending}>{archived ? "Restore" : "Archive"}</button>}
      </div>
      {archived && <p className="banner banner--warn">This field is archived: it cannot be edited, tested or run. {admin ? "Restore it to change it." : "An admin can restore it."}</p>}
      <div className={field ? "editor-layout" : undefined}>
        <div>
          <form onSubmit={submit} aria-label="Field editor" className="field-form" noValidate>
            <fieldset className="plain" disabled={!canEdit}>
              <label className="block">Name<input value={form.name} onChange={(e) => update({ name: e.target.value })} /></label>
              <label className="block">Topic (used for the search and as context for screening)<input value={form.topic} onChange={(e) => update({ topic: e.target.value })} /></label>
              {legacy && current && (
                <p className="banner banner--warn">
                  This field uses the legacy topic match (“{current.legacy[0]?.text}”). Add inclusion or exclusion criteria to save v{nextVersion} with your own criteria.
                </p>
              )}
              <CriteriaList kind="include" items={form.include} onChange={(include) => update({ include })} />
              <CriteriaList kind="exclude" items={form.exclude} onChange={(exclude) => update({ exclude })} />
              <fieldset>
                <legend>Sources</legend>
                {SOURCE_NAMES.map((name) => {
                  const on = enabled.has(name);
                  const checked = form.sources.includes(name);
                  return (
                    <label key={name} className="check source-choice">
                      <input type="checkbox" checked={checked} disabled={!on && !checked} onChange={(e) => toggleSource(name, e.target.checked)} />
                      {sourceLabel(name)}{on ? "" : " (disabled in Settings)"}
                    </label>
                  );
                })}
              </fieldset>
              <fieldset>
                <legend>Years</legend>
                <div className="actions">
                  <label>From year <input inputMode="numeric" value={form.yearFrom} onChange={(e) => update({ yearFrom: e.target.value })} /></label>
                  <label>To year <input inputMode="numeric" value={form.yearTo} onChange={(e) => update({ yearTo: e.target.value })} /></label>
                  <span className="sub">Leave empty for no limit.</span>
                </div>
              </fieldset>
              <label className="block">Change note<input value={form.note} onChange={(e) => update({ note: e.target.value })} /></label>
            </fieldset>
            {errors.length > 0 && (
              <div role="alert" className="form-error"><p>Fix these first:</p><ul>{errors.map((e) => <li key={e}>{e}</li>)}</ul></div>
            )}
            {stale && (
              <div role="alert" className="banner banner--warn">
                <p>{stale}</p>
                <button type="button" onClick={onReload}>Reload the latest version</button> <span className="sub">Reloading discards your unsaved edits.</span>
              </div>
            )}
            {problem && <p role="alert" className="form-error">{problem}</p>}
            {canEdit && (
              <div className="actions">
                <button type="submit" disabled={save.isPending}>{field ? `Save as v${nextVersion}` : "Create field"}</button>
                {field ? (
                  <>
                    <button type="button" onClick={runTest} disabled={test.isPending}>Test criteria</button>
                    <label className="check"><input type="checkbox" checked={demo} onChange={(e) => setDemo(e.target.checked)} /> Demo mode (offline stand-in for Jev)</label>
                  </>
                ) : (
                  <span className="sub">Save the field first to test its criteria.</span>
                )}
              </div>
            )}
          </form>
          {testJob && <CriteriaTestPanel key={testJob} jobId={testJob} />}
        </div>
        {field && <FieldSidePanel field={field} />}
      </div>
    </section>
  );
}
```

Append to `styles.css`:

```css
.editor-layout { display: grid; gap: 16px; grid-template-columns: minmax(0, 1fr) 340px; align-items: start; }
@media (max-width: 900px) { .editor-layout { grid-template-columns: 1fr; } }
.field-form { display: grid; gap: 12px; max-width: 820px; }
fieldset { border: 1px solid var(--line); border-radius: 8px; padding: 8px 12px; margin: 0; }
fieldset.plain { border: 0; padding: 0; display: grid; gap: 12px; }
legend { font-weight: 600; padding: 0 4px; }
label.block { display: grid; gap: 4px; font-weight: 600; }
label.block input { font-weight: 400; }
.criteria ol { margin: 0 0 8px; padding: 0; list-style: none; display: grid; gap: 6px; }
.criteria li { display: flex; gap: 6px; align-items: center; }
.criteria li label { flex: 1; display: flex; gap: 8px; align-items: center; white-space: nowrap; }
.criteria li input { flex: 1; min-width: 0; }
.source-choice { margin-right: 16px; }
.actions { display: flex; gap: 12px; align-items: center; flex-wrap: wrap; }
.actions label { display: inline-flex; gap: 6px; align-items: center; }
.versions { padding: 0; list-style: none; display: grid; gap: 8px; }
.diff h4 { margin: 8px 0 2px; font-size: 12px; }
.diff-lines { margin: 0; padding-left: 0; list-style: none; }
.diff-tag { font-size: 11px; border: 1px solid var(--line); border-radius: 4px; padding: 0 4px; }
.diff-tag--added { background: var(--ok-bg); color: var(--ok-fg); border-color: var(--ok-line); }
.diff-tag--removed { background: var(--bad-bg); color: var(--bad-fg); border-color: var(--bad-line); }
```

`CriteriaTestPanel` is imported here; Task 8 creates it, so Task 7 creates a first version of `web/src/features/fields/CriteriaTestPanel.tsx` exactly as in Task 8 Step 2 (the task order below keeps the tests separate). In practice: implement Task 8's component file in this task too, and add its dedicated tests in Task 8.

- [ ] **Step 3:** PASS, full check, **commit** "Web: field editor (criteria lists, sources, years, save as vN+1, stale reload, archive, history and diff)".

---

### Task 8: Criteria test panel

**Files:** `web/src/features/fields/CriteriaTestPanel.tsx`, `web/src/features/fields/CriteriaTestPanel.test.tsx`; add an editor test to `FieldEditorPage.test.tsx`; `styles.css`.

- [ ] **Step 1: Failing tests**

**File: `web/src/features/fields/CriteriaTestPanel.test.tsx`**

```tsx
import { screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { setCsrfToken } from "../../api/client";
import { JOB_ID, jobOut, session, testResult } from "../../test/fixtures";
import { mockApi } from "../../test/mockApi";
import { renderWithProviders } from "../../test/render";
import { CriteriaTestPanel } from "./CriteriaTestPanel";

afterEach(() => {
  vi.unstubAllGlobals();
  setCsrfToken(null);
});

const job = (over: Parameters<typeof jobOut>[0]) => ({ body: jobOut({ kind: "criteria_test", run_id: null, ...over }) });

function setup(handler: Parameters<typeof mockApi>[0][string]) {
  mockApi({ "GET /api/v1/auth/me": { body: session("member") }, "GET /api/v1/jobs/:id": handler });
  renderWithProviders(<CriteriaTestPanel jobId={JOB_ID} />);
}

describe("CriteriaTestPanel", () => {
  it("shows progress while the worker tests papers", async () => {
    setup(job({ status: "running", progress: { status: "running", done: 3, total: 20 } }));
    expect(await screen.findByText("Testing: 3 of 20 papers")).toBeInTheDocument();
  });

  it("shows one row per paper, one column per criterion, and marks the deciding cell in words", async () => {
    setup(job({ status: "done", progress: { status: "done", result: testResult() } }));
    const table = await screen.findByRole("table");
    expect(within(table).getByRole("columnheader", { name: "incl 1" })).toBeInTheDocument();
    const dropped = within(table).getByRole("row", { name: /a review/ });
    expect(dropped).toHaveTextContent("0.96 decided");
    expect(dropped).toHaveTextContent("dropped · excl 1");
    expect(within(table).getByRole("row", { name: /against invasive FFR/ })).toHaveTextContent("kept");
    expect(within(table).getByRole("row", { name: /without an abstract/ })).toHaveTextContent("not screened");
    expect(screen.getByText(/1 kept · 1 dropped · 0 to the LLM · 1 not screened/)).toBeInTheDocument();
    expect(screen.getByText(/Demo mode/)).toBeInTheDocument();
    expect(screen.getByText("The paper is a review or an editorial.")).toBeInTheDocument();
  });

  it("shows the job's sanitized error when the test fails", async () => {
    setup(job({ status: "failed", error: "TYPESAFE_API_KEY is not set in the worker" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("The test failed: TYPESAFE_API_KEY is not set in the worker");
  });
});
```

Append to `FieldEditorPage.test.tsx`:

```tsx
  it("tests the unsaved edits in demo mode and shows the results", async () => {
    const { calls } = setup("member", {
      "POST /api/v1/fields/:id/test": { status: 202, body: jobOut({ kind: "criteria_test", run_id: null }) },
      "GET /api/v1/jobs/:id": { body: jobOut({ kind: "criteria_test", run_id: null, status: "done", progress: { status: "done", result: testResult() } }) },
    });
    await form();
    await userEvent.clear(screen.getByLabelText("excl 1"));
    await userEvent.type(screen.getByLabelText("excl 1"), "The paper is a review.");
    await userEvent.click(screen.getByRole("checkbox", { name: /Demo mode/ }));
    await userEvent.click(screen.getByRole("button", { name: "Test criteria" }));
    expect(await screen.findByRole("region", { name: "Criteria test" })).toBeInTheDocument();
    expect(await screen.findByRole("table")).toBeInTheDocument();
    const post = calls.find((c) => c.method === "POST")!;
    expect(post.body).toMatchObject({ mode: "demo", draft: { exclude: [{ text: "The paper is a review." }] } });
    expect((post.body as { draft: Record<string, unknown> }).draft).not.toHaveProperty("note");
  });

  it("shows why the server refused a test", async () => {
    setup("member", { "POST /api/v1/fields/:id/test": { status: 422, body: { code: "no_enabled_source", message: "None of this field's sources is enabled", request_id: "r" } } });
    await form();
    await userEvent.click(screen.getByRole("button", { name: "Test criteria" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("None of this field's sources is enabled");
  });
```
(import `jobOut, testResult` from the fixtures.)

- [ ] **Step 2: Implement**

**File: `web/src/features/fields/CriteriaTestPanel.tsx`**

```tsx
import { useJob } from "../../api/hooks";
import type { CriteriaTestResult, JobProgressData } from "../../api/types";
import { criterionLabel, sourceLabel } from "./labels";

const DECISION: Record<string, string> = { include: "kept", exclude: "dropped", escalate: "to the LLM", not_screened: "not screened (no abstract)" };

function statusText(status: string | undefined, progress: JobProgressData): string {
  if (!status) return "Waiting for the worker…";
  if (status === "queued") return "Queued: waiting for the worker…";
  if (status === "running") return progress.total ? `Testing: ${progress.done ?? 0} of ${progress.total} papers` : "Searching the sources…";
  if (status === "done") return "Test finished.";
  return "The test did not finish.";
}

function TestResults({ result }: { result: CriteriaTestResult }) {
  const { summary } = result;
  return (
    <>
      <p>
        <strong>{summary.total} papers</strong> · {summary.kept} kept · {summary.dropped} dropped · {summary.to_llm} to the LLM
        {summary.not_screened ? ` · ${summary.not_screened} not screened` : ""}
      </p>
      <p className="sub">
        {result.mode === "demo" ? "Demo mode: the numbers come from an offline stand-in, not from Jev." : `Model: ${result.model_version ?? "unknown"}.`}{" "}
        Sources: {result.sources.map(sourceLabel).join(", ")}. The cell that decided a paper says “decided”.
      </p>
      {result.papers.length === 0 ? (
        <p>The sources returned no papers for this topic.</p>
      ) : (
        <div className="table-scroll">
          <table className="papers test">
            <caption className="sr-only">Jev probability per criterion for each paper</caption>
            <thead>
              <tr>
                <th scope="col">Paper</th>
                {result.criteria.map((c) => <th scope="col" key={c.key}><abbr title={c.text}>{criterionLabel(c.key)}</abbr></th>)}
                <th scope="col">Decision</th>
              </tr>
            </thead>
            <tbody>
              {result.papers.map((paper, index) => (
                <tr key={`${paper.source_id}:${index}`}>
                  <th scope="row">{paper.title}<span className="sub">{paper.year ?? ""} {paper.source_id}</span></th>
                  {result.criteria.map((c) => {
                    const p = paper.probabilities[c.key];
                    const decided = paper.decided_by === c.key;
                    return (
                      <td key={c.key} className={decided ? "decider" : undefined}>
                        {p === undefined ? "–" : p.toFixed(2)}{decided && <strong> decided</strong>}
                      </td>
                    );
                  })}
                  <td>{DECISION[paper.decision] ?? paper.decision}{paper.decided_by ? ` · ${criterionLabel(paper.decided_by)}` : ""}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <dl className="criteria-legend">
        {result.criteria.map((c) => (
          <div key={c.key}><dt>{criterionLabel(c.key)}</dt><dd>{c.text}</dd></div>
        ))}
      </dl>
    </>
  );
}

/** Follows a criteria_test job; nothing it shows is written to Papers. */
export function CriteriaTestPanel({ jobId }: { jobId: string }) {
  const job = useJob(jobId);
  const progress = (job.data?.progress ?? {}) as JobProgressData;
  const result = job.data?.status === "done" ? (progress.result as CriteriaTestResult | undefined) : undefined;
  return (
    <section aria-label="Criteria test" className="test-panel">
      <h2>Criteria test</h2>
      <p className="sub">Jev only, at most 20 papers from the field's sources. Nothing is written to Papers.</p>
      <p role="status">{job.isError ? "" : statusText(job.data?.status, progress)}</p>
      {job.isError && <p role="alert" className="form-error">Could not read the test status.</p>}
      {job.data?.status === "failed" && <p role="alert" className="form-error">The test failed: {job.data.error ?? "no details were stored."}</p>}
      {result && <TestResults result={result} />}
    </section>
  );
}
```

Append to `styles.css`:

```css
.test-panel { margin-top: 16px; border-top: 1px solid var(--line); padding-top: 8px; }
table.papers td.decider { outline: 2px solid var(--accent); outline-offset: -2px; font-weight: 600; }
.criteria-legend { display: grid; gap: 2px; font-size: 12px; }
.criteria-legend div { display: flex; gap: 8px; }
.criteria-legend dt { font-weight: 600; min-width: 48px; }
.criteria-legend dd { margin: 0; }
```

- [ ] **Step 3:** PASS, full check, **commit** "Web: criteria test panel (draft testing, progress, per-criterion table, errors)".

---

### Task 9: Runs start form uses fields (preselect, versions, new refusals)

**Files:** Modify `web/src/features/runs/StartRunForm.tsx`, `web/src/pages/RunsPage.tsx`, `web/src/features/runs/RunList.tsx`, `web/src/pages/RunsPage.test.tsx`.

- [ ] **Step 1: Failing tests** (append to the start-form describe in `RunsPage.test.tsx`; the `setup` gains a `route` argument passed to `renderWithProviders(<RunsPage />, { route })`):

```tsx
  it("preselects the field from the URL and names fields with their version", async () => {
    setup("member", { "GET /api/v1/fields": { body: [{ ...fieldOut(), current_version: 3 }] } }, `/runs?field=${FIELD_ID}`);
    const select = await screen.findByLabelText("Field");
    expect(select).toHaveValue(FIELD_ID);
    expect(within(select).getByRole("option", { name: "ML CT-FFR · v3" })).toBeInTheDocument();
  });

  it("explains a field whose sources are all disabled", async () => {
    setup("member", { "POST /api/v1/runs": { status: 422, body: { code: "no_enabled_source", message: "None of this field's sources is enabled", request_id: "r" } } }, `/runs?field=${FIELD_ID}`);
    await userEvent.click(await screen.findByRole("button", { name: "Start run" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Settings → Sources");
  });

  it("shows the refusal for an archived field", async () => {
    setup("member", { "POST /api/v1/runs": { status: 409, body: { code: "archived", message: "This field is archived; restore it first", request_id: "r" } } }, `/runs?field=${FIELD_ID}`);
    await userEvent.click(await screen.findByRole("button", { name: "Start run" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("This field is archived; restore it first");
  });
```

- [ ] **Step 2: Implement** — `StartRunForm` takes `initialFieldId = ""`, starts `useState(initialFieldId)`, option text `{field.name} · v{field.current_version ?? 1}`, and in the catch:

```tsx
      if (error instanceof ApiError && error.code === "no_enabled_source") {
        setProblem(`${error.message}. An admin can enable a source in Settings → Sources, or edit the field to use an enabled one.`);
      } else {
        setProblem(error instanceof ApiError ? error.message : "Could not reach the server.");
      }
```

`RunsPage`: `const [search] = useSearchParams();` and `<StartRunForm onStarted={setJobId} initialFieldId={search.get("field") ?? ""} />`. `RunList` field cell: `{run.field_name}{run.field_version ? ` · v${run.field_version}` : ""}`.

- [ ] **Step 3:** PASS, full check, **commit** "Web: start a run from a field (preselected, versioned, archived and no-source refusals)".

---

### Task 10: Papers — Criteria column, Dropped-by and Source filters, Found by, run picker version

**Files:** Modify `web/src/features/papers/{cells.tsx,cells.test.tsx,PaperTable.tsx,FilterBar.tsx,papersState.ts,papersState.test.ts}`, `web/src/pages/{PapersPage.tsx,PapersPage.test.tsx}`.

- [ ] **Step 1: Failing tests**

`cells.test.tsx`: rename `TopicMatchCell` to `CriteriaCell` in the existing screening tests (legacy behaviour is unchanged) and add:

```tsx
const fieldScreen = (over: Partial<PaperRow["screen"]> = {}): PaperRow["screen"] => ({
  tier: "jev", decision: "exclude", jev_decision: "exclude", llm_decision: null, criteria: { i1: 0.01, i2: 0.9, e1: 0.02 }, decided_by: "i1",
  cells: { i1: { kind: "include", jev_p: 0.01, llm: null, quote: null }, i2: { kind: "include", jev_p: 0.9, llm: null, quote: null }, e1: { kind: "exclude", jev_p: 0.02, llm: null, quote: null } },
  ...over,
});

describe("criteria cell for a field with criteria", () => {
  it("names the criterion Jev dropped the paper on", () => {
    render(<CriteriaCell screen={fieldScreen()} />);
    expect(screen.getByText("dropped by incl 1 (0.01)")).toBeInTheDocument();
  });

  it("names the criterion and the LLM's answer when the LLM decided", () => {
    render(<CriteriaCell screen={fieldScreen({ tier: "llm", jev_decision: "escalate", llm_decision: "exclude", decided_by: "e1", cells: { e1: { kind: "exclude", jev_p: 0.5, llm: "yes", quote: "a narrative review" } } })} />);
    expect(screen.getByText("dropped by excl 1 (LLM: yes)")).toBeInTheDocument();
    expect(screen.getByText("escalated")).toBeInTheDocument();
  });

  it("says all met when kept, and says so when no single criterion decided", () => {
    const { rerender } = render(<CriteriaCell screen={fieldScreen({ decision: "include", jev_decision: "include", decided_by: null })} />);
    expect(screen.getByText("all met")).toBeInTheDocument();
    rerender(<CriteriaCell screen={fieldScreen({ tier: "llm", decision: "uncertain", decided_by: null })} />);
    expect(screen.getByText("no single criterion decided")).toBeInTheDocument();
  });

  it("lists the sources a paper was found in", () => {
    const { rerender } = render(<FoundByCell foundBy="query" sources={["europepmc", "openalex"]} />);
    expect(screen.getByText("Europe PMC, OpenAlex")).toBeInTheDocument();
    rerender(<FoundByCell foundBy="lookup" sources={[]} />);
    expect(screen.getByText("lookup")).toBeInTheDocument();
  });
});
```
(import `FoundByCell` and `type PaperRow`.)

`papersState.test.ts`, add:

```ts
  it("reads the criterion and source filters, ignoring values the API would refuse", () => {
    const view = parseView(new URLSearchParams("by=i1&src=openalex"));
    expect(view.params.decided_by).toBe("i1");
    expect(view.params.source).toBe("openalex");
    const bad = parseView(new URLSearchParams("by=I 1&src=pubmed"));
    expect(bad.params.decided_by).toBeUndefined();
    expect(bad.params.source).toBeUndefined();
  });
```

`PapersPage.test.tsx`: the sort test uses `/Criteria/` instead of `/Topic match/`; add:

```tsx
  it("filters by the deciding criterion and by source, naming criteria from the run's field version", async () => {
    const { calls } = setup({
      "GET /api/v1/runs": { body: [runOut({ field_version: 2 })] },
      "GET /api/v1/fields/:id/versions/2": { body: versionOut() },
    });
    await screen.findByRole("table");
    expect(screen.getByRole("combobox", { name: "Run" })).toHaveTextContent("ML CT-FFR · v2 · eval");
    const by = await screen.findByRole("combobox", { name: "Dropped by criterion" });
    await within(by).findByRole("option", { name: /excl 1: The paper is a review/ });
    await userEvent.selectOptions(by, "e1");
    await userEvent.selectOptions(screen.getByRole("combobox", { name: "Source" }), "openalex");
    const last = new URLSearchParams(calls.filter((c) => c.path.endsWith("/papers")).at(-1)!.search);
    expect(last.get("decided_by")).toBe("e1");
    expect(last.get("source")).toBe("openalex");
    expect(screen.queryByLabelText(/Topic match from/)).not.toBeInTheDocument();
  });
```
(import `versionOut`.)

- [ ] **Step 2: Implement**

**File: `web/src/features/papers/papersState.ts`** — full file:

```ts
import type { PaperParams } from "../../api/hooks";

export const PAGE_SIZE = 25;
const MAX_PAGE = 100_000; // the API refuses larger pages
const SORT = /^(title|year|score|criterion:[a-z0-9_]+)$/;
const DECISIONS = ["include", "exclude", "uncertain"];
const TIERS = ["jev", "llm", "rule"];
const CRITERION_KEY = /^[a-z0-9_]{1,100}$/;
export const PAPER_SOURCES = ["europepmc", "openalex", "arxiv", "demo"];

export type PapersView = { runId: string | null; paperId: string | null; stageId: string | null; params: PaperParams };

const number = (text: string | null, low: number, high: number) => {
  if (text === null || text === "") return undefined;
  const value = Number(text);
  return Number.isFinite(value) && value >= low && value <= high ? value : undefined;
};
const flag = (text: string | null) => (text === "true" ? true : text === "false" ? false : undefined);

export function parseView(search: URLSearchParams): PapersView {
  const sort = search.get("sort") ?? "title";
  const params: PaperParams = {
    page: Math.trunc(number(search.get("page"), 1, MAX_PAGE) ?? 1),
    page_size: PAGE_SIZE,
    sort: SORT.test(sort) ? sort : "title",
    direction: search.get("dir") === "desc" ? "desc" : "asc",
  };
  const decision = search.get("decision");
  if (decision && DECISIONS.includes(decision)) params.decision = decision;
  const tier = search.get("tier");
  if (tier && TIERS.includes(tier)) params.tier = tier;
  const escalated = flag(search.get("escalated"));
  if (escalated !== undefined) params.escalated = escalated;
  const inSr = flag(search.get("in_sr"));
  if (inSr !== undefined) params.in_sr = inSr;
  const by = search.get("by");
  if (by && CRITERION_KEY.test(by)) params.decided_by = by;
  const src = search.get("src");
  if (src && PAPER_SOURCES.includes(src)) params.source = src;
  let pMin = number(search.get("pmin"), 0, 1);
  let pMax = number(search.get("pmax"), 0, 1);
  if (pMin !== undefined && pMax !== undefined && pMin > pMax) pMin = pMax = undefined; // an inverted range is a 422
  if (pMin !== undefined || pMax !== undefined) params.criterion = "topic_match";
  if (pMin !== undefined) params.p_min = pMin;
  if (pMax !== undefined) params.p_max = pMax;
  return { runId: search.get("run"), paperId: search.get("paper"), stageId: search.get("stage"), params };
}

type Changes = Partial<{
  run: string | null; page: number | null; sort: string | null; dir: "asc" | "desc" | null; decision: string | null; tier: string | null;
  escalated: boolean | null; in_sr: boolean | null; pmin: number | null; pmax: number | null; paper: string | null; stage: string | null;
  by: string | null; src: string | null;
}>;

/** Returns new search parameters. Any change other than `page`, `paper` or `stage` goes back to page 1; changing the run closes the panels and drops the criterion filter. */
export function patchView(search: URLSearchParams, changes: Changes, resetPage = true): URLSearchParams {
  const next = new URLSearchParams(search);
  for (const [key, value] of Object.entries(changes)) {
    if (value === null || value === undefined) next.delete(key);
    else next.set(key, String(value));
  }
  if (changes.paper) next.delete("stage");
  if (changes.stage) next.delete("paper");
  if (changes.run !== undefined) {
    next.delete("paper");
    next.delete("stage");
    next.delete("by"); // criterion keys belong to a field version
  }
  if (resetPage && changes.page === undefined) next.delete("page");
  return next;
}
```

**File: `web/src/features/papers/cells.tsx`** — full file:

```tsx
import type { PaperRow } from "../../api/types";
import { criterionLabel, isFieldCriterion, sourceLabel } from "../fields/labels";

const VERDICT: Record<string, string> = { include: "inc", exclude: "exc", uncertain: "unc" };
const verdict = (value: string | null) => (value ? (VERDICT[value] ?? value) : "–");

export const NotApplicable = () => <span className="na" aria-label="not applicable">–</span>;
export const Missing = () => <span className="missing" title="Expected data is missing">missing</span>;

export function ExtractCellView({ cell }: { cell: PaperRow["extract"] }) {
  if (cell === null) return <NotApplicable />;
  if ("missing" in cell) return <Missing />;
  return <span>{cell.claims} {cell.quotes_verified ? "verified" : "unverified"}</span>;
}

export function ReviewsCellView({ cell }: { cell: PaperRow["reviews"] }) {
  if (cell === null) return <NotApplicable />;
  if ("missing" in cell) return <Missing />;
  return (
    <span>
      {verdict(cell.a)} / {verdict(cell.b)}
      {cell.adjudicated && <span className="adj"> adj: {verdict(cell.adjudicator)}</span>}
    </span>
  );
}

type Screen = PaperRow["screen"];

/** The keys of every criterion a screen row carries (Jev probabilities and per-criterion cells). */
export const screenKeys = (screen: Screen) => [...new Set([...Object.keys(screen.criteria), ...Object.keys(screen.cells ?? {})])];

/** "dropped by incl 1 (0.01)", "dropped by excl 1 (LLM: yes)", "all met", … */
export function criteriaText(screen: Screen): string {
  const decider = screen.decided_by ?? null;
  if (decider) {
    const cell = screen.cells?.[decider];
    const p = cell?.jev_p ?? screen.criteria[decider];
    const detail = screen.tier === "llm" && cell?.llm ? `LLM: ${cell.llm}` : p != null ? p.toFixed(2) : null;
    const verb = screen.decision === "exclude" ? "dropped by" : "decided by";
    return `${verb} ${criterionLabel(decider)}${detail ? ` (${detail})` : ""}`;
  }
  if (screen.decision === "include") return "all met";
  if (screen.tier === "rule") return "not screened";
  return "no single criterion decided";
}

/** Legacy runs (only topic_match) show the probability as before; field runs name the criterion that decided. */
export function CriteriaCell({ screen }: { screen: Screen }) {
  const keys = screenKeys(screen);
  if (keys.length === 0) return <NotApplicable />;
  const badges = (
    <>
      {screen.tier === "jev" && <span className="chip chip--ok">Jev</span>}
      {screen.jev_decision === "escalate" && <span className="chip chip--warn">escalated</span>}
    </>
  );
  if (!keys.some(isFieldCriterion)) {
    return (
      <span className="topic">
        {keys.map((key) => {
          const p = screen.criteria[key] ?? screen.cells?.[key]?.jev_p ?? null;
          const text = p === null ? "–" : p.toFixed(2);
          return <strong key={key}>{keys.length > 1 ? `${key} ${text}` : text}</strong>;
        })}
        {badges}
      </span>
    );
  }
  return <span className="topic"><span>{criteriaText(screen)}</span>{badges}</span>;
}

const DECISION: Record<string, string> = { include: "keep", exclude: "drop", uncertain: "unsure" };
const TIER: Record<string, string> = { jev: "Jev", llm: "LLM", rule: "no abstract" };

export function DecisionCell({ screen }: { screen: Screen }) {
  return (
    <span>
      <span className={`decision decision--${screen.decision}`}>{DECISION[screen.decision] ?? screen.decision}</span>{" "}
      <span className="chip">{TIER[screen.tier] ?? screen.tier}</span>
    </span>
  );
}

export const InSrCell = ({ value }: { value: boolean | null }) => (value === null ? <NotApplicable /> : <span>{value ? "yes" : "no"}</span>);
export const ScoreCell = ({ rank }: { rank: PaperRow["rank"] }) => (rank ? <span>{rank.score.toFixed(0)}</span> : <NotApplicable />);

export function FoundByCell({ foundBy, sources = [] }: { foundBy: string; sources?: string[] }) {
  if (sources.length === 0) return <span>{foundBy}</span>;
  return <span>{sources.map(sourceLabel).join(", ")}{foundBy === "lookup" && <span className="sub">lookup</span>}</span>;
}
```

**File: `web/src/features/papers/FilterBar.tsx`** — full file:

```tsx
import { criterionLabel, sourceLabel } from "../fields/labels";
import { PAPER_SOURCES, type PapersView } from "./papersState";

type Change = Partial<{ decision: string | null; tier: string | null; escalated: boolean | null; in_sr: boolean | null; pmin: number | null; pmax: number | null; by: string | null; src: string | null }>;
export type CriterionOption = { key: string; text: string };

const CHIPS: { label: string; sr?: boolean; active: (v: PapersView) => boolean; toggle: (v: PapersView) => Change }[] = [
  { label: "Included", active: (v) => v.params.decision === "include", toggle: (v) => ({ decision: v.params.decision === "include" ? null : "include" }) },
  { label: "Dropped", active: (v) => v.params.decision === "exclude", toggle: (v) => ({ decision: v.params.decision === "exclude" ? null : "exclude" }) },
  { label: "Unsure", active: (v) => v.params.decision === "uncertain", toggle: (v) => ({ decision: v.params.decision === "uncertain" ? null : "uncertain" }) },
  { label: "Decided by Jev", active: (v) => v.params.tier === "jev", toggle: (v) => ({ tier: v.params.tier === "jev" ? null : "jev" }) },
  { label: "Decided by the LLM", active: (v) => v.params.tier === "llm", toggle: (v) => ({ tier: v.params.tier === "llm" ? null : "llm" }) },
  { label: "Only escalated", active: (v) => v.params.escalated === true, toggle: (v) => ({ escalated: v.params.escalated === true ? null : true }) },
  { label: "In the SR", sr: true, active: (v) => v.params.in_sr === true, toggle: (v) => ({ in_sr: v.params.in_sr === true ? null : true }) },
  { label: "Not in the SR", sr: true, active: (v) => v.params.in_sr === false, toggle: (v) => ({ in_sr: v.params.in_sr === false ? null : false }) },
];

type Props = { view: PapersView; showSr: boolean; legacy: boolean; criteria: CriterionOption[]; onChange: (change: Change) => void };

/** `showSr` is false for runs without a gold set (the API refuses in_sr there); the topic-match range only applies to legacy runs. */
export function FilterBar({ view, showSr, legacy, criteria, onChange }: Props) {
  const number = (text: string) => (text === "" ? null : Number(text));
  const selectedBy = view.params.decided_by;
  const options = selectedBy && !criteria.some((c) => c.key === selectedBy) ? [...criteria, { key: selectedBy, text: "" }] : criteria;
  return (
    <div className="filters" role="group" aria-label="Filters">
      {CHIPS.filter((chip) => showSr || !chip.sr).map((chip) => (
        <button key={chip.label} type="button" aria-pressed={chip.active(view)} onClick={() => onChange(chip.toggle(view))}>{chip.label}</button>
      ))}
      <label>Dropped by criterion
        <select value={selectedBy ?? ""} onChange={(e) => onChange({ by: e.target.value || null })}>
          <option value="">any</option>
          {options.map((c) => <option key={c.key} value={c.key}>{criterionLabel(c.key)}{c.text ? `: ${c.text}` : ""}</option>)}
        </select>
      </label>
      <label>Source
        <select value={view.params.source ?? ""} onChange={(e) => onChange({ src: e.target.value || null })}>
          <option value="">any</option>
          {PAPER_SOURCES.map((name) => <option key={name} value={name}>{sourceLabel(name)}</option>)}
        </select>
      </label>
      {legacy && (
        <>
          <label>Topic match from <input type="number" min={0} max={1} step={0.05} value={view.params.p_min ?? ""} onChange={(e) => onChange({ pmin: number(e.target.value) })} /></label>
          <label>to <input type="number" min={0} max={1} step={0.05} value={view.params.p_max ?? ""} onChange={(e) => onChange({ pmax: number(e.target.value) })} /></label>
        </>
      )}
    </div>
  );
}
```

**File: `web/src/features/papers/PaperTable.tsx`** — changes: import `CriteriaCell` instead of `TopicMatchCell`; add prop `legacy: boolean`; the header becomes

```tsx
            {legacy ? <SortHeader label="Criteria" sortKey="criterion:topic_match" {...sortProps} /> : <th scope="col">Criteria</th>}
```
and the cells `<td><FoundByCell foundBy={row.found_by} sources={row.sources ?? []} /></td>` and `<td><CriteriaCell screen={row.screen} /></td>`.

**File: `web/src/pages/PapersPage.tsx`** — changes:

```tsx
import { useFieldVersion, usePapers, useRun, useRuns, useStages } from "../api/hooks";
import { isFieldCriterion } from "../features/fields/labels";
import { screenKeys } from "../features/papers/cells";
import { FilterBar, type CriterionOption } from "../features/papers/FilterBar";
// …
  const version = useFieldVersion(selected?.field_id ?? null, selected?.field_version ?? null);
  // …after papers:
  const criteria: CriterionOption[] = version.data
    ? [...version.data.include, ...version.data.exclude, ...version.data.legacy]
    : [...new Set((papers.data?.items ?? []).flatMap((row) => screenKeys(row.screen)))].map((key) => ({ key, text: "" }));
  const legacy = !criteria.some((c) => isFieldCriterion(c.key));
```
The run option text becomes `{r.field_name}{r.field_version ? ` · v${r.field_version}` : ""} · {r.kind}…`; `<FilterBar view={view} showSr={hasGoldSet} legacy={legacy} criteria={criteria} onChange={(changes) => change(changes)} />`; `<PaperTable legacy={legacy} … />`. (Hooks stay above the early returns.)

- [ ] **Step 3:** PASS, full check, **commit** "Web: Papers name the deciding criterion; filters by criterion and source; sources in Found by; versioned run picker".

---

### Task 11: Drawer — per-criterion Screen step

**Files:** Modify `web/src/features/papers/PaperDrawer.tsx`, `web/src/features/papers/drawer.test.tsx`, `web/src/styles.css`.

- [ ] **Step 1: Failing test** (append to `drawer.test.tsx`, using its existing setup helper and `drawerOut`):

```tsx
  it("shows the screen per criterion, marks the criterion that decided and names the sources", async () => {
    const drawer = drawerOut({
      sources: ["europepmc", "openalex"], found_by: "query",
      screening: {
        ...drawerOut().screening, tier: "llm", decision: "exclude", jev_decision: "escalate", llm_decision: "exclude", decided_by: "i1",
        criteria_table: [
          { key: "i1", kind: "include", text: "The study uses machine learning.", jev_p: 0.2, llm: "no", quote: "change in CT-FFR across the lesion was calculated", decided: true },
          { key: "e1", kind: "exclude", text: "The paper is a review.", jev_p: 0.02, llm: "no", quote: null, decided: false },
        ],
      },
    });
    // render the drawer for LOST_ID with GET /api/v1/runs/:id/papers/:id -> drawer, as the other drawer tests do
    …
    const table = within(panel).getByRole("table", { name: "Screening per criterion" });
    expect(within(table).getByRole("row", { name: /incl 1/ })).toHaveTextContent("(decided)");
    expect(within(table).getByRole("row", { name: /incl 1/ })).toHaveTextContent("“change in CT-FFR across the lesion was calculated”");
    expect(within(panel).getByText(/because incl 1 is not met \(decided by the LLM; Jev was unsure\)/)).toBeInTheDocument();
    expect(within(panel).getByText(/Europe PMC, OpenAlex/)).toBeInTheDocument();
  });
```
(The `…` line is filled in with the file's existing render helper at implementation time; the assertions are exact.)

- [ ] **Step 2: Implement** — in `PaperDrawer.tsx`:

```tsx
import { criterionLabel, isFieldCriterion, sourceLabel } from "../fields/labels";

const DECISION_WORD: Record<string, string> = { include: "keep", exclude: "drop", uncertain: "unsure" };

function decisionSentence(screening: DrawerOut["screening"], decider: CriterionRowOut | undefined): string {
  const word = DECISION_WORD[screening.decision] ?? screening.decision;
  if (decider) {
    const by = screening.tier === "llm" ? `the LLM${screening.jev_decision === "escalate" ? "; Jev was unsure" : ""}` : "Jev";
    return `Decision: ${word}, because ${criterionLabel(decider.key)} ${decider.kind === "exclude" ? "is met" : "is not met"} (decided by ${by}).`;
  }
  if (screening.decision === "include") return `Decision: ${word}, all criteria met.`;
  return `Decision: ${word}; no single criterion decided.`;
}

function CriteriaScreen({ screening }: { screening: DrawerOut["screening"] }) {
  const rows = screening.criteria_table ?? [];
  const decider = rows.find((row) => row.decided);
  return (
    <>
      <table className="criteria-table">
        <caption>Screening per criterion</caption>
        <thead><tr><th scope="col">Criterion</th><th scope="col">Jev p</th><th scope="col">LLM</th><th scope="col">Evidence</th></tr></thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.key} className={row.decided ? "decider" : undefined}>
              <th scope="row">{criterionLabel(row.key)}: {row.text}{row.decided && <strong> (decided)</strong>}</th>
              <td>{row.jev_p === null ? "–" : row.jev_p.toFixed(2)}</td>
              <td>{row.llm ?? "–"}</td>
              <td>{row.quote ? `“${row.quote}”` : "–"}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <p>{decisionSentence(screening, decider)}</p>
      <p className="sub">Quotes are checked against the abstract by code.</p>
    </>
  );
}
```
In `Timeline`, the Search step text becomes

```tsx
        <p>{drawer.found_by === "lookup" ? "Found by direct lookup of the systematic review's reference, not by the search query." : `Found by the search query${(drawer.sources ?? []).length ? ` in ${(drawer.sources ?? []).map(sourceLabel).join(", ")}` : ""}.`}</p>
```
and the Screen step renders `<CriteriaScreen screening={screening} />` when `(screening.criteria_table ?? []).some((row) => isFieldCriterion(row.key))`, else the existing legacy content. Import `type CriterionRowOut`. Append to `styles.css`:

```css
table.criteria-table { border-collapse: collapse; width: 100%; font-size: 12px; margin: 4px 0; }
table.criteria-table caption { text-align: left; font-weight: 600; }
table.criteria-table th, table.criteria-table td { text-align: left; padding: 4px 6px; border-bottom: 1px solid var(--line); vertical-align: top; }
table.criteria-table tr.decider { outline: 2px solid var(--accent); outline-offset: -2px; }
```

- [ ] **Step 3:** PASS, full check, **commit** "Web: drawer Screen step per criterion (Jev p, LLM answer, quote) naming the decider".

---

### Task 12: End-to-end flows, axe audits, docs

**Files:** Modify `web/e2e/flows.spec.ts`, `web/e2e/a11y.spec.ts`, `docs/web-app.md`.

- [ ] **Step 1: Update and add Playwright tests**

In `flows.spec.ts`: the admin invite test goes to `/settings/users`; the viewer test keeps `/users` (now a redirect that shows "Not allowed"). Add to the member describe:

```ts
  test("creates a field, tests its criteria in demo mode, starts a demo run and sees what decided", async ({ page }) => {
    test.setTimeout(180_000);
    await page.goto("/fields");
    await page.getByRole("link", { name: "New field" }).click();
    await page.getByLabel("Name", { exact: true }).fill("E2E plaque");
    await page.getByLabel(/^Topic/).fill("AI plaque characterisation on coronary CT angiography");
    for (const text of ["The study uses machine learning or deep learning.", "Plaque is assessed on coronary CT angiography."]) {
      await page.getByRole("button", { name: "Add inclusion criterion" }).click();
      await page.getByRole("textbox").and(page.locator(".criteria li input")).last().fill(text);
    }
    await page.getByRole("button", { name: "Add exclusion criterion" }).click();
    await page.getByLabel("excl 1", { exact: true }).fill("The paper is a review or an editorial.");
    await page.getByLabel("Change note").fill("first version");
    await page.getByRole("button", { name: "Create field" }).click();
    await expect(page.getByRole("heading", { name: "E2E plaque (v1)" })).toBeVisible();

    await page.getByLabel(/Demo mode/).check();
    await page.getByRole("button", { name: "Test criteria" }).click();
    const results = page.getByRole("region", { name: "Criteria test" });
    await expect(results.getByRole("table")).toBeVisible({ timeout: 60_000 });
    await expect(results).toContainText(/\d+ papers · \d+ kept · \d+ dropped/);

    await page.goto("/fields");
    await page.getByRole("link", { name: "Start run for E2E plaque" }).click();
    await page.getByLabel("Papers to screen").fill("3");
    await page.getByLabel(/Demo mode/).check();
    await page.getByRole("button", { name: "Start run" }).click();
    await expect(page.getByRole("status", { name: "Run progress" })).toContainText("done", { timeout: 120_000 });
    await page.locator("table.runs tbody tr").filter({ hasText: "E2E plaque" }).first().getByRole("link", { name: /See papers/ }).click();
    await expect(page.getByRole("combobox", { name: "Run" })).toContainText("E2E plaque · v1");
    await expect(page.locator("table.papers tbody tr").first()).toContainText(/all met|dropped by (incl|excl) \d|no single criterion decided/);
    await expect(page.getByRole("combobox", { name: "Dropped by criterion" })).toContainText("incl 1: The study uses machine learning or deep learning.");
  });
```

In `a11y.spec.ts` add:

```ts
test.describe("fields and settings", () => {
  test.describe("member", () => {
    test.use({ storageState: auth("member") });
    test("fields list", async ({ page }) => {
      await page.goto("/fields");
      await expect(page.getByRole("heading", { name: "Fields" })).toBeVisible();
      await audit(page);
    });
    test("field editor with test results", async ({ page }) => {
      test.setTimeout(90_000);
      await page.goto("/fields");
      await page.locator("table.runs tbody tr a").first().click();
      await expect(page.getByRole("form", { name: "Field editor" })).toBeVisible();
      await page.getByRole("button", { name: "Add inclusion criterion" }).click();
      await page.getByLabel("incl 1", { exact: true }).fill("The study uses deep learning.");
      await page.getByLabel(/Demo mode/).check();
      await page.getByRole("button", { name: "Test criteria" }).click();
      await expect(page.getByRole("region", { name: "Criteria test" }).getByRole("table")).toBeVisible({ timeout: 60_000 });
      await audit(page);
    });
  });
  test.describe("viewer", () => {
    test.use({ storageState: auth("viewer") });
    for (const tab of ["sources", "models"]) {
      test(`settings ${tab} (read-only)`, async ({ page }) => {
        await page.goto(`/settings/${tab}`);
        await expect(page.getByRole("navigation", { name: "Settings sections" })).toBeVisible();
        await expect(page.getByText(/Read-only/)).toBeVisible();
        await audit(page);
      });
    }
  });
  test.describe("admin", () => {
    test.use({ storageState: auth("admin") });
    for (const tab of ["sources", "models", "users"]) {
      test(`settings ${tab}`, async ({ page }) => {
        await page.goto(`/settings/${tab}`);
        await expect(page.getByRole("navigation", { name: "Settings sections" })).toBeVisible();
        await audit(page);
      });
    }
  });
});
```
and the old admin "users" audit is replaced by the `settings users` one.

- [ ] **Step 2: Run** `cd web && npm run e2e` → all pass (fix any real failures; the dataset change in `scripts/e2e_server.py` is only made if a test needs it). Then stop servers: `lsof -ti tcp:8000 tcp:4173 | xargs -r kill`.

- [ ] **Step 3: Docs** — in `docs/web-app.md`, the frontend list becomes "(Papers, Runs, Fields, Evals, System map, Settings)" and a short "Fields and Settings in the browser" section documents: creating and versioning fields, the 409 reload, Test criteria (Jev only, demo mode offline), archive/restore (admins), Settings tabs and who may write, `/users` → `/settings/users`.

- [ ] **Step 4: Commit** `git add web/e2e/flows.spec.ts web/e2e/a11y.spec.ts docs/web-app.md` (plus `scripts/e2e_server.py` only if changed) — "Web: e2e flow create field → test → run → decided-by, axe on Fields and Settings; docs".

---

## Self-review

- **Spec coverage.** Screens 1 (Task 5), 2 (Tasks 6–7), 3 (Task 8), 4 (Tasks 2–4), 5 (Task 10), 6 (Task 11); errors: 409 stale (Task 7), criteria-test failures (Task 8), rejected key display (Task 4), no_enabled_source/archived on start (Task 9); Testing → Frontend: editor add/reorder/remove/validation/409 (Task 7), test table (Task 8), Settings and read-only (Tasks 3–4), Criteria cell and drawer table (Tasks 10–11), Playwright flow and axe (Task 12). Success criteria: 3 incl + 2 excl, test, save v2, run and see decider (Task 12 exercises the same path with 2 + 1); "arXiv enabled → Found by lists arXiv" is covered by Settings enable (Task 3) and Found by (Task 10) but not end to end (no network in e2e).
- **Placeholders.** One deliberate reference: the drawer test's render lines reuse the existing helper in `drawer.test.tsx` (shown there); all component code is complete.
- **Type consistency.** `useFields({enabled, archived})`, `FieldBody`, `CriteriaTestResult`, `JobProgressData`, `SourceCheckResult`, `CriterionOption`, `screenKeys`, `criteriaText`, `FoundByCell({foundBy, sources})`, `PaperParams.decided_by/source`, URL keys `by`/`src` are used with the same names in every task.

## Execution notes (2026-09-29)

- **Accessible names with visually hidden text.** `dom-accessibility-api` (Testing Library) drops the leading space inside
  `<span className="sr-only"> …</span>`, so names like "TestOpenAlex" came out glued. The implemented code puts the space
  outside: `Test{" "}<span className="sr-only">{label}</span>` (SourcesTab buttons and checkbox, FieldsPage "Start run").
- **Test adjustments.** The "creates a new field" test mocks `GET /fields/:id` with the created field (the page refetches
  on mount) and checks "Save the field first" before creating; the history test waits for the measurement with `findByText`;
  two RunsPage tests target the form error by text because the page also shows the fixture's failed-run alert.
- **Task 7/8 split.** `CriteriaTestPanel.tsx` was created in Task 7 (the editor imports it), so its Task 8 tests passed on
  the first run instead of failing first.
- **e2e.** Settings tab audits check the tab's `h2` instead of a table: the e2e worker does not run the start-up key check,
  so AI models shows "No worker has reported yet". No dataset change in `scripts/e2e_server.py` was needed.
