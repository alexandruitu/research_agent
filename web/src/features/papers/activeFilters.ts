import { criterionLabel, sourceLabel } from "../fields/labels";
import type { CriterionOption } from "./FilterBar";
import { patchView, type PapersView } from "./papersState";

type Clear = Parameters<typeof patchView>[1];
export type FilterChip = { label: string; clear: Clear };

const DECISION: Record<string, string> = { include: "Included", exclude: "Dropped", uncertain: "Unsure" };
const TIER: Record<string, string> = { jev: "Decided by Jev", llm: "Decided by the LLM", rule: "Not screened" };

/** Each active filter as a removable chip, in words. */
export function activeFilterChips(view: PapersView, criteria: CriterionOption[]): FilterChip[] {
  const p = view.params;
  const chips: FilterChip[] = [];
  if (p.decision) chips.push({ label: DECISION[p.decision] ?? p.decision, clear: { decision: null } });
  if (p.tier) chips.push({ label: TIER[p.tier] ?? p.tier, clear: { tier: null } });
  if (p.escalated) chips.push({ label: "Only escalated", clear: { escalated: null } });
  if (p.has_red_flags) chips.push({ label: "Has red flags", clear: { flags: null } });
  if (p.in_sr !== undefined) chips.push({ label: p.in_sr ? "In the SR" : "Not in the SR", clear: { in_sr: null } });
  if (p.decided_by) {
    const text = criteria.find((c) => c.key === p.decided_by)?.text;
    chips.push({ label: `Decided by ${criterionLabel(p.decided_by)}${text ? `: ${text.length > 40 ? `${text.slice(0, 40)}…` : text}` : ""}`, clear: { by: null } });
  }
  if (p.source) chips.push({ label: `Source: ${sourceLabel(p.source)}`, clear: { src: null } });
  if (p.p_min !== undefined || p.p_max !== undefined) chips.push({ label: `Topic match ${p.p_min ?? 0}–${p.p_max ?? 1}`, clear: { pmin: null, pmax: null } });
  return chips;
}

export const clearPaperFilters = (search: URLSearchParams) =>
  patchView(search, { decision: null, tier: null, escalated: null, flags: null, in_sr: null, by: null, src: null, pmin: null, pmax: null });
