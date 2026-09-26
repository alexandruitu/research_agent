import { Link } from "react-router-dom";

import type { RunOut } from "../../api/types";

export function RunList({ runs }: { runs: RunOut[] }) {
  if (runs.length === 0) return <p>No runs yet.</p>;
  return (
    <table className="runs">
      <thead>
        <tr><th scope="col">Field</th><th scope="col">Kind</th><th scope="col">Status</th><th scope="col">Gold set</th><th scope="col">Papers</th><th scope="col">Created</th><th scope="col"><span className="sr-only">Actions</span></th></tr>
      </thead>
      <tbody>
        {runs.map((run) => (
          <tr key={run.id}>
            <td>{run.field_name}</td>
            <td>{run.kind}</td>
            <td><span className={`pill pill--run-${run.status}`}>{run.status}</span></td>
            <td>{run.gold_set_name ?? "–"}</td>
            <td>{run.paper_count}</td>
            <td>{new Date(run.created_at).toLocaleString()}</td>
            <td><Link to={`/?run=${run.id}`}>See papers<span className="sr-only"> for {run.field_name}, {run.kind}</span></Link></td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
