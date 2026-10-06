import type { RunOut, UserOut } from "../../api/types";

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
