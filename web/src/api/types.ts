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
export type EvalKind = "screening" | "panel" | "ablation" | "human";
export type EvalJobOut = S["EvalJobOut"];
export type EvalRequest = S["EvalRequest"];
export type EvalHeadline = S["EvalHeadline"];
export type EstimateOut = S["EstimateOut"];
export type CompareOut = S["CompareOut"];
export type CompareRow = S["CompareRow"];
export type GoldSetOut = S["GoldSetOut"];
export type GoldSetRequest = S["GoldSetRequest"];
export type GoldStudyIn = S["GoldStudyIn"];
export type RatingSampleOut = S["RatingSampleOut"];
export type RatingNextOut = S["RatingNextOut"];
export type RatingReviewerOut = S["RatingReviewerOut"];
export type RatingAnswerIn = S["RatingAnswerIn"];
export type RatingSubmitIn = S["RatingSubmitIn"];
export type RatingSubmitOut = S["RatingSubmitOut"];
export type RevealOut = S["RevealOut"];
/** `progress` of an eval_run / gold_build job. */
export type EvalJobProgress = { status?: string; kind?: string; step?: string | null; steps?: string[]; done?: number; total?: number; result?: { eval_id?: string; gold_set_id?: string } };
export type StartRunOut = S["StartRunOut"];
export type ReviewOut = S["ReviewOut"];
export type SourceOut = S["SourceOut"];
export type SettingsOut = S["SettingsOut"];
export type WorkerStatusOut = S["WorkerStatusOut"];
export type ReviewerOut = S["ReviewerOut"];
export type ReviewerVersionOut = S["ReviewerVersionOut"];
export type ReviewerContent = S["ReviewerContent"];
export type ChecklistItemIn = S["ChecklistItemIn"];
export type ChecklistItemOut = S["ChecklistItemOut"];
export type ReviewerSave = S["ReviewerSave"];
export type ReviewerCreate = S["ReviewerCreate"];
export type ReviewSettingsOut = S["ReviewSettingsOut"];
export type ReviewSettingsContent = S["ReviewSettingsContent"];
export type ReviewSettingsVersionOut = S["ReviewSettingsVersionOut"];
export type ScreeningIO = S["ScreeningIO"];
export type FulltextIO = S["FulltextIO"];
export type RoleModelsIO = S["RoleModelsIO"];
export type ModelsAvailableOut = S["ModelsAvailableOut"];
export type AvailableModelOut = S["AvailableModelOut"];
export type PanelOut = S["PanelOut"];
export type PanelReportOut = S["PanelReportOut"];
export type PanelAnswerOut = S["PanelAnswerOut"];
export type PaperFileOut = S["PaperFileOut"];
export type KeywordsIO = S["KeywordsIO"];
export type QueryOverrideIO = S["QueryOverrideIO"];
export type CollectionOut = S["CollectionOut"];
export type CollectionRef = S["CollectionRef"];
export type LibraryRef = S["LibraryRef"];
export type LibraryItemOut = S["LibraryItemOut"];
export type LibraryItemDetail = S["LibraryItemDetail"];
export type LibraryEventOut = S["LibraryEventOut"];
export type LibraryPage = S["LibraryPage"];
export type LibrarySaveRequest = S["LibrarySaveRequest"];
export type LibrarySaveOut = S["LibrarySaveOut"];
export type LibraryPatch = S["LibraryPatch"];

export type KeywordGroup = "all" | "any" | "none";
export type KeywordSuggestion = { term: string; synonyms: string[] };
/** `progress.result` of a finished field_assist job. */
export type AssistResult = {
  mode: string; model: string | null;
  suggestions: { all: KeywordSuggestion[]; any: KeywordSuggestion[]; none: KeywordSuggestion[]; include: string[]; exclude: string[] };
};
export type PreviewSource = {
  source: string; query: string | null; effective_query: string | null; count: number | null;
  papers: { id: string; title: string; year: number | null }[]; error: string | null;
};
/** `progress.result` of a finished field_preview job. */
export type PreviewResult = { mode: string; years: { from: number | null; to: number | null }; sources: PreviewSource[] };

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
