import { useQueryClient } from "@tanstack/react-query";
import { useEffect } from "react";

import { keys, useJob } from "../../api/hooks";

const WORDS: Record<string, string> = { queued: "queued", running: "running", done: "done", failed: "failed" };

/** Follows one job. `useJob` polls every 2 seconds until the job is done or failed. */
export function JobProgress({ jobId }: { jobId: string }) {
  const job = useJob(jobId);
  const client = useQueryClient();
  const finished = job.data?.status === "done" || job.data?.status === "failed";
  // The run list was loaded while the run was queued; refresh it once the run has finished.
  useEffect(() => {
    if (finished) void client.invalidateQueries({ queryKey: keys.runs });
  }, [finished, client]);
  if (job.isError) return <p role="alert" className="form-error">Could not read the job status.</p>;
  const stages = Object.entries((job.data?.progress as { stages?: Record<string, string> } | undefined)?.stages ?? {});
  return (
    // One stable wrapper, so the element a screen reader is on does not get replaced when data arrives.
    <div role="status" aria-label="Run progress" className="job">
      {!job.data ? (
        <p>Waiting for the worker…</p>
      ) : (
        <>
          <p><strong>{WORDS[job.data.status] ?? job.data.status}</strong>{job.data.attempts > 1 ? ` · attempt ${job.data.attempts}` : ""}</p>
          {stages.length > 0 && <ul>{stages.map(([stage, state]) => <li key={stage}>{stage}: {state}</li>)}</ul>}
          {job.data.error && <p className="form-error">{job.data.error}</p>}
        </>
      )}
    </div>
  );
}
