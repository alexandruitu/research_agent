import { ApiError } from "../../api/client";
import { useWorkers } from "../../api/hooks";
import type { WorkerStatusOut } from "../../api/types";

const ROLE_LABEL: Record<string, string> = {
  plan: "Plan", screen: "Screen", screen_criteria: "Screen (per criterion)", extract: "Extract",
  review_a: "Reviewer A", review_b: "Reviewer B", adjudicate: "Adjudicator", jev: "Jev",
};

function keyText(worker: WorkerStatusOut): string {
  const detail = worker.detail ? `: ${worker.detail}` : "";
  if (!worker.key_present) return `✗ missing${detail || ": no key in the worker"}`;
  if (worker.key_accepted === true) return "✓ accepted";
  if (worker.key_accepted === false) return `✗ rejected${detail}`;
  return `present, not checked${detail}`;
}

export function ModelsTab() {
  const workers = useWorkers();
  if (workers.isLoading) return <p role="status">Loading…</p>;
  if (workers.isError) return <p role="alert" className="form-error">{workers.error instanceof ApiError ? workers.error.message : "Could not reach the server."}</p>;
  const rows = workers.data ?? [];
  return (
    <section aria-labelledby="models-heading">
      <h2 id="models-heading">AI models</h2>
      {rows.length === 0 ? (
        <p>No worker has reported yet. A worker checks its keys when it starts.</p>
      ) : (
        <table className="runs">
          <thead><tr><th scope="col">Role</th><th scope="col">Model</th><th scope="col">Key in worker</th><th scope="col">Checked</th></tr></thead>
          <tbody>
            {rows.map((worker) => (
              <tr key={`${worker.worker_id}:${worker.role}`}>
                <th scope="row">{ROLE_LABEL[worker.role] ?? worker.role}</th>
                <td>{worker.provider ?? "–"}{worker.model ? ` · ${worker.model}` : ""}</td>
                <td>{keyText(worker)}</td>
                <td>{new Date(worker.checked_at).toLocaleString()}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <p className="legend">Reported by the worker at start-up: only whether a key is present and whether a test call accepted it. Key values never leave the worker. Models are changed in the worker's environment file, not here.</p>
    </section>
  );
}
