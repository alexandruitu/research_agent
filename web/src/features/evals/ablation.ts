import type { Rate } from "./metrics";
import { list, num, obj, str, strings, toRate, type Json } from "./words";

export type SizeRow = { size: number; subsets: number; verdictChanged: number | null; redFlagsMissed: number | null; scoreDelta: number | null; costCalls: number | null; costChars: number | null };
export type SubsetRow = { subset: string; reviewers: string[]; size: number; verdictChanged: Rate | null; editorChanged: Rate | null; redFlagsMissed: Rate | null; scoreDelta: number | null; calls: number | null; chars: number | null };
export type AblationView = {
  papers: number; reviewers: string[]; rerunEditor: boolean; sizes: SizeRow[]; subsets: SubsetRow[];
  summary: { fromSize: number; toSize: number; verdictChanged: number | null; redFlagsAdded: number | null; costIncrease: number | null; sentence: string | null } | null;
  editorVsMajority: Rate | null;
};

export function parseAblation(metrics: Json): AblationView {
  const a = obj(metrics.ablation) ?? {};
  const summary = obj(a.summary);
  return {
    papers: num(a.papers) ?? 0, reviewers: strings(a.reviewers), rerunEditor: a.rerun_editor === true,
    sizes: Object.entries(obj(a.sizes) ?? {})
      .map(([size, v]) => {
        const o = obj(v) ?? {};
        return { size: Number(size), subsets: num(o.subsets) ?? 0, verdictChanged: num(o.verdict_changed), redFlagsMissed: num(o.red_flags_missed), scoreDelta: num(o.mean_abs_score_delta), costCalls: num(o.cost_calls), costChars: num(o.cost_chars) };
      })
      .filter((s) => Number.isFinite(s.size))
      .sort((x, y) => x.size - y.size),
    subsets: list(a.subsets).flatMap((raw) => {
      const r = obj(raw);
      if (!r) return [];
      const cost = obj(r.cost);
      return [{ subset: str(r.subset), reviewers: strings(r.reviewers), size: num(r.size) ?? 0, verdictChanged: toRate(r.verdict_changed), editorChanged: toRate(r.editor_verdict_changed), redFlagsMissed: toRate(r.red_flags_missed), scoreDelta: num(r.mean_abs_score_delta), calls: num(cost?.calls), chars: num(cost?.chars) }];
    }),
    summary: summary ? { fromSize: num(summary.from_size) ?? 0, toSize: num(summary.to_size) ?? 0, verdictChanged: num(summary.verdict_changed), redFlagsAdded: num(summary.red_flags_added), costIncrease: num(summary.cost_increase), sentence: str(summary.sentence) || null } : null,
    editorVsMajority: toRate(a.full_editor_vs_majority),
  };
}
