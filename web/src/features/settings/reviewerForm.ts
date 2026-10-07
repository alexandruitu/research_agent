import type { ChecklistItemIn, ChecklistItemOut, ReviewerContent, ReviewerVersionOut } from "../../api/types";

/** Saved items back to the request shape (keys kept, so answers stay comparable across versions). */
export const itemsIn = (items: ChecklistItemOut[]): ChecklistItemIn[] =>
  items.map((i) => ({ key: i.key, text: i.text, weight: i.weight, source: i.source, pass_if: i.pass_if === "no" ? "no" : "yes", red_flag_if: i.red_flag_if === "yes" || i.red_flag_if === "no" ? i.red_flag_if : null, flag_text: i.flag_text ?? null }));

/** The next version of a reviewer with only the model changed. */
export const withModel = (version: ReviewerVersionOut, model: string | null, note: string) => ({
  name: version.name, perspective: version.perspective, model, items: itemsIn(version.items), note,
});

export const SOURCE_FAMILIES = ["CLAIM", "TRIPOD+AI", "other", "none"] as const;
export type SourceFamily = (typeof SOURCE_FAMILIES)[number];
export type Weight = 1 | 2 | 3;
export type RedFlagRule = "never" | "yes" | "no";

export type ItemForm = {
  uid: string; key: string | null; text: string; weight: Weight; family: SourceFamily; ref: string; passIf: "yes" | "no"; redFlagIf: RedFlagRule;
  /** How a raised red flag reads, phrased as the problem ("No external validation"); empty: generated. */
  flagText: string;
};
export type ReviewerForm = { name: string; perspective: string; model: string | null; items: ItemForm[] };

export const MAX_ITEMS = 20;
let counter = 0;
const uid = () => `item-${++counter}`;

/** "CLAIM 2020 #21" → CLAIM + "2020 #21"; "TRIPOD+AI 10" → TRIPOD+AI + "10"; null → none; anything else → other. */
export function splitSource(source: string | null): { family: SourceFamily; ref: string } {
  const text = (source ?? "").trim();
  if (!text) return { family: "none", ref: "" };
  for (const family of ["TRIPOD+AI", "CLAIM"] as const) {
    if (text === family || text.startsWith(`${family} `)) return { family, ref: text.slice(family.length).trim() };
  }
  return { family: "other", ref: text };
}

export function joinSource(family: SourceFamily, ref: string): string | null {
  const text = ref.trim();
  if (family === "none") return null;
  if (family === "other") return text || null;
  return text ? `${family} ${text}` : family;
}

export const emptyItem = (): ItemForm => ({ uid: uid(), key: null, text: "", weight: 1, family: "CLAIM", ref: "", passIf: "yes", redFlagIf: "never", flagText: "" });

export function formFromContent(content: ReviewerContent | ReviewerVersionOut): ReviewerForm {
  return {
    name: content.name, perspective: content.perspective, model: content.model,
    items: content.items.map((i) => ({
      uid: uid(), key: i.key, text: i.text, weight: (Math.min(3, Math.max(1, i.weight)) as Weight), ...splitSource(i.source),
      passIf: i.pass_if === "no" ? "no" : "yes", redFlagIf: i.red_flag_if === "yes" || i.red_flag_if === "no" ? i.red_flag_if : "never",
      flagText: i.flag_text ?? "",
    })),
  };
}

export const emptyForm = (): ReviewerForm => ({ name: "", perspective: "", model: null, items: [emptyItem()] });

/** Items with no text are dropped; keys of new items are left to the server. */
export function toBody(form: ReviewerForm, note: string) {
  return {
    name: form.name.trim(), perspective: form.perspective.trim(), model: form.model, note: note.trim(),
    items: form.items.filter((i) => i.text.trim()).map((i): ChecklistItemIn => ({
      key: i.key, text: i.text.trim(), weight: i.weight, source: joinSource(i.family, i.ref), pass_if: i.passIf, red_flag_if: i.redFlagIf === "never" ? null : i.redFlagIf,
      flag_text: i.flagText.trim() || null,
    })),
  };
}

export function validateReviewer(form: ReviewerForm): string[] {
  const errors: string[] = [];
  const items = form.items.filter((i) => i.text.trim());
  if (!form.name.trim()) errors.push("Give the reviewer a name.");
  if (form.name.trim().length > 100) errors.push("The name is at most 100 characters.");
  if (form.perspective.trim().length < 10) errors.push("Describe the perspective in at least 10 characters.");
  if (form.perspective.length > 2000) errors.push("The perspective is at most 2 000 characters.");
  if (items.length === 0) errors.push("Add at least one checklist item.");
  if (items.length > MAX_ITEMS) errors.push(`A reviewer has at most ${MAX_ITEMS} items.`);
  items.forEach((item, index) => {
    const t = item.text.trim();
    if (t.length < 3) errors.push(`Item ${index + 1} is too short.`);
    if (t.length > 500) errors.push(`Item ${index + 1} is longer than 500 characters.`);
    if (item.flagText.trim().length > 200) errors.push(`The red-flag wording of item ${index + 1} is longer than 200 characters.`);
    if ((joinSource(item.family, item.ref) ?? "").length > 60) errors.push(`The source of item ${index + 1} is longer than 60 characters.`);
  });
  return errors;
}

export const moveItem = <T,>(items: T[], index: number, by: -1 | 1): T[] => {
  const target = index + by;
  if (target < 0 || target >= items.length) return items;
  const next = [...items];
  [next[index], next[target]] = [next[target]!, next[index]!];
  return next;
};

/** What the model is given about this reviewer: the perspective and each item's key and text, nothing else. */
export function preview(form: ReviewerForm): { perspective: string; items: { key: string; text: string }[] } {
  return {
    perspective: form.perspective.trim(),
    items: form.items.filter((i) => i.text.trim()).map((i, index) => ({ key: i.key ?? `new ${index + 1}`, text: i.text.trim() })),
  };
}

/** Comparable content, ignoring the React-only uid. */
export const signature = (form: ReviewerForm) => JSON.stringify(toBody(form, ""));

export const firstSentence = (text: string) => {
  const match = text.trim().match(/^.*?[.!?](\s|$)/);
  return (match ? match[0] : text).trim();
};
