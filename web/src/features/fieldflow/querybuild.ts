/**
 * Per-source queries from keyword groups, a line-for-line port of `research_agent.querybuild` so the editor
 * can show the query live. Display only: the server builds the query again on save and preview.
 */
export const QUERY_SOURCES = ["europepmc", "openalex", "arxiv"] as const;
export type QuerySource = (typeof QUERY_SOURCES)[number];
export type Keywords = { all: string[]; any: string[]; none: string[] };

const ARXIV_CATEGORIES = ["cs.CV", "eess.IV", "physics.med-ph"];
export const MAX_QUERY = 2000;
const SYNTAX = /["()[\]{}:\\^~,;<>|&!?=+/]/g;
const BARE = /^[\p{L}\p{N}_]+\*?$/u;
const OPERATORS = new Set(["AND", "OR", "NOT", "ANDNOT", "TO"]);
const WILDCARDS = new Set<QuerySource>(["europepmc"]);
const PREFIX: Record<QuerySource, string> = { europepmc: "TITLE_ABS:", openalex: "", arxiv: "abs:" };
// eslint-disable-next-line no-control-regex
const CONTROL = /[\x00-\x1f\x7f]/;

export class QueryError extends Error {}

const words = (text: string) => text.split(/\s+/).filter(Boolean);

export function cleanTerm(term: string, wildcard = false): string {
  let text = term.normalize("NFKC").replace(SYNTAX, " ");
  const star = text.trimEnd().endsWith("*");
  text = words(text.replace(/\*/g, " ")).join(" ");
  if (text && wildcard && star && !text.includes(" ")) text += "*";
  return text;
}

function unique(terms: string[] | undefined, wildcard: boolean): string[] {
  const seen = new Set<string>();
  const out: string[] = [];
  for (const term of terms ?? []) {
    const cleaned = cleanTerm(term, wildcard);
    if (cleaned && !seen.has(cleaned.toLowerCase())) {
      seen.add(cleaned.toLowerCase());
      out.push(cleaned);
    }
  }
  return out;
}

export const hasTerms = (keywords: Keywords | null | undefined) =>
  !!keywords && (unique(keywords.all, false).length > 0 || unique(keywords.any, false).length > 0);

const phrase = (term: string) => (BARE.test(term) && !OPERATORS.has(term.replace(/\*+$/, "").toUpperCase()) ? term : `"${term}"`);

function group(terms: string[], prefix: string): string {
  const parts = terms.map((t) => `${prefix}${phrase(t)}`);
  return parts.length === 1 ? parts[0]! : `(${parts.join(" OR ")})`;
}

export function buildQuery(source: QuerySource, keywords: Keywords): string {
  const wildcard = WILDCARDS.has(source);
  const prefix = PREFIX[source];
  const all = unique(keywords.all, wildcard);
  const any = unique(keywords.any, wildcard);
  const none = unique(keywords.none, wildcard);
  if (all.length === 0 && any.length === 0) throw new QueryError("Add at least one keyword to 'All of' or 'Any of'");
  const parts = all.map((t) => `${prefix}${phrase(t)}`);
  if (any.length) parts.push(group(any, prefix));
  if (source === "arxiv") parts.push(`(${ARXIV_CATEGORIES.map((c) => `cat:${c}`).join(" OR ")})`);
  let query = parts.join(" AND ");
  if (none.length) query += (source === "arxiv" ? " ANDNOT " : " NOT ") + group(none, prefix);
  if (query.length > MAX_QUERY) throw new QueryError(`The ${source} query is too long (over ${MAX_QUERY} characters); use fewer keywords`);
  return query;
}

export function checkOverride(source: QuerySource, text: string | null | undefined): string {
  const value = (text ?? "").trim();
  if (CONTROL.test(value)) throw new QueryError(`The ${source} query must be a single line`);
  if (value.length > MAX_QUERY) throw new QueryError(`The ${source} query is too long (over ${MAX_QUERY} characters)`);
  if (source === "openalex" && value.includes(",")) throw new QueryError("The OpenAlex query cannot contain a comma");
  return value;
}

export type SourceQuery = { source: QuerySource; query: string | null; overridden: boolean; error: string | null };

/** What each chosen source would search: its override, else the built query, else planned by the model (null). */
export function draftQueries(keywords: Keywords, sources: string[], overrides: Partial<Record<QuerySource, string>>): SourceQuery[] {
  return QUERY_SOURCES.filter((s) => sources.includes(s)).map((source) => {
    try {
      const override = checkOverride(source, overrides[source]);
      if (override) return { source, query: override, overridden: true, error: null };
      if (!hasTerms(keywords)) return { source, query: null, overridden: false, error: null };
      return { source, query: buildQuery(source, keywords), overridden: false, error: null };
    } catch (error) {
      return { source, query: null, overridden: false, error: error instanceof Error ? error.message : String(error) };
    }
  });
}
