import type { DrawerOut, PaperRow } from "../../api/types";
import { criterionLabel } from "../fields/labels";

type Screen = PaperRow["screen"];
export type CriterionState = "met" | "not_met" | "unclear";
export type CriterionLine = { key: string; kind: "include" | "exclude"; state: CriterionState; jevP: number | null; llm: string | null; quote: string | null; decided: boolean };

const kindOf = (key: string, kind?: string): "include" | "exclude" => (kind === "exclude" || (!kind && /^e\d+$/.test(key)) ? "exclude" : "include");

/**
 * Whether the paper passes each criterion: an inclusion criterion passes when it holds, an exclusion
 * criterion when it does not. The LLM's answer wins over Jev's probability (it decided when present).
 */
export function criterionLines(screen: Screen): CriterionLine[] {
  const keys = [...new Set([...Object.keys(screen.criteria), ...Object.keys(screen.cells ?? {})])];
  return keys.map((key) => {
    const cell = screen.cells?.[key];
    const kind = kindOf(key, cell?.kind);
    const jevP = cell?.jev_p ?? screen.criteria[key] ?? null;
    const llm = cell?.llm ?? null;
    const holds = llm === "yes" ? true : llm === "no" ? false : llm === "unclear" ? null : jevP === null ? null : jevP >= 0.5;
    const state: CriterionState = holds === null ? "unclear" : holds === (kind === "include") ? "met" : "not_met";
    return { key, kind, state, jevP, llm, quote: cell?.quote ?? null, decided: screen.decided_by === key };
  });
}

/** The compact criteria line: "✓ 4/4 met", "✕ dropped by incl 2", "? 2 unclear", "not screened". */
export function criteriaSummary(screen: Screen): { icon: string; text: string } {
  if (screen.tier === "rule") return { icon: "–", text: "not screened" };
  const lines = criterionLines(screen);
  if (screen.decision === "exclude") {
    return { icon: "✕", text: screen.decided_by ? `dropped by ${criterionLabel(screen.decided_by)}` : "dropped" };
  }
  if (lines.length === 0) return { icon: "–", text: "no criteria" };
  const unclear = lines.filter((l) => l.state === "unclear").length;
  if (unclear > 0) return { icon: "?", text: `${unclear} unclear` };
  const met = lines.filter((l) => l.state === "met").length;
  return { icon: met === lines.length ? "✓" : "◐", text: `${met}/${lines.length} met` };
}

const clip = (text: string, max: number) => (text.length > max ? `${text.slice(0, max - 1).trimEnd()}…` : text);
const plural = (n: number, word: string) => `${n} ${word}${n === 1 ? "" : "s"}`;

export type WhyContext = {
  /** Criterion key → its text, from the run's field version (falls back to "incl 2"). */
  texts?: Record<string, string>;
  /** The panel's red flag texts (the drawer has them; table rows only carry the count). */
  redFlags?: string[];
  /** Longest quote kept in the sentence; the drawer passes Infinity. */
  maxQuote?: number;
};

function droppedPart(screen: Screen, ctx: WhyContext): string {
  const lines = criterionLines(screen);
  // legacy runs have one criterion (topic match) and no decided_by: that criterion decided
  const key = screen.decided_by ?? (lines.length === 1 ? lines[0]!.key : null);
  if (!key) return "Dropped by screening; no single criterion decided";
  const line = lines.find((l) => l.key === key);
  const text = ctx.texts?.[key];
  const name = text ? `‘${text.replace(/\.$/, "")}’` : criterionLabel(key);
  const what = line?.kind === "exclude" ? `matches the exclusion ${name}` : `doesn't meet ${name}`;
  const by: string[] = [];
  if (screen.tier === "llm" || line?.llm) by.push("LLM");
  else if (line?.jevP != null) by.push(`Jev, p ${line.jevP.toFixed(2)}`);
  if (line?.quote) by.push(`quote: “${clip(line.quote, ctx.maxQuote ?? 140)}”`);
  return `Dropped: ${what}${by.length ? ` (${by.join(", ")})` : ""}`;
}

