import type { GroupDimension } from "../../api/hooks";
import { statusMeta } from "../../components/ui/StatusMark";
import { criterionLabel, sourceLabel } from "../fields/labels";

export type GroupBy = GroupDimension | "none";

export const GROUP_BY_OPTIONS: { value: GroupBy; label: string }[] = [
  { value: "quality", label: "Quality groups" },
  { value: "source", label: "Source" },
  { value: "year", label: "Year" },
  { value: "decided_by", label: "Dropped by criterion" },
  { value: "library", label: "Library status" },
  { value: "none", label: "None (flat list)" },
];

/** Icons are decoration next to the group's name, never its only signal. */
export const QUALITY_ICON: Record<string, string> = { read_first: "★", worth_a_look: "◐", has_problems: "⚑", not_relevant: "⊘", not_reviewed: "○" };

/** The quality group's name as the API labels it (rows carry the key only). */
export const QUALITY_LABEL: Record<string, string> = { read_first: "Read first", worth_a_look: "Worth a look", has_problems: "Has problems", not_relevant: "Not relevant", not_reviewed: "Not reviewed" };

const SPECIAL = new Set(["none", "kept", "not_screened", "unattributed", "not_saved"]);

/** The header name of a group: the server's label for quality and special keys, readable labels otherwise. */
export function groupName(by: GroupDimension, key: string, label: string): string {
  if (by === "quality" || SPECIAL.has(key)) return label;
  if (by === "decided_by") return `Dropped by ${criterionLabel(key)}`;
  if (by === "source") return sourceLabel(key);
  if (by === "library") return statusMeta(key).word;
  return label;
}

export const groupIcon = (by: GroupDimension, key: string) => (by === "quality" ? QUALITY_ICON[key] ?? "" : by === "library" && key !== "not_saved" ? statusMeta(key).icon : "");

const storageKey = (userId: string, by: GroupBy) => `papers.collapsed.${userId}.${by}`;
const defaults = (by: GroupBy) => new Set(by === "quality" ? ["not_relevant"] : []);

/** The groups this user keeps collapsed (storage may be missing or blocked: then the defaults). */
export function readCollapsed(userId: string, by: GroupBy): Set<string> {
  try {
    const raw = window.localStorage.getItem(storageKey(userId, by));
    if (raw === null) return defaults(by);
    const value: unknown = JSON.parse(raw);
    return Array.isArray(value) ? new Set(value.filter((k): k is string => typeof k === "string")) : defaults(by);
  } catch {
    return defaults(by);
  }
}

export function writeCollapsed(userId: string, by: GroupBy, keys: Set<string>): void {
  try {
    window.localStorage.setItem(storageKey(userId, by), JSON.stringify([...keys]));
  } catch {
    // private mode or blocked storage: the state lasts for this page only
  }
}
