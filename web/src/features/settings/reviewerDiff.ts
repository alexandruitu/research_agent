import type { ReviewerVersionOut } from "../../api/types";

export type ReviewerChange = { kind: "added" | "removed" | "changed"; text: string };

const itemWords = (i: ReviewerVersionOut["items"][number]) =>
  `${i.key}: ${i.text} (weight ${i.weight}, passes on ${i.pass_if}${i.red_flag_if ? `, red flag on ${i.red_flag_if}` : ""}${i.source ? `, ${i.source}` : ""})`;

/** What changed between two versions of a reviewer, in words; items are matched by key. */
export function diffReviewers(before: ReviewerVersionOut, after: ReviewerVersionOut): ReviewerChange[] {
  const changes: ReviewerChange[] = [];
  if (before.name !== after.name) changes.push({ kind: "changed", text: `Name: “${before.name}” → “${after.name}”` });
  if (before.perspective !== after.perspective) changes.push({ kind: "changed", text: `Perspective: “${after.perspective}”` });
  if ((before.model ?? null) !== (after.model ?? null)) changes.push({ kind: "changed", text: `Model: ${before.model ?? "worker default"} → ${after.model ?? "worker default"}` });
  const old = new Map(before.items.map((i) => [i.key, i]));
  const now = new Map(after.items.map((i) => [i.key, i]));
  for (const item of after.items) {
    const prev = old.get(item.key);
    if (!prev) changes.push({ kind: "added", text: itemWords(item) });
    else if (itemWords(prev) !== itemWords(item)) changes.push({ kind: "changed", text: itemWords(item) });
  }
  for (const item of before.items) if (!now.has(item.key)) changes.push({ kind: "removed", text: itemWords(item) });
  return changes;
}
