import type { FieldBody } from "../../api/hooks";
import type { FieldDraft, FieldVersionOut } from "../../api/types";
import { isSourceName } from "./labels";

/** What the editor holds: everything as typed, so validation can name each problem. */
export type FieldForm = {
  name: string; topic: string; include: string[]; exclude: string[]; sources: string[]; yearFrom: string; yearTo: string; note: string;
};

export const emptyForm = (sources: string[]): FieldForm => ({ name: "", topic: "", include: [], exclude: [], sources, yearFrom: "", yearTo: "", note: "" });

/** Legacy criteria (topic_match) are not editable: a legacy version loads with empty lists. */
export const formFromVersion = (version: FieldVersionOut): FieldForm => ({
  name: version.name,
  topic: version.topic,
  include: version.include.map((c) => c.text),
  exclude: version.exclude.map((c) => c.text),
  sources: [...version.sources],
  yearFrom: version.years.from == null ? "" : String(version.years.from),
  yearTo: version.years.to == null ? "" : String(version.years.to),
  note: "",
});

const YEAR = /^\d{4}$/;
const year = (text: string) => (text.trim() === "" ? null : Number(text.trim()));

/** Every problem in form order; empty when the form can be saved or tested. */
export function validate(form: FieldForm): string[] {
  const problems: string[] = [];
  if (!form.name.trim()) problems.push("Give the field a name.");
  if (!form.topic.trim()) problems.push("Describe the topic.");
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

export const toDraft = (form: FieldForm): FieldDraft => ({
  name: form.name.trim(),
  topic: form.topic.trim(),
  include: form.include.map((text) => ({ text: text.trim() })),
  exclude: form.exclude.map((text) => ({ text: text.trim() })),
  sources: form.sources.filter(isSourceName),
  years: { from: year(form.yearFrom), to: year(form.yearTo) },
});

export const toBody = (form: FieldForm): FieldBody => ({ ...toDraft(form), note: form.note.trim() });

export function moveItem<T>(items: T[], index: number, delta: number): T[] {
  const target = index + delta;
  if (index < 0 || index >= items.length || target < 0 || target >= items.length) return items;
  const next = [...items];
  const [item] = next.splice(index, 1);
  next.splice(target, 0, item as T);
  return next;
}
