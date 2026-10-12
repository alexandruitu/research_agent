import type { AuthorCandidate, AuthorRef, AuthorSearch, InstitutionRef, LookupCoauthor, LookupInstitution, MatchKind, MatchOut } from "../../api/types";

export const DEFAULT_MIN_SHARED = 3;
export type Group = AuthorSearch["group"];

export const GROUP_WORDS: Record<Group, string> = {
  coauthors: "Frequent co-authors",
  institution: "Their institution(s) — much broader",
  person: "The person only",
};

export const MATCH_KINDS: MatchKind[] = ["person", "coauthor", "institution", "name_match"];
export const MATCH_FILTER_WORDS: Record<MatchKind, string> = {
  person: "the person",
  coauthor: "a co-author",
  institution: "the institution",
  name_match: "name match",
};

/** "Matched by" in words: the person / co-author X / institution X / name match X (never by colour alone). */
export function matchWords(match: MatchOut): string {
  if (match.kind === "person") return `the person (${match.name})`;
  if (match.kind === "coauthor") return `co-author ${match.name}`;
  if (match.kind === "institution") return `institution ${match.name}`;
  return `name match: ${match.name} — may be another person`;
}

export const personOf = (c: AuthorCandidate): AuthorRef => ({ openalex_id: c.openalex_id, name: c.name, orcid: c.orcid ?? "", s2_id: "" });

/** One candidate line: institution, works, ORCID, topics. */
export function candidateWords(c: AuthorCandidate): string {
  const parts = [c.institution?.name ?? "institution unknown", `${c.works_count.toLocaleString("en-US")} works`, c.orcid ? `ORCID ${c.orcid}` : "no ORCID"];
  if (c.concepts.length) parts.push(c.concepts.slice(0, 3).join(", "));
  return parts.join(" · ");
}

const coauthorRef = (c: LookupCoauthor): AuthorRef => ({ openalex_id: c.openalex_id, name: c.name, orcid: c.orcid ?? "", s2_id: "" });

/** The co-authors checked by default: at least `min` shared works. */
export const defaultCoauthors = (coauthors: LookupCoauthor[], min: number): AuthorRef[] => coauthors.filter((c) => c.shared >= min).map(coauthorRef);

/** The spec after a group lookup: people with their Semantic Scholar ids, co-authors checked by `min_shared`, institutions. */
export function withGroup(spec: AuthorSearch, people: AuthorRef[], coauthors: LookupCoauthor[], institutions: LookupInstitution[]): AuthorSearch {
  const min = spec.min_shared ?? DEFAULT_MIN_SHARED;
  return {
    ...spec,
    people,
    coauthors: defaultCoauthors(coauthors, min),
    institutions: institutions.slice(0, 3).map((i): InstitutionRef => ({ openalex_id: i.openalex_id, name: i.name })),
  };
}

export const newSpec = (people: AuthorRef[]): AuthorSearch => ({ people, group: "coauthors", coauthors: [], institutions: [], min_shared: DEFAULT_MIN_SHARED });

export function toggle<T extends { openalex_id: string }>(items: T[], item: T, on: boolean): T[] {
  const rest = items.filter((i) => i.openalex_id !== item.openalex_id);
  return on ? [...rest, item] : rest;
}

export const asCoauthorRef = coauthorRef;
