import type { Rate } from "./metrics";
import { list, num, obj, scoreOf, str, strings, toRate, type Json } from "./words";

export type Reviewer = { key: string; name: string; model: string | null };
export type ItemRow = { text: string; source: string | null; reviewers: string[]; share: Rate | null; kappa: number | null; reason: string | null; unanswered: number | null; reword: boolean; answers: Record<string, number> };
export type CoverageRow = { reviewer: string; item: string; text: string; fulltext: Rate | null; abstract: Rate | null };
export type DispersionRow = { paperId: string; title: string; score: number | null; range: number | null; sd: number | null; scores: { name: string; score: number | null }[] };
export type HumanView = {
  raters: number; units: number; papers: number; stale: number;
  interRater: Rate | null; interRaterKappa: number | null; interRaterReason: string | null;
  panelAccuracy: Rate | null; panelKappa: number | null;
  perReviewer: { key: string; name: string; accuracy: Rate | null; kappa: number | null }[];
  perItem: { reviewer: string; text: string; n: number; accuracy: Rate | null; kappa: number | null }[];
  spearman: { rho: number | null; n: number; reason: string | null } | null;
};
export type PanelView = {
  n: number; reviewers: Reviewer[]; textSources: { source: string; count: number }[];
  fleiss: { kappa: number | null; agreement: number | null; prevalence: number | null; raters: number; reason: string | null } | null;
  verdictReason: string | null;
  pairwise: { a: string; b: string; kappa: number | null; agreement: number | null; prevalence: number | null }[];
  editor: Rate | null; items: ItemRow[]; coverage: CoverageRow[]; dispersion: DispersionRow[];
  auc: { value: number | null; ci: [number, number] | null; nPos: number; nNeg: number; note: string; reason: string | null } | null;
  families: { single: boolean; provider: string | null; providers: Record<string, string>; byFamily: { provider: string; kappa: number | null; reviewers: string[] }[] } | null;
  human: HumanView | null;
};

