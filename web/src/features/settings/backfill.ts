/** The authors backfill job's progress and result: {total, done, updated, not_found, no_authors, failed}. */
export type BackfillSummary = Partial<Record<"total" | "done" | "updated" | "not_found" | "no_authors" | "failed", number>>;

/** "12 of 40 looked up · 9 updated · 2 not in OpenAlex · 1 without authors · 0 failed", in words. */
export function backfillWords(summary: BackfillSummary, running: boolean): string {
  const n = (key: keyof BackfillSummary) => summary[key] ?? 0;
  const parts = [
    running ? `${n("done")} of ${n("total")} looked up` : `Done: ${n("done")} of ${n("total")} looked up`,
    `${n("updated")} updated`,
    `${n("not_found")} not in OpenAlex`,
    `${n("no_authors")} without authors there`,
    `${n("failed")} failed`,
  ];
  return parts.join(" · ");
}
