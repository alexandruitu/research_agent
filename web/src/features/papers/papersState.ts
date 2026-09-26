import type { PaperParams } from "../../api/hooks";

export const PAGE_SIZE = 25;
const MAX_PAGE = 100_000; // the API refuses larger pages
const SORT = /^(title|year|score|criterion:[a-z0-9_]+)$/;
const DECISIONS = ["include", "exclude", "uncertain"];
const TIERS = ["jev", "llm", "rule"];

export type PapersView = { runId: string | null; paperId: string | null; stageId: string | null; params: PaperParams };

const number = (text: string | null, low: number, high: number) => {
  if (text === null || text === "") return undefined;
  const value = Number(text);
  return Number.isFinite(value) && value >= low && value <= high ? value : undefined;
};
const flag = (text: string | null) => (text === "true" ? true : text === "false" ? false : undefined);

export function parseView(search: URLSearchParams): PapersView {
  const sort = search.get("sort") ?? "title";
  const params: PaperParams = {
    page: Math.trunc(number(search.get("page"), 1, MAX_PAGE) ?? 1),
    page_size: PAGE_SIZE,
    sort: SORT.test(sort) ? sort : "title",
    direction: search.get("dir") === "desc" ? "desc" : "asc",
  };
  const decision = search.get("decision");
  if (decision && DECISIONS.includes(decision)) params.decision = decision;
  const tier = search.get("tier");
  if (tier && TIERS.includes(tier)) params.tier = tier;
  const escalated = flag(search.get("escalated"));
  if (escalated !== undefined) params.escalated = escalated;
  const inSr = flag(search.get("in_sr"));
  if (inSr !== undefined) params.in_sr = inSr;
  let pMin = number(search.get("pmin"), 0, 1);
  let pMax = number(search.get("pmax"), 0, 1);
  if (pMin !== undefined && pMax !== undefined && pMin > pMax) pMin = pMax = undefined; // an inverted range is a 422
  if (pMin !== undefined || pMax !== undefined) params.criterion = "topic_match";
  if (pMin !== undefined) params.p_min = pMin;
  if (pMax !== undefined) params.p_max = pMax;
  return { runId: search.get("run"), paperId: search.get("paper"), stageId: search.get("stage"), params };
}

type Changes = Partial<{
  run: string | null; page: number | null; sort: string | null; dir: "asc" | "desc" | null; decision: string | null; tier: string | null;
  escalated: boolean | null; in_sr: boolean | null; pmin: number | null; pmax: number | null; paper: string | null; stage: string | null;
}>;

/** Returns new search parameters. Any change other than `page`, `paper` or `stage` goes back to page 1; changing the run closes the panels. */
export function patchView(search: URLSearchParams, changes: Changes, resetPage = true): URLSearchParams {
  const next = new URLSearchParams(search);
  for (const [key, value] of Object.entries(changes)) {
    if (value === null || value === undefined) next.delete(key);
    else next.set(key, String(value));
  }
  if (changes.paper) next.delete("stage");
  if (changes.stage) next.delete("paper");
  if (changes.run !== undefined) {
    next.delete("paper");
    next.delete("stage");
  }
  if (resetPage && changes.page === undefined) next.delete("page");
  return next;
}
