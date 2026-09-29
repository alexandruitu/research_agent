import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api, uploadFile } from "./client";
import type {
  CallOut, DrawerOut, ModelsAvailableOut, PaperFileOut, ReviewerCreate, ReviewerOut, ReviewerSave, ReviewSettingsContent, ReviewSettingsOut, EvalDetailOut, EvalSummaryOut, FieldDraft, FieldOut, FieldVersionOut, JobOut, PaperPage, RunDetailOut, RunOut,
  SettingsOut, SourceOut, StageOut, StartRunOut, UserOut, WorkerStatusOut,
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
  allReviewers: ["reviewers"] as const,
  reviewers: (archived: boolean) => ["reviewers", { archived }] as const,
  reviewer: (key: string) => ["reviewer", key] as const,
  reviewSettings: ["review-settings"] as const,
  models: ["models-available"] as const,
  paperFiles: (paperId: string) => ["paper-files", paperId] as const,
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
