import type { ReaderHighlight } from "../../api/types";

export type Segment = { text: string; marks: ReaderHighlight[] };

/** Every place a quote occurs in `text` (exact, non-overlapping occurrences of the same quote). */
function occurrences(text: string, quote: string): [number, number][] {
  const out: [number, number][] = [];
  if (!quote) return out;
  for (let at = text.indexOf(quote); at >= 0; at = text.indexOf(quote, at + quote.length)) out.push([at, at + quote.length]);
  return out;
}

/**
 * The text cut into plain and marked pieces. A piece covered by several quotes carries all of them (a red flag
 * and a claim on the same words both show). Quotes that do not occur in this text are simply not marked here.
 */
export function segments(text: string, highlights: ReaderHighlight[]): Segment[] {
  const ranges = highlights.flatMap((h) => occurrences(text, h.quote).map(([start, end]) => ({ start, end, h })));
  if (ranges.length === 0) return text ? [{ text, marks: [] }] : [];
  const cuts = [...new Set([0, text.length, ...ranges.flatMap((r) => [r.start, r.end])])].sort((a, b) => a - b);
  const out: Segment[] = [];
  for (let i = 0; i < cuts.length - 1; i++) {
    const [from, to] = [cuts[i]!, cuts[i + 1]!];
    if (from === to) continue;
    const marks = ranges.filter((r) => r.start <= from && r.end >= to).map((r) => r.h);
    const last = out[out.length - 1];
    if (last && last.marks.length === 0 && marks.length === 0) last.text += text.slice(from, to);
    else out.push({ text: text.slice(from, to), marks });
  }
  return out;
}

/** The quotes found in none of the sections (e.g. a quote that spans two sections): listed, never hidden. */
export function unplaced(sections: { text: string }[], highlights: ReaderHighlight[]): ReaderHighlight[] {
  return highlights.filter((h) => !sections.some((s) => s.text.includes(h.quote)));
}

export const MAX_SELECTION = 4000;

/** The current selection's text when it lies inside `container`, trimmed; "" otherwise. */
export function selectionIn(container: HTMLElement | null): string {
  const selection = typeof window === "undefined" ? null : window.getSelection();
  if (!container || !selection || selection.rangeCount === 0 || selection.isCollapsed) return "";
  const range = selection.getRangeAt(0);
  if (!container.contains(range.commonAncestorContainer)) return "";
  return selection.toString().replace(/\s+/g, " ").trim();
}
