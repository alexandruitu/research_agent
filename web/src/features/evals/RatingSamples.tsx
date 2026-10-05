import { useState, type FormEvent } from "react";
import { Link } from "react-router-dom";

import { ApiError } from "../../api/client";
import { useCreateRatingSample, useRatingSample } from "../../api/hooks";
import { hasRole } from "../../api/types";
import { useAuth } from "../../auth/AuthProvider";
import { dateText } from "./words";

function SampleRow({ id }: { id: string }) {
  const sample = useRatingSample(id);
  if (!sample.data) return <li>{sample.isError ? "Could not load this sample." : "Loading sample…"}</li>;
  const s = sample.data;
  const left = s.papers.filter((p) => !p.rated_by_me).length;
  return (
    <li className="sample-row">
      <span><strong>{s.papers.length} papers</strong> · created {dateText(s.created_at)} · {s.complete_papers} of {s.papers.length} papers have {s.raters_needed} raters · you rated {s.my_rated}</span>
      {left > 0 ? <Link className="button-link" to={`/rate/${s.id}`}>Rate papers<span className="sr-only"> in this sample</span> ({left} left for you)</Link> : <span>✓ you rated every paper</span>}
      {s.latest_human_eval_id && <Link to={`/evals/${s.latest_human_eval_id}`}>Latest human reference report</Link>}
    </li>
  );
}

export function RatingSamples({ evalId, sampleIds, allowCreate = true }: { evalId: string; sampleIds: string[]; allowCreate?: boolean }) {
  const { user } = useAuth();
  const admin = allowCreate && hasRole(user, "admin");
  const create = useCreateRatingSample(evalId);
  const [size, setSize] = useState("20");
  const [problem, setProblem] = useState<string | null>(null);
  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setProblem(null);
    try {
      await create.mutateAsync({ size: Number(size) || 20, seed: 0 });
    } catch (error) {
      setProblem(error instanceof ApiError ? error.message : "Could not reach the server.");
    }
  };
  return (
    <section aria-label="Human reference ratings" className="report-section">
      <h2>Human reference ratings</h2>
      <p className="lede-sm">A rating sample picks papers across the panel's score range. People answer the same checklist without seeing the models' answers; two raters per paper are recommended.</p>
      {sampleIds.length === 0 ? <p>No rating sample yet{admin ? "." : ": an admin can create one from the panel report."}</p> : <ul className="sample-list">{sampleIds.map((id) => <SampleRow key={id} id={id} />)}</ul>}
      {admin && (
        <form onSubmit={submit} className="inline">
          <label>Papers<input inputMode="numeric" value={size} onChange={(e) => setSize(e.target.value)} size={4} /></label>
          <button type="submit" disabled={create.isPending}>Create rating sample</button>
          {problem && <span role="alert" className="form-error">{problem}</span>}
        </form>
      )}
    </section>
  );
}
