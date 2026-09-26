import { useState, type FormEvent } from "react";

import { ApiError } from "../../api/client";
import { useFields, useStartRun } from "../../api/hooks";

export const MAX_PAPERS = 12;

export function StartRunForm({ onStarted }: { onStarted: (jobId: string) => void }) {
  const fields = useFields();
  const start = useStartRun();
  const [fieldId, setFieldId] = useState("");
  const [papers, setPapers] = useState("5");
  const [demo, setDemo] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    const count = Number(papers);
    if (!fieldId) return setProblem("Choose a field.");
    if (!Number.isInteger(count) || count < 1 || count > MAX_PAPERS) return setProblem(`Choose between 1 and ${MAX_PAPERS} papers.`);
    setProblem(null);
    try {
      const started = await start.mutateAsync({ field_id: fieldId, max_papers: count, mode: demo ? "demo" : "live" });
      onStarted(started.job.id);
    } catch (error) {
      setProblem(error instanceof ApiError ? error.message : "Could not reach the server.");
    }
  };

  return (
    <form onSubmit={submit} className="start-run" aria-label="Start a run">
      <label>Field
        <select value={fieldId} onChange={(e) => setFieldId(e.target.value)}>
          <option value="">Choose…</option>
          {fields.data?.map((field) => <option key={field.id} value={field.id}>{field.name}</option>)}
        </select>
      </label>
      <label>Papers to screen
        <input inputMode="numeric" value={papers} onChange={(e) => setPapers(e.target.value)} />
      </label>
      <label className="check"><input type="checkbox" checked={demo} onChange={(e) => setDemo(e.target.checked)} /> Demo mode (no model calls)</label>
      <button type="submit" disabled={start.isPending}>Start run</button>
      {problem && <p role="alert" className="form-error">{problem}</p>}
    </form>
  );
}
