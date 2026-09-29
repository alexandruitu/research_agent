import type { ChecklistItemIn, ChecklistItemOut, ReviewerVersionOut } from "../../api/types";

/** Saved items back to the request shape (keys kept, so answers stay comparable across versions). */
export const itemsIn = (items: ChecklistItemOut[]): ChecklistItemIn[] =>
  items.map((i) => ({ key: i.key, text: i.text, weight: i.weight, source: i.source, pass_if: i.pass_if === "no" ? "no" : "yes", red_flag_if: i.red_flag_if === "yes" || i.red_flag_if === "no" ? i.red_flag_if : null }));

/** The next version of a reviewer with only the model changed. */
export const withModel = (version: ReviewerVersionOut, model: string | null, note: string) => ({
  name: version.name, perspective: version.perspective, model, items: itemsIn(version.items), note,
});
