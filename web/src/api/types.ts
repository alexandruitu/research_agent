import type { components } from "./schema";

type S = components["schemas"];

export type UserOut = S["UserOut"];
export type SessionOut = S["SessionOut"];
export type FieldOut = S["FieldOut"];
export type RunOut = S["RunOut"];
export type RunDetailOut = S["RunDetailOut"];
export type RunCounts = S["RunCounts"];
export type PaperRow = S["PaperRow"];
export type PaperPage = S["PaperPage"];
export type DrawerOut = S["DrawerOut"];
export type CallOut = S["CallOut"];
export type StageOut = S["StageOut"];
export type EvalSummaryOut = S["EvalSummaryOut"];
export type EvalDetailOut = S["EvalDetailOut"];
export type JobOut = S["JobOut"];
export type StartRunOut = S["StartRunOut"];
export type ReviewOut = S["ReviewOut"];

export type Role = "viewer" | "member" | "admin";
export const ROLE_ORDER: Record<Role, number> = { viewer: 0, member: 1, admin: 2 };
export const hasRole = (user: { role: string } | null | undefined, minimum: Role): boolean =>
  !!user && (ROLE_ORDER[user.role as Role] ?? -1) >= ROLE_ORDER[minimum];
