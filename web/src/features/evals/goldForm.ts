import type { GoldStudyIn } from "../../api/types";

const DOI = /^(?:https?:\/\/(?:dx\.)?doi\.org\/|doi:\s*)?(10\.\S+)$/i;

/** One included study per line: `DOI`, `DOI | title | year`, or a title alone. Blank lines are ignored. */
export function parseIncluded(text: string): GoldStudyIn[] {
  return text.split("\n").map((line) => line.trim()).filter(Boolean).map((line) => {
    const [first = "", title = "", year = ""] = line.split("|").map((part) => part.trim());
    const doi = DOI.exec(first)?.[1];
    return doi ? { doi, title, year } : { doi: "", title: first, year: title && /^\d{4}$/.test(title) ? title : year };
  });
}

export type GoldDraft = { name: string; citation: string; topic: string; query: string; included: string };

export function goldProblems(d: GoldDraft): string[] {
  return [
    !d.name.trim() && "Give the gold set a name.",
    !d.citation.trim() && "Cite the systematic review.",
    !d.topic.trim() && "Say what the review is about (topic).",
    !d.query.trim() && "Give the search query used to collect candidates.",
    parseIncluded(d.included).length === 0 && "List at least one included study.",
  ].filter((x): x is string => !!x);
}
