import type { FieldVersionOut } from "../../api/types";
import { sourceLabel } from "./labels";

export type DiffLine = { change: "added" | "removed" | "unchanged"; text: string };
export type DiffSection = { title: string; lines: DiffLine[] };

function listDiff(before: string[], after: string[]): DiffLine[] {
  const kept: DiffLine[] = before.map((text) => ({ change: after.includes(text) ? "unchanged" : "removed", text }));
  const added: DiffLine[] = after.filter((text) => !before.includes(text)).map((text) => ({ change: "added", text }));
  return [...kept, ...added];
}

const years = (v: FieldVersionOut) => `${v.years.from ?? "any year"} – ${v.years.to ?? "now"}`;
const texts = (items: { text: string }[]) => items.map((c) => c.text);

/** What changed from `before` to `after`, per section. A reworded criterion shows as removed plus added. */
export function diffVersions(before: FieldVersionOut, after: FieldVersionOut): DiffSection[] {
  const sections: DiffSection[] = [
    { title: "Name", lines: listDiff([before.name], [after.name]) },
    { title: "Topic", lines: listDiff([before.topic], [after.topic]) },
    { title: "Inclusion criteria", lines: listDiff(texts(before.include), texts(after.include)) },
    { title: "Exclusion criteria", lines: listDiff(texts(before.exclude), texts(after.exclude)) },
    { title: "Legacy topic match", lines: listDiff(texts(before.legacy), texts(after.legacy)) },
    { title: "Sources", lines: listDiff(before.sources.map(sourceLabel), after.sources.map(sourceLabel)) },
    { title: "Years", lines: listDiff([years(before)], [years(after)]) },
  ];
  return sections.filter((section) => section.lines.length > 0);
}

export const hasChanges = (sections: DiffSection[]) => sections.some((s) => s.lines.some((line) => line.change !== "unchanged"));
