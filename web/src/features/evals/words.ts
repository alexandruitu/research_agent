import type { EvalKind } from "../../api/types";
import { toRate, type Rate } from "./metrics";

export type Json = Record<string, unknown>;
export const obj = (value: unknown): Json | null => (value && typeof value === "object" && !Array.isArray(value) ? (value as Json) : null);
export const num = (value: unknown): number | null => (typeof value === "number" && Number.isFinite(value) ? value : null);
export const str = (value: unknown, fallback = ""): string => (typeof value === "string" ? value : fallback);
export const list = (value: unknown): unknown[] => (Array.isArray(value) ? value : []);
export const strings = (value: unknown): string[] => list(value).filter((x): x is string => typeof x === "string");
export { toRate };

/** Landis and Koch bands, so a kappa is never only a number. */
export function kappaWords(kappa: number | null): string {
  if (kappa === null) return "not measured";
  if (kappa < 0) return "worse than chance";
  if (kappa < 0.2) return "slight";
  if (kappa < 0.4) return "fair";
  if (kappa < 0.6) return "moderate";
  if (kappa < 0.8) return "substantial";
  return "almost perfect";
}

export const pct = (share: number | null | undefined): string => (share === null || share === undefined ? "n/a" : `${Math.round(share * 100)}%`);
export const fixed = (value: number | null | undefined, digits = 2): string => (value === null || value === undefined ? "n/a" : value.toFixed(digits));

export function ratioText(rate: Rate | null): string {
  if (!rate) return "n/a";
  if (rate.value === null) return `n/a${rate.reason ? ` (${rate.reason})` : ""}`;
  return `${pct(rate.value)} (${rate.k} of ${rate.n})`;
}

/** A kappa given as a number or as a Cohen/Fleiss object `{kappa}`. */
export const scoreOf = (value: unknown): number | null => num(value) ?? num(obj(value)?.kappa);

export const KIND_LABEL: Record<EvalKind, string> = { screening: "Screening", panel: "Review panel", ablation: "1 / 2 / 3 reviewers", human: "Human reference" };
export const KIND_ICON: Record<EvalKind, string> = { screening: "⌕", panel: "☰", ablation: "⅓", human: "✎" };
export const KIND_WHAT: Record<EvalKind, string> = {
  screening: "Does the search and the Jev → LLM screen keep the papers a systematic review included?",
  panel: "Do the reviewers agree with each other, item by item, and does their score separate SR-included papers?",
  ablation: "Does each extra reviewer earn its cost? Re-scores every subset of a panel evaluation offline.",
  human: "Are the reviewers right? Compares their answers with people's blind ratings.",
};
export type Family = "screening" | "panel" | "ablation";
export const familyOf = (kind: string | undefined): Family => (kind === "panel" || kind === "human" ? "panel" : kind === "ablation" ? "ablation" : "screening");
export const kindOf = (kind: string | undefined): EvalKind => (kind === "panel" || kind === "human" || kind === "ablation" ? kind : "screening");

export const dateText = (iso: string) => new Date(iso).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
