import type { PanelOut } from "../../api/types";
import { textSourceLabel } from "./cells";

const ANSWER: Record<string, { icon: string; word: string }> = {
  yes: { icon: "✓", word: "yes" },
  no: { icon: "✗", word: "no" },
  unclear: { icon: "?", word: "unclear" },
  not_reported: { icon: "–", word: "not reported" },
};
export const answerParts = (answer: string) => ANSWER[answer] ?? { icon: "·", word: answer.replace(/_/g, " ") };

const VERDICT: Record<string, string> = { include: "include", exclude: "exclude", uncertain: "uncertain" };
export const verdictWord = (verdict: string | null | undefined) => (verdict ? (VERDICT[verdict] ?? verdict) : "no verdict");

export const listWords = (names: string[]) =>
  names.length <= 1 ? (names[0] ?? "") : `${names.slice(0, -1).join(", ")} and ${names[names.length - 1]}`;

const thousands = (n: number) => n.toLocaleString("en-US").replace(/,/g, " ");

/** Which text the reviewers read, in one sentence. */
export function textSentence(panel: PanelOut): string {
  if (panel.text_source === "abstract") return `Reviewed on the abstract only${panel.text_reason ? ` (${panel.text_reason})` : ""}.`;
  const details = [
    panel.text_sections.length ? panel.text_sections.map((s) => s[0]!.toUpperCase() + s.slice(1)).join(", ") : null,
    panel.text_chars != null ? `${thousands(panel.text_chars)} characters${panel.text_truncated ? ", cut to the length limit" : ""}` : null,
  ].filter(Boolean);
  return `Reviewed on the ${textSourceLabel(panel.text_source).replace("full text · ", "full text from ")}${details.length ? ` (${details.join("; ")})` : ""}.`;
}

/** Key → display name for every reviewer in the panel. */
export const reviewerNames = (panel: PanelOut) => Object.fromEntries(panel.reviews.map((r) => [r.key, r.name]));

/** Item key → its text, as the reviewers' answers carry it. */
export const itemTexts = (panel: PanelOut) => {
  const texts: Record<string, string> = {};
  for (const review of panel.reviews) for (const a of review.answers) if (a.text && !texts[a.key]) texts[a.key] = a.text;
  return texts;
};

export function disagreementSentence(panel: PanelOut, d: PanelOut["editor"]["disagreements"][number]): string {
  const names = reviewerNames(panel);
  const who = listWords(d.reviewers.map((k) => names[k] ?? k));
  const text = itemTexts(panel)[d.item];
  return `${who || "Reviewers"} disagree on ${d.item}${text ? ` (“${text}”)` : ""}${d.note ? `: ${d.note}` : "."}`;
}
