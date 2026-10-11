import { useState } from "react";
import { Link } from "react-router-dom";
import { FlowStepper } from "../components/FlowStepper";

import { ApiError } from "../api/client";
import { useFields } from "../api/hooks";
import { hasRole, type FieldOut } from "../api/types";
import { useAuth } from "../auth/AuthProvider";
import { EmptyState } from "../components/ui/EmptyState";
import { Skeleton } from "../components/ui/Skeleton";
import { shortDate, sourceLabel } from "../features/fields/labels";
import { Term } from "../components/ui/Term";

const criteriaText = (field: FieldOut) => {
  const current = field.current;
  if (!current || current.include.length + current.exclude.length === 0) return "topic match (legacy)";
  const k = current.keywords;
  const terms = k ? (k.all?.length ?? 0) + (k.any?.length ?? 0) + (k.none?.length ?? 0) : 0;
  return `${current.include.length} incl · ${current.exclude.length} excl${terms ? ` · ${terms} keyword${terms === 1 ? "" : "s"}` : ""}`;
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
      <FlowStepper current={1} />
      <div className="page-head">
        <div>
          <h1>Topics</h1>
          <p className="lede">Each topic is a research question the agent searches and screens for. Every save is a new version; runs record the version they used.</p>
        </div>
        {canEdit && <Link className="button-link" to="/topics/new">New topic</Link>}
      </div>
      <label className="check"><input type="checkbox" checked={archived} onChange={(e) => setArchived(e.target.checked)} /> Show archived topics</label>
      {fields.isLoading ? (
        <Skeleton label="the topics" rows={4} />
      ) : fields.isError ? (
        <p role="alert" className="form-error">{fields.error instanceof ApiError ? fields.error.message : "Could not load the topics."}</p>
      ) : rows.length === 0 ? (
        <EmptyState title={archived ? "No topics here" : "No topics yet"} action={canEdit && !archived ? <Link className="button-link" to="/topics/new">Create your first topic</Link> : undefined}>
          {archived ? "No topic has been archived." : "A topic is a research question: a description, keywords for the search and criteria for the screen."}
        </EmptyState>
      ) : (
        <table className="runs">
          <thead>
            <tr><th scope="col">Topic</th><th scope="col"><Term k="field_version">Version</Term></th><th scope="col"><Term k="criterion">Criteria</Term></th><th scope="col">Sources</th><th scope="col">Last run</th><th scope="col"><span className="sr-only">Actions</span></th></tr>
          </thead>
          <tbody>
            {rows.map((field) => (
              <tr key={field.id}>
                <td><Link to={`/topics/${field.id}`}>{field.name}</Link><span className="sub">{field.topic}</span></td>
                <td>{versionText(field)}</td>
                <td>{criteriaText(field)}</td>
                <td>{field.current?.sources.map(sourceLabel).join(", ") || "–"}</td>
                <td>{lastRunText(field)}</td>
                <td>
                  {field.archived_at ? <span className="pill">archived</span>
                    : canEdit ? <Link to={`/screening?field=${field.id}`}>Start run{" "}<span className="sr-only">for {field.name}</span></Link> : null}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}
