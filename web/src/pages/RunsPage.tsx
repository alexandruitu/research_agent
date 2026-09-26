import { useState } from "react";

import { ApiError } from "../api/client";
import { useFields, useResumeRun, useRuns } from "../api/hooks";
import { hasRole } from "../api/types";
import { useAuth } from "../auth/AuthProvider";
import { JobProgress } from "../features/runs/JobProgress";
import { RunList } from "../features/runs/RunList";
import { StartRunForm } from "../features/runs/StartRunForm";

export function RunsPage() {
  const { status, user } = useAuth();
  const runs = useRuns();
  const resume = useResumeRun();
  const [jobId, setJobId] = useState<string | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const canRun = hasRole(user, "member");
  // Members get the start form; render the page once its field list is known, so the form never
  // appears with an empty field picker that fills in a moment later.
  const fields = useFields(canRun);

  const doResume = async (runId: string) => {
    setProblem(null);
    try {
      setJobId((await resume.mutateAsync(runId)).job.id);
    } catch (error) {
      setProblem(error instanceof ApiError ? error.message : "Could not reach the server.");
    }
  };

  if (status === "loading" || runs.isLoading || (canRun && fields.isPending)) return <p role="status">Loading…</p>;
  if (runs.isError) return <p role="alert">Could not load the runs.</p>;
  const failed = runs.data?.filter((run) => run.status === "failed") ?? [];

  return (
    <section>
      <h1>Runs</h1>
      {canRun && <StartRunForm onStarted={setJobId} />}
      {jobId && <JobProgress jobId={jobId} />}
      {failed.map((run) => (
        <div key={run.id} role="alert" className="banner banner--bad">
          <p><strong>{run.field_name} · {run.kind} failed.</strong> {run.error ?? "No details were stored."}</p>
          {canRun && run.kind === "research" && <button type="button" onClick={() => doResume(run.id)} disabled={resume.isPending}>Resume</button>}
        </div>
      ))}
      {problem && <p role="alert" className="form-error">{problem}</p>}
      <RunList runs={runs.data ?? []} />
    </section>
  );
}
