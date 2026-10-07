import type { RunOut, UserOut } from "../../api/types";
import { sourceLabel } from "../fields/labels";
import { skippedList } from "./SearchWarnings";

export const RUN_STATUSES = ["queued", "running", "done", "failed", "cancelled"] as const;
export const RUN_STATUS_META: Record<string, { icon: string; word: string }> = {
  queued: { icon: "…", word: "queued" },
  running: { icon: "↻", word: "running" },
  done: { icon: "✓", word: "done" },
  failed: { icon: "!", word: "failed" },
  cancelled: { icon: "⊘", word: "cancelled" },
};
export const runStatusMeta = (status: string) => RUN_STATUS_META[status] ?? { icon: "·", word: status };

/** The run's own name, else its field and version. */
export const runLabel = (run: Pick<RunOut, "name" | "field_name" | "field_version">) =>
  run.name || `${run.field_name}${run.field_version ? ` · v${run.field_version}` : ""}`;

/** The run's creator or an admin may resume, cancel, delete, rename, annotate and pin it. */
export const canManageRun = (user: UserOut | null | undefined, run: Pick<RunOut, "created_by">) =>
  !!user && (user.role === "admin" || (user.role === "member" && !!run.created_by && run.created_by === user.id));

export function formatSeconds(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined) return "not recorded";
  if (seconds < 1) return "under 1 s";
  if (seconds < 60) return `${Math.round(seconds)} s`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes} min ${Math.round(seconds % 60)} s`;
  return `${Math.floor(minutes / 60)} h ${minutes % 60} min`;
}

export const formatUsd = (value: number | null | undefined) =>
  value === null || value === undefined ? "no price" : value < 0.01 && value > 0 ? "< $0.01" : `$${value.toFixed(2)}`;

/**
 * "Searched: Europe PMC, OpenAlex · Skipped: Semantic Scholar (rate limited) · Max papers: 12 · Text: 3 full
 * text / 7 abstract only". Unknown parts say so ("not recorded"), never a silent zero.
 */
export function coverageLine(coverage: RunOut["coverage"]): string | null {
  if (!coverage) return null;
  const parts = [`Searched: ${coverage.searched.length ? coverage.searched.map(sourceLabel).join(", ") : "not recorded"}`];
  if (coverage.skipped) parts.push(`Skipped: ${coverage.skipped.length ? skippedList(coverage.skipped) : "none"}`);
  parts.push(`Max papers: ${coverage.max_papers ?? "not recorded"}`);
  parts.push(coverage.full_text == null || coverage.abstract_only == null
    ? "Text: not reviewed by the panel"
    : `Text: ${coverage.full_text} full text / ${coverage.abstract_only} abstract only`);
  return parts.join(" · ");
}

const clip = (text: string, max: number) => (text.length > max ? `${text.slice(0, max - 1).trimEnd()}…` : text);

/** "6 Oct, 11:25" (local time). */
export const runDate = (iso: string) =>
  new Date(iso).toLocaleString("en-GB", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });

/** The run's short name: its own name, else its topic clipped to 40 (null when it has neither). */
const ownName = (run: Pick<RunOut, "name" | "topic">) => run.name || (run.topic?.trim() ? clip(run.topic.trim(), 40) : null);

/** The run's short name, else its field and version. */
export const runShortName = (run: Pick<RunOut, "name" | "topic" | "field_name" | "field_version">) => ownName(run) ?? runLabel(run);

/** Status in words; failed and cancelled carry their mark too, so they stand out without colour. */
const statusText = (status: string) => (status === "failed" || status === "cancelled" ? `${runStatusMeta(status).icon} ${status}` : runStatusMeta(status).word);

/** One way to name a run everywhere: "Baseline · ML CT-FFR v3 · 6 Oct, 11:25 · done". */
export function runIdentity(run: Pick<RunOut, "name" | "topic" | "field_name" | "field_version" | "created_at" | "status">) {
  const field = `${clip(run.field_name, 32)}${run.field_version ? ` v${run.field_version}` : ""}`;
  // fields imported from older runs are named after their topic: then the topic would only repeat the field
  const norm = (t: string) => t.toLowerCase().replace(/\s+/g, " ").trim();
  const repeats = !run.name && !!run.topic && (norm(run.topic).startsWith(norm(run.field_name)) || norm(run.field_name).startsWith(norm(run.topic)));
  return [repeats ? null : ownName(run), field, runDate(run.created_at), statusText(run.status)].filter(Boolean).join(" · ");
}

/** Run pickers list the most recent run first. */
export const newestFirst = <T extends { created_at: string }>(runs: T[]) =>
  [...runs].sort((a, b) => Date.parse(b.created_at) - Date.parse(a.created_at));

/** A run picker option: the run's identity plus details, clipped to `max`; the full text with the topic for hover. */
export function runOption(run: Pick<RunOut, "name" | "field_name" | "field_version" | "topic" | "created_at" | "status">, details: string[] = [], max = 120) {
  const full = [runIdentity(run), ...details].join(" · ");
  const text = clip(full, max);
  return { text, title: run.topic ? `${full} — ${run.topic}` : full };
}
