import { useState } from "react";

import { useEvals, useFieldVersion, useRuns } from "../../api/hooks";
import type { FieldOut } from "../../api/types";
import { shortDate } from "./labels";
import { diffVersions, hasChanges } from "./versionDiff";

const runCount = (n: number) => (n === 1 ? "1 run" : `${n} runs`);

/** Measured only when an eval exists for a run of this field at its current version. */
function Measurement({ field }: { field: FieldOut }) {
  const runs = useRuns();
  const evals = useEvals();
  const current = field.current_version ?? 1;
  if (runs.isLoading || evals.isLoading) return <p className="sub">Checking measurements…</p>;
  const runIds = new Set((runs.data ?? []).filter((r) => r.field_id === field.id && (r.field_version ?? 1) === current).map((r) => r.id));
  const golds = [...new Set((evals.data ?? []).filter((e) => runIds.has(e.run_id)).map((e) => e.gold_set.name))];
  if (golds.length > 0) return <p className="banner">Screening for this field (v{current}): measured against {golds.join(", ")}.</p>;
  return <p className="banner banner--warn">Screening for this field (v{current}): not measured. No eval against a published review has used this version yet.</p>;
}

function VersionDiff({ fieldId, versions }: { fieldId: string; versions: number[] }) {
  const [from, setFrom] = useState(versions[1] ?? versions[0] ?? 1);
  const [to, setTo] = useState(versions[0] ?? 1);
  const before = useFieldVersion(fieldId, from);
  const after = useFieldVersion(fieldId, to);
  const sections = before.data && after.data ? diffVersions(before.data, after.data) : null;
  const options = versions.map((v) => <option key={v} value={v}>v{v}</option>);
  return (
    <div className="diff">
      <h3>Compare versions</h3>
      <div className="actions">
        <label>Compare from <select value={from} onChange={(e) => setFrom(Number(e.target.value))}>{options}</select></label>
        <label>to <select value={to} onChange={(e) => setTo(Number(e.target.value))}>{options}</select></label>
      </div>
      {before.isError || after.isError ? (
        <p role="alert" className="form-error">Could not load a version.</p>
      ) : !sections ? (
        <p className="sub">Loading…</p>
      ) : !hasChanges(sections) ? (
        <p>No differences.</p>
      ) : (
        sections.filter((s) => s.lines.some((line) => line.change !== "unchanged")).map((section) => (
          <div key={section.title}>
            <h4>{section.title}</h4>
            <ul className="diff-lines">
              {section.lines.map((line, i) => (
                <li key={i}><span className={`diff-tag diff-tag--${line.change}`}>{line.change}</span> {line.text}</li>
              ))}
            </ul>
          </div>
        ))
      )}
    </div>
  );
}

export function FieldSidePanel({ field }: { field: FieldOut }) {
  const versions = field.versions ?? [];
  return (
    <aside aria-label="Field history" className="side-panel">
      <h2>History</h2>
      <Measurement field={field} />
      <ol className="versions">
        {versions.map((v) => (
          <li key={v.version}>
            <strong>v{v.version}</strong> · {v.imported ? "imported" : (v.created_by_name ?? "unknown author")} · {shortDate(v.created_at)}
            <span className="sub">{v.note || "No change note."}</span>
            <span className="sub">{v.include_count + v.exclude_count === 0 ? "topic match" : `${v.include_count} incl · ${v.exclude_count} excl`} · {runCount(v.run_count)}</span>
          </li>
        ))}
      </ol>
      {versions.length > 1 && <VersionDiff fieldId={field.id} versions={versions.map((v) => v.version)} />}
    </aside>
  );
}
