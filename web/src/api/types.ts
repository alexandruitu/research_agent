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
