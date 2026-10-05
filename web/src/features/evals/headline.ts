import type { EvalSummaryOut } from "../../api/types";
import { fixed, kappaWords, kindOf, pct } from "./words";

const ratio = (r: { k: number; n: number } | null | undefined) => (r ? `${r.k} of ${r.n}` : "n/a");

/** Two or three headline numbers of a report, each as a short phrase (never a bare number). */
export function headlinePhrases(report: EvalSummaryOut): string[] {
  const h = report.headline;
  switch (kindOf(report.kind)) {
    case "screening":
      return [
        `search recall ${ratio(h.retrieval_recall)}`,
        `cascade recall ${ratio(h.cascade_recall)}`,
        h.kappa !== null ? `reviewer kappa ${fixed(h.kappa)} (${kappaWords(h.kappa)})` : "reviewer agreement not measured",
      ];
    case "panel":
      return [
        h.fleiss_kappa != null ? `Fleiss kappa ${fixed(h.fleiss_kappa)}: ${kappaWords(h.fleiss_kappa)} agreement` : "verdict kappa not defined",
        `verdict agreement ${pct(h.raw_agreement)} on ${h.papers ?? "?"} papers`,
        h.sr_auc != null ? `SR inclusion AUC ${fixed(h.sr_auc)}` : "no SR labels",
      ];
    case "ablation":
      return h.summary
        ? [h.summary]
        : [`verdict changed ${pct(h.verdict_changed)}`, `red flags added ${fixed(h.red_flags_added, 1)}`, `cost +${pct(h.cost_increase)}`];
    case "human":
      return [
        `${pct(h.human_accuracy)} of answers match the human consensus`,
        h.human_kappa != null ? `kappa ${fixed(h.human_kappa)} (${kappaWords(h.human_kappa)})` : "kappa not defined",
        `${h.human_raters ?? 0} raters · Spearman ${fixed(h.spearman)}`,
      ];
  }
}

export const reportTitle = (report: Pick<EvalSummaryOut, "gold_set">) => report.gold_set?.name ?? "from a run";
