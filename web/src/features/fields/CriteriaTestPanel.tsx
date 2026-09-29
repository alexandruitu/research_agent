import { useJob } from "../../api/hooks";
import type { CriteriaTestResult, JobProgressData } from "../../api/types";
import { criterionLabel, sourceLabel } from "./labels";

const DECISION: Record<string, string> = { include: "kept", exclude: "dropped", escalate: "to the LLM", not_screened: "not screened (no abstract)" };

function statusText(status: string | undefined, progress: JobProgressData): string {
  if (!status) return "Waiting for the worker…";
  if (status === "queued") return "Queued: waiting for the worker…";
  if (status === "running") return progress.total ? `Testing: ${progress.done ?? 0} of ${progress.total} papers` : "Searching the sources…";
  if (status === "done") return "Test finished.";
  return "The test did not finish.";
}

function TestResults({ result }: { result: CriteriaTestResult }) {
  const { summary } = result;
  return (
    <>
      <p>
        <strong>{summary.total} papers</strong> · {summary.kept} kept · {summary.dropped} dropped · {summary.to_llm} to the LLM
        {summary.not_screened ? ` · ${summary.not_screened} not screened` : ""}
      </p>
      <p className="sub">
        {result.mode === "demo" ? "Demo mode: the numbers come from an offline stand-in, not from Jev." : `Model: ${result.model_version ?? "unknown"}.`}{" "}
        Sources: {result.sources.map(sourceLabel).join(", ")}. The cell that decided a paper says “decided”.
      </p>
      {result.papers.length === 0 ? (
        <p>The sources returned no papers for this topic.</p>
      ) : (
        <div className="table-scroll">
          <table className="papers test">
            <caption className="sr-only">Jev probability per criterion for each paper</caption>
            <thead>
              <tr>
                <th scope="col">Paper</th>
                {result.criteria.map((c) => <th scope="col" key={c.key}><abbr title={c.text}>{criterionLabel(c.key)}</abbr></th>)}
                <th scope="col">Decision</th>
              </tr>
            </thead>
            <tbody>
              {result.papers.map((paper, index) => (
                <tr key={`${paper.source_id}:${index}`}>
                  <th scope="row">{paper.title}<span className="sub">{paper.year ?? ""} {paper.source_id}</span></th>
                  {result.criteria.map((c) => {
                    const p = paper.probabilities[c.key];
                    const decided = paper.decided_by === c.key;
                    return (
                      <td key={c.key} className={decided ? "decider" : undefined}>
                        {p === undefined ? "–" : p.toFixed(2)}{decided && <strong> decided</strong>}
                      </td>
                    );
                  })}
                  <td>{DECISION[paper.decision] ?? paper.decision}{paper.decided_by ? ` · ${criterionLabel(paper.decided_by)}` : ""}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <dl className="criteria-legend">
        {result.criteria.map((c) => (
          <div key={c.key}><dt>{criterionLabel(c.key)}</dt><dd>{c.text}</dd></div>
        ))}
      </dl>
    </>
  );
}

/** Follows a criteria_test job; nothing it shows is written to Papers. */
export function CriteriaTestPanel({ jobId }: { jobId: string }) {
  const job = useJob(jobId);
  const progress = (job.data?.progress ?? {}) as JobProgressData;
  const result = job.data?.status === "done" ? (progress.result as CriteriaTestResult | undefined) : undefined;
  return (
    <section aria-label="Criteria test" className="test-panel">
      <h2>Criteria test</h2>
      <p className="sub">Jev only, at most 20 papers from the field's sources. Nothing is written to Papers.</p>
      <p role="status">{job.isError ? "" : statusText(job.data?.status, progress)}</p>
      {job.isError && <p role="alert" className="form-error">Could not read the test status.</p>}
      {job.data?.status === "failed" && <p role="alert" className="form-error">The test failed: {job.data.error ?? "no details were stored."}</p>}
      {result && <TestResults result={result} />}
    </section>
  );
}
