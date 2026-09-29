export const SOURCE_NAMES = ["europepmc", "openalex", "arxiv"] as const;
export type SourceName = (typeof SOURCE_NAMES)[number];

const SOURCE_LABEL: Record<string, string> = { europepmc: "Europe PMC", openalex: "OpenAlex", arxiv: "arXiv", demo: "demo" };

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
