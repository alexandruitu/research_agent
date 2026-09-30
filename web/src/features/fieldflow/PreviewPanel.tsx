import { useJob } from "../../api/hooks";
import type { JobProgressData, PreviewResult } from "../../api/types";
import { Skeleton } from "../../components/ui/Skeleton";
import { sourceLabel } from "../fields/labels";

const count = (n: number | null) => (n === null ? "count not reported" : `${n.toLocaleString("en-US")} paper${n === 1 ? "" : "s"}`);

/** Follows a field_preview job: per source the hit count the source reports, 10 titles, the exact query. */
export function PreviewPanel({ jobId }: { jobId: string }) {
  const job = useJob(jobId);
  const status = job.data?.status;
  const result = status === "done" ? ((job.data?.progress ?? {}) as JobProgressData).result as PreviewResult | undefined : undefined;
  return (
    <section aria-label="Search preview" className="preview-panel">
      {job.isError && <p role="alert" className="form-error">Could not read the preview status.</p>}
      {status === "failed" && <p role="alert" className="form-error">The preview failed: {job.data?.error ?? "no details were stored."}</p>}
      {!result && !job.isError && status !== "failed" && <Skeleton label="the preview" rows={3} />}
      {result && (
        <>
          {result.mode === "demo" && <p className="hint">Demo mode: offline stand-in results, not the real sources.</p>}
          <div className="preview-grid">
            {result.sources.map((row) => (
              <article key={row.source} className="preview-source">
                <header>
                  <h4>{sourceLabel(row.source)}</h4>
                  {row.error ? <span className="status-word status-word--bad"><span aria-hidden="true">!</span> failed</span>
                    : <strong className="preview-count tnum">{count(row.count)}</strong>}
                </header>
                {row.error ? (
                  <p className="form-error">{row.error}</p>
                ) : row.papers.length === 0 ? (
                  <p className="sub">No papers: loosen the keywords or the years.</p>
                ) : (
                  <ol className="preview-titles">
                    {row.papers.map((p) => <li key={p.id}><span className="serif">{p.title}</span> <span className="sub-inline">{p.year ?? ""}</span></li>)}
                  </ol>
                )}
                {(row.effective_query ?? row.query) && (
                  <details className="disclosure"><summary>Exact query</summary><code className="query-text">{row.effective_query ?? row.query}</code></details>
                )}
              </article>
            ))}
          </div>
        </>
      )}
    </section>
  );
}
