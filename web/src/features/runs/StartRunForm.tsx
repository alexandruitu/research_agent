import { useState, type FormEvent } from "react";

import { ApiError } from "../../api/client";
import { useFields, useStartRun } from "../../api/hooks";
import { TermHint } from "../../components/ui/Term";

export const MAX_PAPERS = 12;

export function StartRunForm({ onStarted, initialFieldId = "" }: { onStarted: (jobId: string) => void; initialFieldId?: string }) {
  const fields = useFields();
  const start = useStartRun();
  const [fieldId, setFieldId] = useState(initialFieldId);
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
      if (error instanceof ApiError && error.code === "no_enabled_source") {
        setProblem(`${error.message}. An admin can enable a source in Settings → Sources, or edit the field to use an enabled one.`);
      } else {
        setProblem(error instanceof ApiError ? error.message : "Could not reach the server.");
      }
    }
  };

  return (
    <form onSubmit={submit} className="start-run" aria-label="Start a run">
      <label>Field
        <select value={fieldId} onChange={(e) => setFieldId(e.target.value)}>
          <option value="">Choose…</option>
          {fields.data?.map((field) => <option key={field.id} value={field.id}>{field.name} · v{field.current_version ?? 1}</option>)}
        </select>
      </label>
      <label>Papers to screen
        <input inputMode="numeric" value={papers} onChange={(e) => setPapers(e.target.value)} />
      </label>
      <span className="check-with-term"><label className="check"><input type="checkbox" checked={demo} onChange={(e) => setDemo(e.target.checked)} /> Demo mode (no model calls)</label><TermHint k="demo_mode" /></span>
      <button type="submit" disabled={start.isPending}>Start run</button>
      {problem && <p role="alert" className="form-error">{problem}</p>}
    </form>
  );
}
