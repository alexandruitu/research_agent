import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api, uploadFile } from "./client";
import type {
  BulkDeleteOut, CallOut, CallsSummaryOut, CancelOut, CollectionOut, DeleteOut, RunCompareOut, RunLogOut, RunPatch, DrawerOut, KeywordsIO, LibraryItemDetail, LibraryPage, LibraryPatch, LibrarySaveOut, LibrarySaveRequest, QueryOverrideIO, ModelsAvailableOut, PaperFileOut, ReviewerCreate, ReviewerOut, ReviewerSave, ReviewSettingsContent, ReviewSettingsOut, EvalDetailOut, EvalSummaryOut, FieldDraft, FieldOut, FieldVersionOut, JobOut, PaperPage, RunDetailOut, RunOut,
  CompareOut, EstimateOut, EvalJobOut, EvalKind, EvalRequest, GoldSetOut, GoldSetRequest, RatingNextOut, RatingSampleOut, RatingSubmitIn, RatingSubmitOut, RevealOut,
  ReviewerVersionOut, SettingsOut, SourceOut, StageOut, StartRunOut, UserOut, WorkerStatusOut,
} from "./types";

export type PaperParams = {
  page: number; page_size: number; sort: string; direction: "asc" | "desc";
  decision?: string; tier?: string; escalated?: boolean; in_sr?: boolean; criterion?: string; p_min?: number; p_max?: number;
  decided_by?: string; source?: string; has_red_flags?: boolean;
};

export const keys = {
  allFields: ["fields"] as const,
  fields: (archived: boolean) => ["fields", { archived }] as const,
  field: (id: string) => ["field", id] as const,
  fieldVersion: (id: string, version: number) => ["field", id, "version", version] as const,
  runs: ["runs"] as const,
  run: (id: string) => ["run", id] as const,
  runList: (params: RunListParams) => ["runs", "list", params] as const,
  runLog: (id: string, lines: number) => ["run", id, "log", lines] as const,
  runCalls: (id: string) => ["run", id, "calls"] as const,
  runCompare: (a: string, b: string) => ["runs", "compare", a, b] as const,
  papers: (runId: string, params: PaperParams) => ["papers", runId, params] as const,
  paper: (runId: string, paperId: string) => ["paper", runId, paperId] as const,
  stages: ["stages"] as const,
  evals: ["evals"] as const,
  eval: (id: string) => ["eval", id] as const,
  evalList: (kind: EvalKind | null) => ["evals", { kind }] as const,
  evalJobs: ["evals", "jobs"] as const,
  compare: (ids: string[]) => ["evals", "compare", ids] as const,
  goldSets: ["gold-sets"] as const,
  ratingSample: (id: string) => ["rating-sample", id] as const,
  ratingNext: (id: string) => ["rating-sample", id, "next"] as const,
  reveal: (id: string, paperId: string) => ["rating-sample", id, "reveal", paperId] as const,
  job: (id: string) => ["job", id] as const,
  call: (runId: string, key: string) => ["call", runId, key] as const,
  users: ["users"] as const,
  sources: ["sources"] as const,
  settings: ["settings"] as const,
  workers: ["workers"] as const,
  allReviewers: ["reviewers"] as const,
  reviewers: (archived: boolean) => ["reviewers", { archived }] as const,
  reviewer: (key: string) => ["reviewer", key] as const,
  reviewSettings: ["review-settings"] as const,
  models: ["models-available"] as const,
  paperFiles: (paperId: string) => ["paper-files", paperId] as const,
  allLibrary: ["library"] as const,
  library: (params: LibraryParams) => ["library", "list", params] as const,
  libraryItem: (id: string) => ["library", "item", id] as const,
  allCollections: ["collections"] as const,
  collections: (archived: boolean) => ["collections", { archived }] as const,
  reviewerVersion: (key: string, version: number) => ["reviewer", key, "version", version] as const,
};

