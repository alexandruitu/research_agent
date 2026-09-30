import { QUERY_SOURCES } from "../fieldflow/querybuild";

/** Every source a field may search (the server's registry; Settings → Sources lists the rest of it). */
export const SOURCE_NAMES = QUERY_SOURCES;
export type SourceName = (typeof SOURCE_NAMES)[number];

/** Names only, so paper rows render before /sources answers; groups and key status come from the API. */
const SOURCE_LABEL: Record<string, string> = {
  europepmc: "Europe PMC", pubmed: "PubMed", arxiv: "arXiv", medrxiv: "medRxiv", biorxiv: "bioRxiv", openalex: "OpenAlex",
  semantic_scholar: "Semantic Scholar", core: "CORE", unpaywall: "Unpaywall", ieee: "IEEE Xplore", springer: "Springer Nature",
  scopus: "Scopus", sciencedirect: "ScienceDirect", crossref: "Crossref", demo: "demo",
};

export const sourceLabel = (name: string) => SOURCE_LABEL[name] ?? name;
export const isSourceName = (name: string): name is SourceName => (SOURCE_NAMES as readonly string[]).includes(name);

const FIELD_KEY = /^([ie])(\d+)$/;

/** True for the keys a field's criteria get on save (i1.., e1..); false for legacy keys such as topic_match. */
export const isFieldCriterion = (key: string) => FIELD_KEY.test(key);

/** "i1" -> "incl 1", "e2" -> "excl 2", "topic_match" -> "topic match". */
export function criterionLabel(key: string): string {
  const match = FIELD_KEY.exec(key);
  if (!match) return key.replace(/_/g, " ");
  return `${match[1] === "i" ? "incl" : "excl"} ${match[2]}`;
}

export const shortDate = (iso: string) => new Date(iso).toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });

const LICENCE: Record<string, string> = {
  "cc-by": "Creative Commons BY", "cc-by-sa": "Creative Commons BY-SA", "cc-by-nd": "Creative Commons BY-ND",
  "cc-by-nc": "Creative Commons BY-NC", "cc-by-nc-sa": "Creative Commons BY-NC-SA", "cc-by-nc-nd": "Creative Commons BY-NC-ND",
  cc0: "public domain (CC0)", open_access: "open access, licence not stated", publisher_licensed: "publisher licence (your institution's entitlement; not redistributed)",
  user_upload: "uploaded by your team", abstract: "abstract only",
};

/** The licence of the text the reviewers read, in words; null for runs before licences were recorded. */
export const licenceLabel = (licence: string | null | undefined) => (licence ? (LICENCE[licence] ?? licence.replace(/_/g, " ")) : null);
