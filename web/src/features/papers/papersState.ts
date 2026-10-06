import type { PaperParams } from "../../api/hooks";
import { SOURCE_NAMES } from "../fields/labels";
import { GROUP_BY_OPTIONS, type GroupBy } from "./groups";

export const PAGE_SIZE = 25;
const MAX_PAGE = 100_000; // the API refuses larger pages
const SORT = /^(title|year|score|criterion:[a-z0-9_]+)$/;
const DECISIONS = ["include", "exclude", "uncertain"];
const TIERS = ["jev", "llm", "rule"];
const CRITERION_KEY = /^[a-z0-9_]{1,100}$/;
export const PAPER_SOURCES: string[] = [...SOURCE_NAMES, "demo"];

/** `groupBy` "none" is the flat list (one pager); any other value shows collapsible groups that page on their own. */
export type PapersView = { runId: string | null; paperId: string | null; stageId: string | null; groupBy: GroupBy; params: PaperParams };

const number = (text: string | null, low: number, high: number) => {
  if (text === null || text === "") return undefined;
  const value = Number(text);
  return Number.isFinite(value) && value >= low && value <= high ? value : undefined;
};
const flag = (text: string | null) => (text === "true" ? true : text === "false" ? false : undefined);

export function parseView(search: URLSearchParams): PapersView {
  const group = search.get("group");
  const groupBy: GroupBy = GROUP_BY_OPTIONS.find((o) => o.value === group)?.value ?? "quality";
  // Inside groups the best panel score comes first unless the user picked a sort; the flat list sorts by title.
  const sort = search.get("sort") ?? (groupBy === "none" ? "title" : "score");
  const params: PaperParams = {
    page: Math.trunc(number(search.get("page"), 1, MAX_PAGE) ?? 1),
    page_size: PAGE_SIZE,
    sort: SORT.test(sort) ? sort : "title",
    direction: search.get("dir") === "desc" || (search.get("sort") === null && groupBy !== "none") ? "desc" : "asc",
  };
  const decision = search.get("decision");
  if (decision && DECISIONS.includes(decision)) params.decision = decision;
  const tier = search.get("tier");
  if (tier && TIERS.includes(tier)) params.tier = tier;
  const escalated = flag(search.get("escalated"));
  if (escalated !== undefined) params.escalated = escalated;
  const inSr = flag(search.get("in_sr"));
  if (inSr !== undefined) params.in_sr = inSr;
  const by = search.get("by");
  if (by && CRITERION_KEY.test(by)) params.decided_by = by;
  if (search.get("flags") === "true") params.has_red_flags = true;
  const provisional = flag(search.get("prov"));
  if (provisional !== undefined) params.provisional = provisional;
  const src = search.get("src");
  if (src && PAPER_SOURCES.includes(src)) params.source = src;
  let pMin = number(search.get("pmin"), 0, 1);
  let pMax = number(search.get("pmax"), 0, 1);
  if (pMin !== undefined && pMax !== undefined && pMin > pMax) pMin = pMax = undefined; // an inverted range is a 422
  if (pMin !== undefined || pMax !== undefined) params.criterion = "topic_match";
  if (pMin !== undefined) params.p_min = pMin;
  if (pMax !== undefined) params.p_max = pMax;
  return { runId: search.get("run"), paperId: search.get("paper"), stageId: search.get("stage"), groupBy, params };
}

type Changes = Partial<{
  run: string | null; page: number | null; sort: string | null; dir: "asc" | "desc" | null; decision: string | null; tier: string | null;
  escalated: boolean | null; in_sr: boolean | null; pmin: number | null; pmax: number | null; paper: string | null; stage: string | null;
  by: string | null; src: string | null; flags: boolean | null; prov: boolean | null; group: GroupBy | null;
}>;

/** Returns new search parameters. Any change other than `page`, `paper` or `stage` goes back to page 1; changing the run closes the panels and drops the criterion filter. */
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
    next.delete("by"); // criterion keys belong to a field version
  }
  if (resetPage && changes.page === undefined) next.delete("page");
  return next;
}