export type LibraryParams = {
  q?: string; collection_id?: string; status?: string; tag?: string; field_id?: string; min_score?: number; has_red_flags?: boolean;
  sort?: string; direction?: "asc" | "desc"; page?: number; page_size?: number;
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
export type RunListParams = {
  kind?: "research" | "eval"; status?: string; field_id?: string; mine?: boolean; created_from?: string; created_to?: string;
  q?: string; sort?: "created" | "name" | "status" | "papers"; direction?: "asc" | "desc";
};
const RUN_ACTIVE = ["queued", "running"];
export const isActive = (status: string | undefined) => RUN_ACTIVE.includes(status ?? "");

/** Without params: every run (the Papers run picker). With params: the Runs list, polled while a run is active. */
export const useRuns = (params?: RunListParams) =>
  useQuery({
    queryKey: params ? keys.runList(params) : keys.runs,
    queryFn: () => api.get<RunOut[]>("/runs", params),
    placeholderData: params ? keepPreviousData : undefined,
    refetchInterval: (query) => (params && query.state.data?.some((run) => isActive(run.status)) ? 3000 : false),
  });
export const useRun = (id: string | null) =>
  useQuery({
    queryKey: keys.run(id ?? ""), enabled: !!id, queryFn: () => api.get<RunDetailOut>(`/runs/${id}`),
    refetchInterval: (query) => (isActive(query.state.data?.status) ? 3000 : false),
  });
export const useRunLog = (id: string, lines: number, enabled: boolean) =>
  useQuery({ queryKey: keys.runLog(id, lines), enabled, retry: false, queryFn: () => api.get<RunLogOut>(`/runs/${id}/log`, { lines }) });
export const useRunCalls = (id: string, enabled: boolean) =>
  useQuery({ queryKey: keys.runCalls(id), enabled, retry: false, queryFn: () => api.get<CallsSummaryOut>(`/runs/${id}/calls`) });
export const useRunCompare = (a: string | null, b: string | null) =>
  useQuery({
    queryKey: keys.runCompare(a ?? "", b ?? ""), enabled: !!a && !!b && a !== b, retry: false,
    queryFn: () => api.get<RunCompareOut>("/runs/compare", { ids: `${a},${b}` }),
  });
export const runExportUrl = (id: string, format: "csv" | "bibtex" | "bundle") => `/api/v1/runs/${id}/export?format=${format}`;
export const runsExportUrl = (ids: string[], format: "csv" | "bibtex") => `/api/v1/runs/export?ids=${ids.join(",")}&format=${format}`;
export const usePapers = (runId: string | null, params: PaperParams) =>
  useQuery({
    queryKey: keys.papers(runId ?? "", params), enabled: !!runId, placeholderData: keepPreviousData,
    queryFn: () => api.get<PaperPage>(`/runs/${runId}/papers`, params),
  });
export const usePaper = (runId: string | null, paperId: string | null) =>
  useQuery({ queryKey: keys.paper(runId ?? "", paperId ?? ""), enabled: !!runId && !!paperId, queryFn: () => api.get<DrawerOut>(`/runs/${runId}/papers/${paperId}`) });
export const useStages = () => useQuery({ queryKey: keys.stages, queryFn: () => api.get<StageOut[]>("/stages") });
export const useEvals = (kind: EvalKind | null = null) =>
  useQuery({ queryKey: kind ? keys.evalList(kind) : keys.evals, queryFn: () => api.get<EvalSummaryOut[]>("/evals", { kind }) });
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
    onSuccess: (_data, runId) => {
      void client.invalidateQueries({ queryKey: keys.runs });
      void client.invalidateQueries({ queryKey: keys.run(runId) });
    },
  });
}

