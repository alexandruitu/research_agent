import type { AuthorOut } from "../../api/types";

type Person = Pick<AuthorOut, "name" | "orcid" | "openalex_id">;

/** Rows show this many authors, then "et al.". */
export const SHOWN_AUTHORS = 3;
export const NAME_MATCH_NOTE = "name match — may include other people with this name";

export const orcidUrl = (orcid: string) => `https://orcid.org/${encodeURIComponent(orcid)}`;
export const openalexUrl = (id: string) => `https://openalex.org/${encodeURIComponent(id)}`;
/** An author is identified only by an identifier (ORCID or OpenAlex id), never by a name. */
export const isIdentified = (author: Person) => !!(author.orcid || author.openalex_id);

/** "Ana Popescu, Jon Smith, Third Author et al." — the first three of `count` authors. */
export function authorLine(authors: Person[], count = authors.length): string {
  const shown = authors.slice(0, SHOWN_AUTHORS).map((a) => a.name);
  if (shown.length === 0) return "";
  return shown.join(", ") + (Math.max(count, authors.length) > shown.length ? " et al." : "");
}

/** How an author is known, in words (never only a colour). */
export function identityWords(author: Person): string {
  if (author.orcid && author.openalex_id) return "ORCID · OpenAlex";
  if (author.orcid) return "ORCID";
  if (author.openalex_id) return "OpenAlex";
  return "name only";
}