export function parsePanel(metrics: Json): PanelView {
  const panel = obj(metrics.panel) ?? {};
  const config = obj(metrics.config) ?? {};
  const fromConfig = new Map(list(config.panel).flatMap((p) => { const o = obj(p); return o ? [[str(o.key), o] as const] : []; }));
  const keys = strings(panel.reviewers);
  const reviewers: Reviewer[] = (keys.length ? keys : [...fromConfig.keys()]).map((key) => ({ key, name: str(fromConfig.get(key)?.name, key), model: str(fromConfig.get(key)?.model) || null }));
  const nameOf = (key: string) => reviewers.find((r) => r.key === key)?.name ?? key;
  const verdicts = obj(panel.verdicts);
  const fleiss = obj(verdicts?.fleiss);
  const items: ItemRow[] = list(panel.items).flatMap((raw) => {
    const r = obj(raw);
    if (!r) return [];
    const answers = obj(r.answers) ?? {};
    return [{
      text: str(r.text), source: str(r.source) || null,
      reviewers: list(r.items).map((i) => nameOf(str(obj(i)?.reviewer))),
      share: toRate(r.share), kappa: scoreOf(r.kappa), reason: str(r.reason) || null,
      unanswered: num(r.unanswered_share), reword: r.reword_candidate === true,
      answers: Object.fromEntries(Object.entries(answers).filter(([, v]) => num(v) !== null)) as Record<string, number>,
    }];
  });
  const itemText = new Map<string, string>();
  list(panel.items).forEach((raw) => list(obj(raw)?.items).forEach((i) => { const o = obj(i); if (o) itemText.set(`${str(o.reviewer)}|${str(o.item)}`, str(obj(raw)?.text)); }));
  const coverage: CoverageRow[] = Object.entries(obj(panel.coverage) ?? {}).flatMap(([reviewer, perItem]) =>
    Object.entries(obj(perItem) ?? {}).map(([item, split]) => ({
      reviewer: nameOf(reviewer), item, text: itemText.get(`${reviewer}|${item}`) ?? item,
      fulltext: toRate(obj(split)?.fulltext), abstract: toRate(obj(split)?.abstract),
    })),
  );
  const auc = obj(panel.sr_inclusion_auc);
  const families = obj(panel.model_families);
  const ci = list(auc?.ci);
  const human = obj(metrics.human);
  return {
    n: num(panel.n) ?? 0, reviewers,
    textSources: Object.entries(obj(panel.text_sources) ?? {}).map(([source, count]) => ({ source, count: num(count) ?? 0 })),
    fleiss: fleiss ? { kappa: num(fleiss.kappa), agreement: num(fleiss.agreement), prevalence: num(fleiss.prevalence), raters: num(fleiss.raters) ?? reviewers.length, reason: str(fleiss.reason) || null } : null,
    verdictReason: str(verdicts?.reason) || null,
    pairwise: Object.entries(obj(verdicts?.pairwise) ?? {}).map(([pair, c]) => {
      const [a = "", b = ""] = pair.split("|");
      const o = obj(c);
      return { a: nameOf(a), b: nameOf(b), kappa: num(o?.kappa), agreement: num(o?.agreement), prevalence: num(o?.prevalence) };
    }),
    editor: toRate(panel.editor_vs_majority), items, coverage,
    dispersion: list(panel.dispersion).flatMap((raw) => {
      const r = obj(raw);
      return r ? [{ paperId: str(r.paper_id), title: str(r.title), score: num(r.score), range: num(r.range), sd: num(r.sd), scores: Object.entries(obj(r.scores) ?? {}).map(([k, v]) => ({ name: nameOf(k), score: num(v) })) }] : [];
    }),
    auc: auc ? { value: num(auc.value), ci: ci.length === 2 && num(ci[0]) !== null && num(ci[1]) !== null ? [ci[0] as number, ci[1] as number] : null, nPos: num(auc.n_pos) ?? 0, nNeg: num(auc.n_neg) ?? 0, note: str(auc.note), reason: str(auc.reason) || null } : null,
    families: families
      ? {
          single: families.single_family === true,
          provider: str(obj(families.families)?.single) || null,
          providers: Object.fromEntries(Object.entries(obj(families.providers) ?? {}).map(([k, v]) => [nameOf(k), str(v)])),
          byFamily: families.single_family === true ? [] : Object.entries(obj(families.families) ?? {}).map(([provider, f]) => ({ provider, kappa: scoreOf(obj(f)?.fleiss), reviewers: strings(obj(f)?.reviewers).map(nameOf) })),
        }
      : null,
    human: human ? parseHuman(human, nameOf) : null,
  };
}

function parseHuman(h: Json, nameOf: (key: string) => string): HumanView {
  const inter = obj(h.inter_rater);
  const panel = obj(h.panel);
  const spearman = obj(obj(h.scores)?.spearman);
  return {
    raters: list(h.raters).length || (num(h.raters) ?? 0), units: num(h.units) ?? 0, papers: num(h.papers) ?? 0, stale: num(h.stale_or_unknown) ?? 0,
    interRater: toRate(inter?.share), interRaterKappa: scoreOf(inter?.fleiss), interRaterReason: str(inter?.reason) || null,
    panelAccuracy: toRate(panel?.accuracy), panelKappa: scoreOf(panel?.kappa),
    perReviewer: Object.entries(obj(h.per_reviewer) ?? {}).map(([key, v]) => ({ key, name: nameOf(key), accuracy: toRate(obj(v)?.accuracy), kappa: scoreOf(obj(v)?.kappa) })),
    perItem: list(h.per_item).flatMap((raw) => {
      const r = obj(raw);
      return r ? [{ reviewer: nameOf(str(r.reviewer)), text: str(r.text, str(r.item)), n: num(r.n) ?? 0, accuracy: toRate(r.accuracy), kappa: scoreOf(r.kappa) }] : [];
    }),
    spearman: spearman ? { rho: num(spearman.rho), n: num(spearman.n) ?? 0, reason: str(spearman.reason) || null } : null,
  };
}