/** A new run from an old one: `same` reuses its frozen configuration, `current` today's field and review settings. */
export function useRerun() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ runId, config }: { runId: string; config: "same" | "current" }) =>
      api.post<StartRunOut>(`/runs/${runId}/rerun`, { body: { config }, headers: { "Idempotency-Key": newIdempotencyKey() } }),
    onSuccess: () => client.invalidateQueries({ queryKey: keys.runs }),
  });
}

export function useCancelRun() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (runId: string) => api.post<CancelOut>(`/runs/${runId}/cancel`),
    onSuccess: (_data, runId) => {
      void client.invalidateQueries({ queryKey: keys.runs });
      void client.invalidateQueries({ queryKey: keys.run(runId) });
    },
  });
}

export function usePatchRun() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ runId, patch }: { runId: string; patch: RunPatch }) => api.patch<RunOut>(`/runs/${runId}`, { body: patch }),
    onSuccess: (_data, { runId }) => {
      void client.invalidateQueries({ queryKey: keys.runs });
      void client.invalidateQueries({ queryKey: keys.run(runId) });
    },
  });
}

export function useDeleteRuns() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async (ids: string[]): Promise<BulkDeleteOut> => {
      if (ids.length === 1) {
        await api.delete<DeleteOut>(`/runs/${ids[0]}`);
        return { deleted: ids, refused: [] };
      }
      return api.post<BulkDeleteOut>("/runs/delete", { body: { ids } });
    },
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

export const useReviewers = (archived = false) =>
  useQuery({ queryKey: keys.reviewers(archived), queryFn: () => api.get<ReviewerOut[]>("/reviewers", { archived }) });
export const useReviewer = (key: string | null) =>
  useQuery({ queryKey: keys.reviewer(key ?? ""), enabled: !!key, queryFn: () => api.get<ReviewerOut>(`/reviewers/${key}`) });
export const useReviewSettings = () => useQuery({ queryKey: keys.reviewSettings, queryFn: () => api.get<ReviewSettingsOut>("/settings/review") });
export const useModelsAvailable = () => useQuery({ queryKey: keys.models, queryFn: () => api.get<ModelsAvailableOut>("/models/available") });
export const usePaperFiles = (paperId: string | null) =>
  useQuery({ queryKey: keys.paperFiles(paperId ?? ""), enabled: !!paperId, queryFn: () => api.get<PaperFileOut[]>(`/papers/${paperId}/files`) });

/** Creates a reviewer (key null) or saves its next version against `baseVersion` (409 stale_version if it moved on). */
export function useSaveReviewer() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ key, baseVersion, body }: { key: string | null; baseVersion: number | null; body: Omit<ReviewerSave, "base_version"> & { key?: string | null } }) =>
      key
        ? api.post<ReviewerOut>(`/reviewers/${key}/versions`, { body: { ...body, base_version: baseVersion } })
        : api.post<ReviewerOut>("/reviewers", { body: body as ReviewerCreate }),
    onSuccess: (reviewer) => {
      client.setQueryData(keys.reviewer(reviewer.key), reviewer);
      void client.invalidateQueries({ queryKey: keys.allReviewers });
      void client.invalidateQueries({ queryKey: keys.models });
    },
  });
}

export function useArchiveReviewer() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ key, archive }: { key: string; archive: boolean }) => api.post<ReviewerOut>(`/reviewers/${key}/${archive ? "archive" : "restore"}`),
    onSuccess: (reviewer) => {
      client.setQueryData(keys.reviewer(reviewer.key), reviewer);
      void client.invalidateQueries({ queryKey: keys.allReviewers });
    },
  });
}

export type ReviewSettingsBody = ReviewSettingsContent & { note: string; base_version: number };

export function useSaveReviewSettings() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body: ReviewSettingsBody) => api.post<ReviewSettingsOut>("/settings/review", { body }),
    onSuccess: (settings) => {
      client.setQueryData(keys.reviewSettings, settings);
      void client.invalidateQueries({ queryKey: keys.allReviewers });
      void client.invalidateQueries({ queryKey: keys.models });
    },
  });
}

