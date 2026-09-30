import type { SourceOut } from "../../api/types";

export type SourceGroup = SourceOut["group"];

/** The Sources page, in reading order: what each group is for, and what it asks of you. */
export const SOURCE_GROUPS: { key: SourceGroup; title: string; intro: string }[] = [
  { key: "biomedical", title: "Biomedical", intro: "The core of a clinical imaging search: PubMed, PMC and the life-science literature. Free, no key needed." },
  { key: "preprints", title: "Preprints", intro: "Work before peer review — where MICCAI and cs.CV papers appear first. Read these results with that in mind." },
  { key: "multidisciplinary", title: "Multidisciplinary", intro: "Broad catalogues that also cover engineering and computer science. Some raise their rate limits with a free key." },
  { key: "publishers", title: "Publishers (licensed)", intro: "Publisher APIs. Each needs a key your organisation obtains from the publisher; full text is used only when it is open access or your institution is entitled to it." },
  { key: "identity", title: "Identity", intro: "Registries that confirm who a paper is: searched like any source, and used to find DOIs for papers that lack one." },
];

export const groupSources = (rows: SourceOut[]) =>
  SOURCE_GROUPS.map((group) => ({ ...group, sources: rows.filter((s) => s.group === group.key) })).filter((g) => g.sources.length > 0);

const vars = (names: string[]) => names.join(" and ");

/** What the source needs, in words (never a value). */
export function authWords(source: SourceOut): string {
  if (source.auth === "none") return "No key needed";
  if (source.auth === "optional") return `Optional key: set ${vars(source.env)} for higher limits`;
  return `Key required: set ${vars(source.env)}`;
}

/** What the worker last reported about the key; null when the source needs none. */
export function keyStatusWords(source: SourceOut): string | null {
  if (source.auth === "none") return null;
  if (!source.key_checked_at) return "Key status unknown: no worker has reported yet";
  if (!source.key_present) return source.auth === "required" ? "Key not set in the worker" : "Key not set: lower rate limit";
  if (source.key_accepted === true) return "Key set · accepted";
  if (source.key_accepted === false) return "Key set · rejected";
  return `Key set · not checked${source.key_detail === "check failed" ? " (the check failed)" : ""}`;
}

export type KeyTone = "ok" | "warn" | "bad" | "neutral";
export function keyTone(source: SourceOut): KeyTone {
  if (source.auth === "none") return "neutral";
  if (source.key_accepted === false || (source.auth === "required" && !source.key_present)) return "bad";
  if (source.key_accepted === true) return "ok";
  return "warn";
}

/** Why the enable switch is locked, or null: a required key the worker does not have. Disabling is always allowed. */
export function enableBlocked(source: SourceOut): string | null {
  if (source.enabled || source.auth !== "required" || source.key_present) return null;
  return `Set ${source.env[0]} in the worker environment first, then restart the worker.`;
}

export const searchable = (source: SourceOut) => source.capabilities.includes("search");

/** The request pace the worker keeps for this source. */
export function rateWords(source: SourceOut): string {
  const rps = source.rps_in_use;
  if (!rps) return "paced by the connector";
  if (rps >= 1) return `${Number.isInteger(rps) ? rps : rps.toFixed(1)} requests / s`;
  return `1 request every ${Math.round(1 / rps)} s`;
}
