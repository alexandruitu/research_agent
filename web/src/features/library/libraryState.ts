import type { LibraryParams } from "../../api/hooks";
import { LIBRARY_STATUSES } from "../../components/ui/StatusMark";

export const LIBRARY_PAGE_SIZE = 25;
const SORTS = ["added_at", "title", "year", "score", "status"];
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export type LibraryView = { itemId: string | null; params: LibraryParams };

/** The URL is the view: every filter, the sort, the page and the open item. Invalid values are dropped. */
export function parseLibraryView(search: URLSearchParams): LibraryView {
  const params: LibraryParams = {
    sort: SORTS.includes(search.get("sort") ?? "") ? search.get("sort")! : "added_at",
    direction: search.get("dir") === "asc" ? "asc" : "desc",
    page: Math.max(1, Math.min(100_000, Math.trunc(Number(search.get("page")) || 1))),
    page_size: LIBRARY_PAGE_SIZE,
  };
  const q = search.get("q")?.trim();
  if (q) params.q = q.slice(0, 200);
  const collection = search.get("collection");
  if (collection && UUID.test(collection)) params.collection_id = collection;
  const status = search.get("status");
  if (status && (LIBRARY_STATUSES as readonly string[]).includes(status)) params.status = status;
  const tag = search.get("tag")?.trim().toLowerCase();
  if (tag) params.tag = tag.slice(0, 50);
  const field = search.get("field");
  if (field && UUID.test(field)) params.field_id = field;
  const min = Number(search.get("min"));
  if (search.get("min") && Number.isFinite(min) && min >= 0 && min <= 100) params.min_score = min;
  if (search.get("flags") === "true") params.has_red_flags = true;
  const item = search.get("item");
  return { itemId: item && UUID.test(item) ? item : null, params };
}

export type LibraryChange = Partial<Record<"q" | "collection" | "status" | "tag" | "field" | "min" | "flags" | "sort" | "dir" | "page" | "item", string | number | boolean | null>>;

/** New search params; any filter change goes back to page 1 and keeps the open item. */
export function patchLibraryView(search: URLSearchParams, changes: LibraryChange): URLSearchParams {
  const next = new URLSearchParams(search);
  for (const [key, value] of Object.entries(changes)) {
    if (value === null || value === undefined || value === "" || value === false) next.delete(key);
    else next.set(key, String(value));
  }
  if (changes.page === undefined && changes.item === undefined) next.delete("page");
  return next;
}

export const FILTER_KEYS = ["q", "collection", "status", "tag", "field", "min", "flags"] as const;

export const clearFilters = (search: URLSearchParams) => patchLibraryView(search, Object.fromEntries(FILTER_KEYS.map((k) => [k, null])));