export function useUploadPaperFile(paperId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ file, onProgress }: { file: File; onProgress?: (fraction: number) => void }) =>
      uploadFile<PaperFileOut>(`/papers/${paperId}/files`, file, onProgress),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: keys.paperFiles(paperId) });
      void client.invalidateQueries({ queryKey: ["paper"] });
    },
  });
}

export function useDeletePaperFile(paperId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (fileId: string) => api.delete(`/papers/${paperId}/files/${fileId}`),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: keys.paperFiles(paperId) });
      void client.invalidateQueries({ queryKey: ["paper"] });
    },
  });
}

export const useReviewerVersion = (key: string | null, version: number | null) =>
  useQuery({
    queryKey: keys.reviewerVersion(key ?? "", version ?? 0), enabled: !!key && !!version, retry: false, staleTime: Infinity,
    queryFn: () => api.get<ReviewerVersionOut>(`/reviewers/${key}/versions/${version}`),
  });

/* ---------- field assist and preview (worker jobs) ---------- */

export type AssistBody = { description: string; topic: string; keywords: KeywordsIO | null; mode: "live" | "demo" };
export const useAssist = () => useMutation({ mutationFn: (body: AssistBody) => api.post<JobOut>("/fields/assist", { body }) });

export type PreviewBody = {
  keywords: KeywordsIO | null; query_override: QueryOverrideIO | null; sources: string[];
  years: { from: number | null; to: number | null }; mode: "live" | "demo";
};
export const usePreview = () => useMutation({ mutationFn: (body: PreviewBody) => api.post<JobOut>("/fields/preview", { body }) });

/* ---------- team library ---------- */

export const useLibrary = (params: LibraryParams) =>
  useQuery({ queryKey: keys.library(params), placeholderData: keepPreviousData, queryFn: () => api.get<LibraryPage>("/library", params) });
export const useLibraryItem = (id: string | null) =>
  useQuery({ queryKey: keys.libraryItem(id ?? ""), enabled: !!id, queryFn: () => api.get<LibraryItemDetail>(`/library/${id}`) });
export const useCollections = (archived = false) =>
  useQuery({ queryKey: keys.collections(archived), queryFn: () => api.get<CollectionOut[]>("/library/collections", { archived }) });

/** Everything that shows library state: the library itself, collections (counts) and paper rows/drawers. */
function refreshLibrary(client: ReturnType<typeof useQueryClient>) {
  void client.invalidateQueries({ queryKey: keys.allLibrary });
  void client.invalidateQueries({ queryKey: keys.allCollections });
  void client.invalidateQueries({ queryKey: ["papers"] });
  void client.invalidateQueries({ queryKey: ["paper"] });
}

export function useSaveToLibrary() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body: LibrarySaveRequest) => api.post<LibrarySaveOut>("/library", { body }),
    onSettled: () => refreshLibrary(client),
  });
}

export function usePatchLibraryItem() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ id, ...body }: LibraryPatch & { id: string }) => api.patch<LibraryItemDetail>(`/library/${id}`, { body }),
    onSuccess: (item) => client.setQueryData(keys.libraryItem(item.id), item),
    onSettled: () => refreshLibrary(client),
  });
}

export function useDeleteLibraryItems() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async (ids: string[]) => {
      for (const id of ids) await api.delete(`/library/${id}`);
    },
    onSettled: () => refreshLibrary(client),
  });
}

export function useSnapshotItem() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ id, runId }: { id: string; runId: string }) => api.post<LibraryItemDetail>(`/library/${id}/snapshot`, { body: { run_id: runId } }),
    onSuccess: (item) => client.setQueryData(keys.libraryItem(item.id), item),
    onSettled: () => refreshLibrary(client),
  });
}

export function useCreateCollection() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body: { name: string; description?: string }) => api.post<CollectionOut>("/library/collections", { body }),
    onSettled: () => void client.invalidateQueries({ queryKey: keys.allCollections }),
  });
}