function panelParts(row: PaperRow, ctx: WhyContext): string[] {
  const parts: string[] = [];
  const flags = row.red_flag_count;
  if (flags != null) {
    if (flags === 0) parts.push("panel found no red flags");
    else {
      const names = (ctx.redFlags ?? []).map((t) => t.replace(/\.$/, "").toLowerCase());
      parts.push(`panel found ${plural(flags, "red flag")}${names.length ? ` (${names.join("; ")})` : ""}`);
    }
  } else if (row.reviews && !("missing" in row.reviews)) {
    const verdict = row.reviews.adjudicated ? row.reviews.adjudicator : row.reviews.a === row.reviews.b ? row.reviews.a : null;
    parts.push(verdict ? `reviewers say ${verdict}` : "reviewers disagree");
  }
  if (row.provisional) {
    parts.push(row.checklist_answered != null && row.checklist_total != null
      ? `score provisional (${row.checklist_answered} of ${row.checklist_total} checklist items answered)`
      : "score provisional (under half of the checklist answered)");
  }
  if (row.text_source) parts.push(row.text_source === "abstract" ? "abstract only" : "full text read");
  return parts;
}

/**
 * Why the paper is where it is, in one plain sentence: the screening outcome first, then what the review
 * panel found and what text it read. Used by the Simple view and as the drawer's first line.
 */
export function whySentence(row: PaperRow, ctx: WhyContext = {}): string {
  const { screen } = row;
  let head: string;
  if (screen.tier === "rule") head = "Not screened: no abstract was available";
  else if (screen.decision === "exclude") return `${droppedPart(screen, ctx)}.`;
  else if (screen.decision === "uncertain") head = "Unsure: screening could not decide, check it by hand";
  else {
    const lines = criterionLines(screen);
    const met = lines.filter((l) => l.state === "met").length;
    const unclear = lines.filter((l) => l.state === "unclear").length;
    head = lines.length === 0 ? "Kept"
      : met === lines.length ? `Kept: meets ${lines.length === 1 ? "the criterion" : `all ${lines.length} criteria`}`
        : `Kept: meets ${met} of ${lines.length} criteria${unclear ? ` (${unclear} unclear)` : ""}`;
  }
  const rest = panelParts(row, ctx);
  return `${head}${rest.length ? `; ${rest.join("; ")}` : ""}.`;
}

/** The drawer's data as a table row, so the drawer's why sentence comes from the same function. */
export function drawerAsRow(drawer: DrawerOut): PaperRow {
  const { screening, panel } = drawer;
  const table = screening.criteria_table ?? [];
  const byRole = Object.fromEntries(drawer.reviews.map((r) => [r.role, r.verdict]));
  return {
    paper: { id: drawer.paper.id, source_id: drawer.paper.source_id, title: drawer.paper.title, year: drawer.paper.year, doi: drawer.paper.doi },
    found_by: drawer.found_by, sources: drawer.sources ?? [], in_sr: drawer.in_sr,
    screen: {
      tier: screening.tier, decision: screening.decision, jev_decision: screening.jev_decision, llm_decision: screening.llm_decision,
      criteria: Object.fromEntries(screening.criteria.map((c) => [c.key, c.probability])),
      decided_by: screening.decided_by ?? table.find((r) => r.decided)?.key ?? null,
      cells: Object.fromEntries(table.map((r) => [r.key, { kind: r.kind, jev_p: r.jev_p, llm: r.llm, quote: r.quote }])),
    },
    extract: null,
    reviews: drawer.reviews.length ? { a: byRole.a ?? null, b: byRole.b ?? null, adjudicated: "adjudicator" in byRole, adjudicator: byRole.adjudicator ?? null } : null,
    rank: drawer.rank,
    score: panel?.score ?? null, coverage: panel?.coverage ?? null, red_flag_count: panel ? panel.red_flag_count : null,
    text_source: panel?.text_source ?? null, provisional: panel?.coverage != null ? panel.coverage < 0.5 : null,
  };
}

/** The drawer's first line: the same sentence, with full quotes, criterion texts and red flag names. */
export const drawerWhy = (drawer: DrawerOut) =>
  whySentence(drawerAsRow(drawer), {
    texts: Object.fromEntries((drawer.screening.criteria_table ?? []).map((r) => [r.key, r.text])),
    redFlags: drawer.panel?.red_flags.map((f) => f.text) ?? [],
    maxQuote: Infinity,
  });
