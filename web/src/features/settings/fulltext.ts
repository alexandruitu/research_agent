import type { FulltextIO } from "../../api/types";

export type FulltextSource = FulltextIO["sources"][number];

type Resolver = { key: FulltextSource; label: string; explain: string; licence: string; source: string | null };

/** Every resolver, in the pipeline's default order (fulltext.DEFAULT_ORDER). `source` names its row in Sources. */
export const FULLTEXT_SOURCES: Resolver[] = [
  { key: "pmc_oa", label: "PubMed Central Open Access", source: "europepmc", explain: "The full article from Europe PMC when the paper has a PMCID. Free, no key.", licence: "Records the article's Creative Commons licence when it states one, else “open access”." },
  { key: "europepmc", label: "Europe PMC open-access links", source: "europepmc", explain: "Open-access PDF links Europe PMC lists for papers outside PMC. Free, no key.", licence: "Open-access copies only; licence from the record when stated." },
  { key: "core", label: "CORE", source: "core", explain: "Full texts harvested from open repositories. Needs CORE_API_KEY in the worker.", licence: "Open-access copies only; licence recorded when CORE states it." },
  { key: "springer_oa", label: "Springer Nature open access", source: "springer", explain: "Open-access Springer Nature articles as structured text. Needs SPRINGER_API_KEY in the worker.", licence: "Open-access articles only, with their Creative Commons licence." },
  { key: "semantic_scholar_oa", label: "Semantic Scholar open-access PDFs", source: "semantic_scholar", explain: "The open-access PDF Semantic Scholar links to. Works without a key; S2_API_KEY raises the rate limit.", licence: "Open-access copies only; licence recorded when stated." },
  { key: "unpaywall", label: "Unpaywall (legal open-access copies)", source: "unpaywall", explain: "Looks up a legal open-access PDF or page by DOI. Unpaywall asks for a contact email.", licence: "Legal open-access copies; the licence Unpaywall reports, else “open access”." },
  { key: "ieee", label: "IEEE Xplore open access", source: "ieee", explain: "IEEE articles marked open access, as PDF. Needs IEEE_API_KEY in the worker.", licence: "Open-access articles only; subscription articles are never fetched." },
  { key: "sciencedirect", label: "ScienceDirect (institutional entitlement)", source: "sciencedirect", explain: "Elsevier full text only when Elsevier confirms your institution is entitled to it. Needs ELSEVIER_API_KEY and ELSEVIER_INSTTOKEN in the worker.", licence: "Publisher-licensed: reviewed under your entitlement, never exported or shared outside the team." },
  { key: "upload", label: "PDFs uploaded by your team", source: null, explain: "Members can upload a PDF on a paper; the next run reviews it. Turn off to hide uploads.", licence: "Recorded as uploaded by your team." },
];

export const resolverInfo = (key: FulltextSource) => FULLTEXT_SOURCES.find((r) => r.key === key)!;

export const EMAIL = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;

export function validateFulltext(f: FulltextIO): string[] {
  const errors: string[] = [];
  if (f.sources.includes("unpaywall") && !(f.contact ?? "").trim()) errors.push("Unpaywall needs a contact email.");
  if ((f.contact ?? "").trim() && !EMAIL.test((f.contact ?? "").trim())) errors.push("The contact must be an email address.");
  if (!Number.isInteger(f.max_chars) || f.max_chars < 2000 || f.max_chars > 200000) errors.push("Maximum length must be a whole number from 2 000 to 200 000 characters.");
  if (!Number.isInteger(f.upload_max_mb) || f.upload_max_mb < 1 || f.upload_max_mb > 30) errors.push("Upload limit must be a whole number from 1 to 30 MB.");
  return errors;
}

export type ResolverEntry = { key: FulltextSource; on: boolean };

/** The editable list: the enabled resolvers in their saved order, then the others in the default order. */
export function resolverList(enabled: FulltextSource[]): ResolverEntry[] {
  const known = enabled.filter((k) => FULLTEXT_SOURCES.some((r) => r.key === k));
  return [
    ...known.map((key) => ({ key, on: true })),
    ...FULLTEXT_SOURCES.filter((r) => !known.includes(r.key)).map((r) => ({ key: r.key, on: false })),
  ];
}

/** The list with the entry at `index` moved one place up (-1) or down (+1); unchanged at the ends. */
export function moveResolver(list: ResolverEntry[], index: number, delta: -1 | 1): ResolverEntry[] {
  const target = index + delta;
  if (index < 0 || index >= list.length || target < 0 || target >= list.length) return list;
  const next = [...list];
  [next[index], next[target]] = [next[target]!, next[index]!];
  return next;
}

/** The order the pipeline tries: only the enabled resolvers, as listed. */
export const enabledOrder = (list: ResolverEntry[]) => list.filter((e) => e.on).map((e) => e.key);