export function usePatchCollection() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ id, ...body }: { id: string; name?: string; description?: string }) => api.patch<CollectionOut>(`/library/collections/${id}`, { body }),
    onSettled: () => refreshLibrary(client),
  });
}

export function useArchiveCollection() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ id, archive }: { id: string; archive: boolean }) => api.post<CollectionOut>(`/library/collections/${id}/${archive ? "archive" : "restore"}`),
    onSettled: () => refreshLibrary(client),
  });
}

/** The export download: same origin, cookies, GET (no CSRF). Empty filters are left out. */
export function exportUrl(params: LibraryParams, format: "csv" | "bibtex"): string {
  const search = new URLSearchParams({ format });
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === null || value === "" || key === "page" || key === "page_size") continue;
    search.set(key, String(value));
  }
  return `/api/v1/library/export?${search.toString()}`;
}

// --- live evals ------------------------------------------------------------------------------------------

const ACTIVE = ["queued", "running"];
/** Evaluations without a report yet; polls every 3 seconds while one is queued or running. */
export const useEvalJobs = (enabled = true) =>
  useQuery({
    queryKey: keys.evalJobs, enabled, queryFn: () => api.get<EvalJobOut[]>("/evals/jobs"),
    refetchInterval: (query) => ((query.state.data ?? []).some((j) => ACTIVE.includes(j.job.status)) ? 3000 : false),
  });
export const useGoldSets = (enabled = true) => useQuery({ queryKey: keys.goldSets, enabled, queryFn: () => api.get<GoldSetOut[]>("/gold-sets") });
export const useCompare = (ids: string[]) =>
  useQuery({ queryKey: keys.compare(ids), enabled: ids.length >= 2, retry: false, queryFn: () => api.get<CompareOut>("/evals/compare", { ids: ids.join(",") }) });
export const useEstimate = () => useMutation({ mutationFn: (body: EvalRequest) => api.post<EstimateOut>("/evals/estimate", { body }) });
export function useStartEval() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body: EvalRequest) => api.post<JobOut>("/evals", { body, headers: { "Idempotency-Key": newIdempotencyKey() } }),
    onSuccess: () => client.invalidateQueries({ queryKey: keys.evalJobs }),
  });
}
export const useBuildGoldSet = () =>
  useMutation({ mutationFn: (body: GoldSetRequest) => api.post<JobOut>("/gold-sets", { body, headers: { "Idempotency-Key": newIdempotencyKey() } }) });
export function useCreateRatingSample(evalId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body: { size: number; seed: number }) => api.post<RatingSampleOut>(`/evals/${evalId}/rating-samples`, { body }),
    onSuccess: () => client.invalidateQueries({ queryKey: keys.eval(evalId) }),
  });
}
export const useRatingSample = (id: string | null) =>
  useQuery({ queryKey: keys.ratingSample(id ?? ""), enabled: !!id, queryFn: () => api.get<RatingSampleOut>(`/rating-samples/${id}`) });
export const useRatingNext = (id: string) =>
  useQuery({ queryKey: keys.ratingNext(id), queryFn: () => api.get<RatingNextOut>(`/rating-samples/${id}/next`), gcTime: 0, staleTime: Infinity });
export function useSubmitRatings(sampleId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body: RatingSubmitIn) => api.post<RatingSubmitOut>(`/rating-samples/${sampleId}/ratings`, { body }),
    onSuccess: () => client.invalidateQueries({ queryKey: keys.ratingSample(sampleId) }),
  });
}
export const useReveal = (sampleId: string, paperId: string | null) =>
  useQuery({ queryKey: keys.reveal(sampleId, paperId ?? ""), enabled: !!paperId, retry: false, queryFn: () => api.get<RevealOut>(`/rating-samples/${sampleId}/papers/${encodeURIComponent(paperId ?? "")}/reveal`) });
