import { useState } from "react";
import { Link } from "react-router-dom";

import { ApiError } from "../api/client";
import { useFields } from "../api/hooks";
import { hasRole, type FieldOut } from "../api/types";
import { useAuth } from "../auth/AuthProvider";
import { shortDate, sourceLabel } from "../features/fields/labels";

const criteriaText = (field: FieldOut) => {
  const current = field.current;
  if (!current || current.include.length + current.exclude.length === 0) return "topic match (legacy)";
  return `${current.include.length} incl · ${current.exclude.length} excl`;
};

const versionText = (field: FieldOut) => {
  const current = field.current;
  if (!current) return `v${field.current_version ?? 1}`;
  return `v${current.version} · ${current.imported ? "imported" : (current.created_by_name ?? "unknown author")} · ${shortDate(current.created_at)}`;
};

const lastRunText = (field: FieldOut) => {
  const run = field.last_run;
  if (!run) return "none yet";
  return `${run.status} · ${run.kind}${run.field_version ? ` · v${run.field_version}` : ""} · ${shortDate(run.created_at)}`;
};

export function FieldsPage() {
  const { user } = useAuth();
  const [archived, setArchived] = useState(false);
  const fields = useFields({ archived });
  const canEdit = hasRole(user, "member");
  const rows = fields.data ?? [];
  return (
    <section>
      <div className="page-head">
        <h1>Fields</h1>
        {canEdit && <Link className="button-link" to="/fields/new">New field</Link>}
      </div>
      <label className="check"><input type="checkbox" checked={archived} onChange={(e) => setArchived(e.target.checked)} /> Show archived fields</label>
      {fields.isLoading ? (
        <p role="status">Loading…</p>
      ) : fields.isError ? (
        <p role="alert" className="form-error">{fields.error instanceof ApiError ? fields.error.message : "Could not load the fields."}</p>
      ) : rows.length === 0 ? (
        <p>No fields yet.</p>
      ) : (
        <table className="runs">
          <thead>
            <tr><th scope="col">Field</th><th scope="col">Version</th><th scope="col">Criteria</th><th scope="col">Sources</th><th scope="col">Last run</th><th scope="col"><span className="sr-only">Actions</span></th></tr>
          </thead>
          <tbody>
            {rows.map((field) => (
              <tr key={field.id}>
                <td><Link to={`/fields/${field.id}`}>{field.name}</Link><span className="sub">{field.topic}</span></td>
                <td>{versionText(field)}</td>
                <td>{criteriaText(field)}</td>
                <td>{field.current?.sources.map(sourceLabel).join(", ") || "–"}</td>
                <td>{lastRunText(field)}</td>
                <td>
                  {field.archived_at ? <span className="pill">archived</span>
                    : canEdit ? <Link to={`/runs?field=${field.id}`}>Start run{" "}<span className="sr-only">for {field.name}</span></Link> : null}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}
