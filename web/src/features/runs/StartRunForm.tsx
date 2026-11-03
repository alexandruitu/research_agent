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
    if (!fieldId) return setProblem(fields.data?.length === 0 ? "There is no topic yet: create one under Topics first." : "Choose a topic in the list, then start the search.");
    if (!Number.isInteger(count) || count < 1 || count > MAX_PAPERS) return setProblem(`Choose between 1 and ${MAX_PAPERS} papers.`);
    setProblem(null);
    try {
      const started = await start.mutateAsync({ field_id: fieldId, max_papers: count, mode: demo ? "demo" : "live" });
      onStarted(started.job.id);
    } catch (error) {
      if (error instanceof ApiError && error.code === "no_enabled_source") {
        setProblem(`${error.message}. An admin can enable a source in Settings → Sources, or edit the topic to use an enabled one.`);
      } else {
        setProblem(error instanceof ApiError ? `${error.message}${/[.!?]$/.test(error.message) ? "" : "."} Fix that, then press Start a search again.` : "Could not reach the server. Check your connection and press Start a search again.");
      }
    }
  };

  return (
    <form onSubmit={submit} className="start-run" aria-label="Start a search">
      <label>Topic
        <select value={fieldId} onChange={(e) => setFieldId(e.target.value)}>
          <option value="">Choose…</option>
          {fields.data?.map((field) => <option key={field.id} value={field.id}>{field.name} · v{field.current_version ?? 1}</option>)}
        </select>
      </label>
      <label>Papers to review (at most {MAX_PAPERS})
        <input inputMode="numeric" value={papers} onChange={(e) => setPapers(e.target.value)} />
      </label>
      <span className="check-with-term"><label className="check"><input type="checkbox" checked={demo} onChange={(e) => setDemo(e.target.checked)} /> Demo mode (no model calls)</label><TermHint k="demo_mode" /></span>
      <button type="submit" disabled={start.isPending}>Start a search</button>
      {problem && <p role="alert" className="form-error">{problem}</p>}
    </form>
  );
}
