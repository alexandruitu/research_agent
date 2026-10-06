import { Link } from "react-router-dom";

import type { RunOut } from "../../api/types";
import { EmptyState } from "../../components/ui/EmptyState";
import { MenuButton, type MenuItem } from "../../components/ui/MenuButton";
import { runLabel, runStatusMeta } from "./runWords";

export function RunStatus({ status }: { status: string }) {
  const meta = runStatusMeta(status);
  return <span className={`pill pill--run-${status}`}><span aria-hidden="true">{meta.icon}</span> {meta.word}</span>;
}

/**
 * The runs table: a checkbox per run (bulk actions), the run's name (a link to its page) with pin and note
 * marks, status in words, papers, who started it, when, and a menu of actions per row.
 */
export function RunList({ runs, selected, onToggle, onToggleAll, items, filtered }: {
  runs: RunOut[];
  selected: Set<string>;
  onToggle: (id: string) => void;
  onToggleAll: () => void;
  items: (run: RunOut) => MenuItem[];
  filtered: boolean;
}) {
  if (runs.length === 0) {
    return filtered ? (
      <EmptyState title="No runs match these filters">Clear a filter or the search to see more runs.</EmptyState>
    ) : (
      <EmptyState title="No runs yet">
        A run searches a field's sources, screens what it finds and reviews what it keeps. Choose a field above and start one; demo mode runs offline.
      </EmptyState>
    );
  }
  const all = runs.every((run) => selected.has(run.id));
  return (
    <table className="runs runs--ledger">
      <thead>
        <tr>
          <th scope="col" className="runs__check"><input type="checkbox" aria-label="Select every run shown" checked={all} onChange={onToggleAll} /></th>
          <th scope="col">Run</th><th scope="col">Kind</th><th scope="col">Status</th><th scope="col">Papers</th>
          <th scope="col">Started by</th><th scope="col">Created</th><th scope="col"><span className="sr-only">Actions</span></th>
        </tr>
      </thead>
      <tbody>
        {runs.map((run) => {
          const label = runLabel(run);
          return (
            <tr key={run.id} className={`runs__row runs__row--${run.status}${selected.has(run.id) ? " is-selected" : ""}`}>
              <td className="runs__check"><input type="checkbox" aria-label={`Select ${label}`} checked={selected.has(run.id)} onChange={() => onToggle(run.id)} /></td>
              <th scope="row">
                <Link to={`/runs/${run.id}`} className="runs__name">{label}</Link>
                {run.pinned && <span className="runs__mark" title="Pinned"><span aria-hidden="true">📌</span><span className="sr-only"> pinned</span></span>}
                {run.name && <span className="runs__sub">{run.field_name}{run.field_version ? ` · v${run.field_version}` : ""}</span>}
                {run.note && <span className="runs__note">{run.note}</span>}
                {run.status === "failed" && run.error && <span className="runs__error" title={run.error}>{shortError(run.error)}</span>}
              </th>
              <td>{run.kind}{run.gold_set_name ? ` · ${run.gold_set_name}` : ""}</td>
              <td><RunStatus status={run.status} /></td>
              <td className="num">{run.paper_count}</td>
              <td>{run.created_by_name ?? "imported"}</td>
              <td className="runs__date"><time dateTime={run.created_at} title={new Date(run.created_at).toLocaleString()}>{shortDate(run.created_at)}</time></td>
              <td className="runs__actions">
                <Link to={`/?run=${run.id}`}>Papers<span className="sr-only"> of {label}</span></Link>
                <MenuButton label={`Actions for ${label}`} text="Actions" items={items(run)} />
              </td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

/** "failed at stage 'review_methodologist': EvidenceQuoteError: …" → "Failed at review methodologist (EvidenceQuoteError)". */
export function shortError(error: string): string {
  const m = /failed at stage '([^']+)':\s*([A-Za-z]+)/.exec(error);
  if (m) return `Failed at ${m[1].replace(/_/g, " ")} (${m[2]})`;
  return error.length > 90 ? `${error.slice(0, 87)}…` : error;
}

export function shortDate(iso: string): string {
  return new Date(iso).toLocaleString(undefined, { day: "numeric", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" });
}
