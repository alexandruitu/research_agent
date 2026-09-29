import type { ScreeningIO } from "../../api/types";
import type { Pair } from "../evals/metrics";

const round2 = (value: number) => Math.round(value * 100) / 100;
const round5 = (percent: number) => Math.round(percent / 5) * 5;

/**
 * The Evals pair (Jev confidence |2p − 1|) in probabilities, for inclusion criteria:
 * keep when p ≥ (1 + min_confidence) / 2, drop when p ≤ (1 − exclude_min_confidence) / 2.
 * Exclusion criteria have no measured counterpart.
 */
export const fromEvals = (pair: Pair) => ({ keep_min: round2((1 + pair.include) / 2), include_fail_max: round2((1 - pair.exclude) / 2) });

export function validateScreening(s: ScreeningIO): string[] {
  const values = [s.keep_min, s.include_fail_max, s.exclude_hit_min, s.exclude_clear_max];
  if (values.some((v) => !Number.isFinite(v) || v < 0 || v > 1)) return ["Every threshold is a probability from 0 to 1."];
  const errors: string[] = [];
  if (s.include_fail_max >= s.keep_min) errors.push("Inclusion criteria: “Drop at or below” must be lower than “Keep from”.");
  if (s.exclude_clear_max >= s.exclude_hit_min) errors.push("Exclusion criteria: “Clear at or below” must be lower than “Drop from”.");
  return errors;
}

/** Widths (percent, 5% steps) of the low band [0, low], the middle and the high band [high, 1]. */
export function bands(low: number, high: number) {
  const lowPct = Math.min(100, Math.max(0, round5(low * 100)));
  const highPct = Math.min(100 - lowPct, Math.max(0, 100 - round5(high * 100)));
  return { low: lowPct, middle: 100 - lowPct - highPct, high: highPct };
}

/** Inline widths are forbidden by the CSP, so widths are classes (.w-0 … .w-100). */
export const widthClass = (percent: number) => `w-${percent}`;
