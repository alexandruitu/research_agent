import type { PaperRow } from "../../api/types";
import { criterionLines } from "./why";

/**
 * The Simple view's words: one plain sentence per paper and the next thing to do. No model names, tiers,
 * escalation or thresholds here; those live in the Detailed view and the drawer.
 */
export function plainWhy(row: PaperRow, texts: Record<string, string> = {}): string {
  const { screen } = row;
  if (screen.tier === "rule") return "Not checked against your search: no abstract was available.";
  if (screen.decision === "exclude") {
    const lines = criterionLines(screen);
    const key = screen.decided_by ?? (lines.length === 1 ? lines[0]!.key : null);
    const line = lines.find((l) => l.key === key);
    const text = key ? texts[key]?.replace(/\.$/, "") : undefined;
    if (!text) return "Does not match your search.";
    return line?.kind === "exclude" ? `Does not match your search: it is ‘${text}’.` : `Does not match your search: not ‘${text}’.`;
  }
  const head = screen.decision === "uncertain" ? "Might match your search" : "Matches your search";
  const flags = row.red_flags ?? [];
  if ((row.red_flag_count ?? 0) > 0) {
    return `${head}, but the review found a problem${flags[0] ? `: ${flags[0].replace(/\.$/, "")}` : ""}.`;
  }
  if (row.provisional || row.text_source === "abstract") return `${head}; only the abstract was read, so the review is not final.`;
  if (row.group === "read_first") return `${head} and the review found no problems.`;
  if (row.group === "has_problems") return `${head}, but the review advises against relying on it.`;
  if (row.group === "not_reviewed" || row.red_flag_count == null) return `${head}; not reviewed in depth yet.`;
  return `${head}; the review found no serious problems.`;
}

export type NextAction = { word: string; hint: string };

/** What to do next with the paper, first match wins. */
export function nextAction(row: PaperRow): NextAction | null {
  if (row.screen.decision === "exclude") return null;
  if (row.screen.decision === "uncertain" || row.screen.tier === "rule") return { word: "Check the match", hint: "The search could not decide: read the abstract and judge it yourself." };
  if ((row.red_flag_count ?? 0) > 0) return { word: "Check red flag", hint: "Open the paper to see the problem and the quote it rests on." };
  if (row.provisional || row.text_source === "abstract") return { word: "Upload full text", hint: "The review read only the abstract; upload the PDF to firm it up." };
  if (!row.library) return { word: "Save", hint: "Worth keeping: save it to the team library." };
  return { word: "Read", hint: "Open the paper and read the evidence." };
}
