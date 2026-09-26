export type Rate = { k: number; n: number; value: number | null; ci: [number, number] | null; reason: string | null };
export type Pair = { include: number; exclude: number };
export type SweepRow = { pair: Pair; recall: Rate | null; missed: number; lost: number; lostIds: string[]; callsSaved: number; escalated: number };
export type Strategy = { name: "llm_only" | "jev_only" | "cascade"; recall: Rate | null; callsSaved: number; escalated: number; kept: number; keptNegatives: number };
export type EvalView = {
  gold: { name: string; citation: string };
  screened: number | null;
  retrievalRecall: Rate | null;
  defaultPair: Pair | null;
  strategies: Strategy[];
  sweep: SweepRow[];
  holdout: { gold: string; n: number; recall: Rate | null; pair: Pair | null; callsSaved: number | null } | null;
  holdoutSweep: { gold: string; n: number; rows: SweepRow[] } | null;
  recommended: Pair | null;
  rejected: { pair: Pair; lost: { id: string; title: string }[] } | null;
  agreement: { n: number; kappa: number | null; agreement: number | null; reason: string | null; sameFamily: boolean | null; adjudicated: Rate | null } | null;
  warnings: string[];
};

type Json = Record<string, unknown>;
const obj = (value: unknown): Json | null => (value && typeof value === "object" && !Array.isArray(value) ? (value as Json) : null);
const num = (value: unknown): number | null => (typeof value === "number" && Number.isFinite(value) ? value : null);
const str = (value: unknown, fallback = ""): string => (typeof value === "string" ? value : fallback);

export function toRate(value: unknown): Rate | null {
  const r = obj(value);
  if (!r || num(r.k) === null || num(r.n) === null) return null;
  const ci = Array.isArray(r.ci) && r.ci.length === 2 && r.ci.every((x) => num(x) !== null) ? ([r.ci[0], r.ci[1]] as [number, number]) : null;
  return { k: r.k as number, n: r.n as number, value: num(r.value), ci, reason: typeof r.reason === "string" ? r.reason : null };
}

const toPair = (value: unknown): Pair | null => {
  const p = obj(value);
  const include = num(p?.min_confidence);
  const exclude = num(p?.exclude_min_confidence);
  return include === null || exclude === null ? null : { include, exclude };
};

function toRows(value: unknown): SweepRow[] {
  if (!Array.isArray(value)) return [];
  return value.flatMap((item) => {
    const row = obj(item);
    const pair = toPair(row);
    if (!row || !pair) return [];
    return [{
      pair, recall: toRate(row.recall), missed: num(row.missed) ?? 0, lost: num(row.lost_vs_llm) ?? 0,
      lostIds: Array.isArray(row.lost_ids) ? row.lost_ids.filter((x): x is string => typeof x === "string") : [],
      callsSaved: num(row.calls_saved) ?? 0, escalated: num(row.escalated) ?? 0,
    }];
  });
}

export function parseEval(metrics: Json): EvalView {
  const gold = obj(metrics.gold);
  const strategies = obj(metrics.strategies) ?? {};
  const holdout = obj(metrics.holdout);
  const holdoutSweep = obj(metrics.holdout_sweep);
  const rejected = obj(metrics.rejected_on_holdout);
  const agreement = obj(metrics.agreement);
  const verdict = obj(agreement?.verdict);
  return {
    gold: { name: str(gold?.name, "unknown"), citation: str(gold?.citation) },
    screened: num(obj(metrics.counts)?.screened),
    retrievalRecall: toRate(metrics.retrieval_recall),
    defaultPair: toPair(metrics.default_thresholds),
    strategies: (["llm_only", "jev_only", "cascade"] as const).flatMap((name) => {
      const s = obj(strategies[name]);
      return s ? [{ name, recall: toRate(s.recall), callsSaved: num(s.calls_saved) ?? 0, escalated: num(s.escalated) ?? 0, kept: num(s.kept) ?? 0, keptNegatives: num(s.kept_negatives) ?? 0 }] : [];
    }),
    sweep: toRows(metrics.sweep),
    holdout: holdout ? { gold: str(holdout.gold), n: num(holdout.n) ?? 0, recall: toRate(holdout.recall), pair: toPair(holdout.thresholds), callsSaved: num(holdout.calls_saved) } : null,
    holdoutSweep: holdoutSweep ? { gold: str(holdoutSweep.gold), n: num(holdoutSweep.n) ?? 0, rows: toRows(holdoutSweep.rows) } : null,
    recommended: toPair(metrics.recommended),
    rejected: rejected && toPair(rejected.thresholds)
      ? {
          pair: toPair(rejected.thresholds)!,
          lost: Array.isArray(rejected.lost) ? rejected.lost.flatMap((m) => { const o = obj(m); return o ? [{ id: str(o.id), title: str(o.title) }] : []; }) : [],
        }
      : null,
    agreement: agreement
      ? { n: num(agreement.n) ?? 0, kappa: num(verdict?.kappa), agreement: num(verdict?.agreement), reason: typeof verdict?.reason === "string" ? verdict.reason : null, sameFamily: typeof agreement.same_family === "boolean" ? agreement.same_family : null, adjudicated: toRate(agreement.adjudication_rate) }
      : null,
    warnings: Array.isArray(metrics.warnings) ? metrics.warnings.filter((w): w is string => typeof w === "string") : [],
  };
}

export function formatRate(rate: Rate | null): string {
  if (!rate) return "n/a";
  if (rate.value === null || !rate.ci) return `n/a (${rate.reason ?? "undefined"})`;
  return `${rate.k}/${rate.n} (95% CI ${rate.ci[0].toFixed(2)}–${rate.ci[1].toFixed(2)})`;
}

export const rowFor = (rows: SweepRow[], pair: Pair): SweepRow | undefined =>
  rows.find((row) => row.pair.include === pair.include && row.pair.exclude === pair.exclude);

export const samePair = (a: Pair | null, b: Pair | null) => !!a && !!b && a.include === b.include && a.exclude === b.exclude;
