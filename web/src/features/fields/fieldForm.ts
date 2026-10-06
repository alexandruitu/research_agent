import type { FieldBody } from "../../api/hooks";
import type { FieldDraft, FieldVersionOut } from "../../api/types";
import { checkOverride, hasTerms, QUERY_SOURCES, QueryError, type Keywords, type QuerySource } from "../fieldflow/querybuild";
import { isSourceName } from "./labels";

export type Overrides = Record<QuerySource, string>;

/** What the editor holds: everything as typed, so validation can name each problem. */
export type FieldForm = {
  name: string; description: string; topic: string; keywords: Keywords; overrides: Overrides;
  include: string[]; exclude: string[]; sources: string[]; yearFrom: string; yearTo: string; note: string;
  /** Sources that fail the run when they fail (partial search skips the others with a warning). */
  required?: string[];
};

export const MAX_TERMS = 20;
export const noKeywords = (): Keywords => ({ all: [], any: [], none: [] });
export const noOverrides = (): Overrides => Object.fromEntries(QUERY_SOURCES.map((s) => [s, ""])) as Overrides;

export const emptyForm = (sources: string[]): FieldForm => ({
  name: "", description: "", topic: "", keywords: noKeywords(), overrides: noOverrides(),
  include: [], exclude: [], sources, yearFrom: "", yearTo: "", note: "",
});

/** Legacy criteria (topic_match) are not editable: a legacy version loads with empty lists. */
export const formFromVersion = (version: FieldVersionOut): FieldForm => ({
  name: version.name,
  description: version.description ?? "",
  topic: version.topic,
  keywords: { all: [...(version.keywords?.all ?? [])], any: [...(version.keywords?.any ?? [])], none: [...(version.keywords?.none ?? [])] },
  overrides: Object.fromEntries(QUERY_SOURCES.map((s) => [s, version.query_override?.[s] ?? ""])) as Overrides,
  include: version.include.map((c) => c.text),
  exclude: version.exclude.map((c) => c.text),
  sources: [...version.sources],
  required: [...(version.required_sources ?? [])],
  yearFrom: version.years.from == null ? "" : String(version.years.from),
  yearTo: version.years.to == null ? "" : String(version.years.to),
  note: "",
});

const YEAR = /^\d{4}$/;
const year = (text: string) => (text.trim() === "" ? null : Number(text.trim()));

/** The topic the server needs (3–500 characters): as typed, else the description's first sentence, else the keywords. */
export function effectiveTopic(form: FieldForm): string {
  const typed = form.topic.trim();
  if (typed) return typed;
  const sentence = form.description.trim().split(/(?<=[.!?])\s+/)[0]?.trim() ?? "";
  if (sentence) return sentence.slice(0, 500);
  return [...form.keywords.all, ...form.keywords.any].join(" ").slice(0, 500);
}

export const hasKeywords = (form: FieldForm) => hasTerms(form.keywords);

const GROUP_NAME = { all: "Must include", any: "At least one of", none: "Exclude" } as const;

/** Every problem in form order; empty when the form can be saved or tested. */
export function validate(form: FieldForm): string[] {
  const problems: string[] = [];
  if (!form.name.trim()) problems.push("Give the field a name.");
  if (effectiveTopic(form).length < 3) problems.push("Describe the field or add keywords.");
  for (const group of ["all", "any", "none"] as const) {
    const terms = form.keywords[group];
    if (terms.length > MAX_TERMS) problems.push(`${GROUP_NAME[group]} has more than ${MAX_TERMS} keywords.`);
    if (terms.some((t) => t.trim().length > 80)) problems.push(`A keyword in ${GROUP_NAME[group]} is longer than 80 characters.`);
  }
  if (form.keywords.none.length > 0 && form.keywords.all.length + form.keywords.any.length === 0) {
    problems.push("Add a keyword to Must include or At least one of (Exclude alone cannot search).");
  }
  for (const source of QUERY_SOURCES) {
    try {
      checkOverride(source, form.overrides[source]);
    } catch (error) {
      if (error instanceof QueryError) problems.push(`${error.message}.`);
    }
  }
  form.include.forEach((text, i) => {
    if (!text.trim()) problems.push(`Inclusion criterion ${i + 1} is empty.`);
  });
  form.exclude.forEach((text, i) => {
    if (!text.trim()) problems.push(`Exclusion criterion ${i + 1} is empty.`);
  });
  if (form.include.length + form.exclude.length === 0) problems.push("Add at least one inclusion or exclusion criterion.");
  if (!form.sources.some(isSourceName)) problems.push("Choose at least one source.");
  const years = [form.yearFrom, form.yearTo].map((text) => text.trim()).filter(Boolean);
  if (years.some((text) => !YEAR.test(text) || Number(text) < 1900 || Number(text) > 2100)) {
    problems.push("Years must be four-digit years between 1900 and 2100.");
  } else {
    const from = year(form.yearFrom);
    const to = year(form.yearTo);
    if (from !== null && to !== null && from > to) problems.push("The first year is after the last year.");
  }
  return problems;
}

const cleanTerms = (terms: string[]) => terms.map((t) => t.trim()).filter(Boolean);

export const draftKeywords = (form: FieldForm): Keywords | null => {
  const keywords = { all: cleanTerms(form.keywords.all), any: cleanTerms(form.keywords.any), none: cleanTerms(form.keywords.none) };
  return keywords.all.length + keywords.any.length + keywords.none.length > 0 ? keywords : null;
};

export const draftOverrides = (form: FieldForm): Partial<Overrides> | null => {
  const set = QUERY_SOURCES.filter((s) => form.overrides[s].trim()).map((s) => [s, form.overrides[s].trim()] as const);
  return set.length ? Object.fromEntries(set) : null;
};

export const toDraft = (form: FieldForm): FieldDraft => {
  const draft: FieldDraft = {
    name: form.name.trim(),
    topic: effectiveTopic(form),
    include: form.include.map((text) => ({ text: text.trim() })),
    exclude: form.exclude.map((text) => ({ text: text.trim() })),
    sources: form.sources.filter(isSourceName),
    years: { from: year(form.yearFrom), to: year(form.yearTo) },
  };
  if (form.description.trim()) draft.description = form.description.trim();
  const keywords = draftKeywords(form);
  if (keywords) draft.keywords = keywords;
  const overrides = draftOverrides(form);
  if (overrides) draft.query_override = overrides;
  const required = draft.sources.filter((s) => (form.required ?? []).includes(s));
  if (required.length) draft.required_sources = required;
  return draft;
};

export const toBody = (form: FieldForm): FieldBody => ({ ...toDraft(form), note: form.note.trim() });

export const yearsOf = (form: FieldForm) => ({ from: year(form.yearFrom), to: year(form.yearTo) });

export function moveItem<T>(items: T[], index: number, delta: number): T[] {
  const target = index + delta;
  if (index < 0 || index >= items.length || target < 0 || target >= items.length) return items;
  const next = [...items];
  const [item] = next.splice(index, 1);
  next.splice(target, 0, item as T);
  return next;
}

/** Adds terms to a group, skipping case-insensitive duplicates and empty text; keeps the cap. */
export function addTerms(existing: string[], terms: string[]): string[] {
  const seen = new Set(existing.map((t) => t.toLowerCase()));
  const next = [...existing];
  for (const raw of terms) {
    const term = raw.trim().replace(/\s+/g, " ");
    if (!term || seen.has(term.toLowerCase()) || next.length >= MAX_TERMS) continue;
    seen.add(term.toLowerCase());
    next.push(term);
  }
  return next;
}
