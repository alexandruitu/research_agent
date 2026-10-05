import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import { useEvalJobs, useEvals } from "../api/hooks";
import { hasRole, type EvalKind } from "../api/types";
import { useAuth } from "../auth/AuthProvider";
import { EmptyState } from "../components/ui/EmptyState";
import { Skeleton } from "../components/ui/Skeleton";
import { EvalJobs } from "../features/evals/EvalJobs";
import { ReportCard } from "../features/evals/ReportCard";
import { KIND_LABEL, KIND_WHAT, familyOf } from "../features/evals/words";

const FILTERS: (EvalKind | null)[] = [null, "screening", "panel", "ablation", "human"];

export function EvalsHomePage() {
  const { user } = useAuth();
  const canRun = hasRole(user, "member");
  const [kind, setKind] = useState<EvalKind | null>(null);
  const [picked, setPicked] = useState<string[]>([]);
  const navigate = useNavigate();
  const reports = useEvals(kind);
  const all = useEvals();
  const jobs = useEvalJobs();
  const byId = new Map((all.data ?? []).map((r) => [r.id, r]));
  const families = new Set(picked.map((id) => familyOf(byId.get(id)?.kind)));
  const compareProblem = picked.length < 2 ? "Pick 2 or 3 reports." : picked.length > 3 ? "At most 3 reports." : families.size > 1 ? "Pick reports of the same family: screening; review panel and human reference; or 1 / 2 / 3 reviewers." : null;
  const toggle = (id: string, on: boolean) => setPicked((list) => (on ? [...list, id] : list.filter((x) => x !== id)));
  const newButton = canRun ? <Link to="/evals/new" className="button-link">New evaluation</Link> : null;

  return (
    <section className="evals-home">
      <div className="page-head evals-head">
        <div>
          <h1>Evals</h1>
          <p className="lede">Each evaluation is a frozen, citable measurement of one part of the pipeline. Start one, watch it run, compare it with earlier ones.</p>
        </div>
        {newButton}
      </div>
      {jobs.data && <EvalJobs jobs={jobs.data} />}
      <div className="segmented-buttons eval-filter" role="group" aria-label="Show">
        {FILTERS.map((k) => <button key={k ?? "all"} type="button" aria-pressed={kind === k} onClick={() => setKind(k)}>{k ? KIND_LABEL[k] : "All"}</button>)}
      </div>
      {reports.isLoading ? (
        <Skeleton label="the evaluations" rows={4} />
      ) : reports.isError ? (
        <p role="alert" className="form-error">Could not load the evaluations.</p>
      ) : !reports.data?.length ? (
        <EmptyState title={kind ? `No ${KIND_LABEL[kind].toLowerCase()} evaluations yet` : "No evaluations yet"} action={newButton}>
          <dl className="kind-guide">
            {(Object.keys(KIND_WHAT) as EvalKind[]).map((k) => <div key={k}><dt>{KIND_LABEL[k]}</dt><dd>{KIND_WHAT[k]}</dd></div>)}
          </dl>
          {!canRun && <p>Ask a member to start one; you can read every report.</p>}
        </EmptyState>
      ) : (
        <div className="eval-grid">
          {reports.data.map((r) => (
            <ReportCard key={r.id} report={r} parent={r.parent_id ? byId.get(r.parent_id) : undefined} children={(all.data ?? []).filter((c) => c.parent_id === r.id)} selected={picked.includes(r.id)} onSelect={(on) => toggle(r.id, on)} />
          ))}
        </div>
      )}
      {picked.length > 0 && (
        <section aria-label="Compare" className="compare-bar">
          <p><strong>{picked.length} selected.</strong> {compareProblem ?? "Ready to compare side by side."}</p>
          <button type="button" className="primary" disabled={!!compareProblem} onClick={() => navigate(`/evals/compare?ids=${picked.join(",")}`)}>Compare {picked.length}</button>
          <button type="button" onClick={() => setPicked([])}>Clear</button>
        </section>
      )}
    </section>
  );
}
