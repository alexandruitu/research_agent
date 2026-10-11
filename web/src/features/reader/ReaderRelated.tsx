import { useState } from "react";
import { Link } from "react-router-dom";

import { ApiError } from "../../api/client";
import { useJob, useReaderRelated } from "../../api/hooks";
import type { RelatedMode, RelatedPaper, RelatedResult } from "../../api/types";

const errorText = (error: unknown) => (error instanceof ApiError ? error.message : "Could not reach the server.");
const yearOf = (row: RelatedPaper) => (row.year && /^\d{4}/.test(row.year) ? Number(row.year.slice(0, 4)) : null);

function Row({ row }: { row: RelatedPaper }) {
  const seen = row.seen_in_runs[0];
  return (
    <li className="reader-related-item">
      {row.url ? <a href={row.url} target="_blank" rel="noopener noreferrer">{row.title}<span className="sr-only"> (opens in a new tab)</span></a> : <span>{row.title}</span>}
      <span className="sub"> · {row.year ?? "year unknown"}{row.sources.length ? ` · ${row.sources.join(", ")}` : ""}{row.doi ? ` · doi:${row.doi}` : ""}</span>
      {" "}
      {row.in_library && <span className="chip">in library</span>}
      {seen && row.paper_id && (
        <span className="chip">seen in run <Link to={`/read/${seen.id}/${row.paper_id}`}>{seen.name}</Link>{row.seen_in_runs.length > 1 ? ` +${row.seen_in_runs.length - 1}` : ""}</span>
      )}
    </li>
  );
}

function Results({ result }: { result: RelatedResult }) {
  const queries = Object.entries(result.queries);
  const own = result.paper_year;
  const before = result.mode === "earlier" && own != null ? result.results.filter((r) => (yearOf(r) ?? Infinity) < own) : [];
  const rest = result.mode === "earlier" && own != null ? result.results.filter((r) => !before.includes(r)) : result.results;
  return (
    <div className="reader-related">
      <p className="sub">
        Searched for {result.basis === "title" ? "the paper's title" : "the selection"} by key terms (code, no AI): {result.terms.map((t) => `“${t}”`).join(", ")}
        {result.search_mode === "demo" ? " · demo results (test data)" : ""}
      </p>
      {queries.length > 0 && (
        <details>
          <summary>Queries sent</summary>
          <ul>{queries.map(([source, q]) => <li key={source}><strong>{source}</strong>: <code>{q}</code></li>)}</ul>
        </details>
      )}
      {result.warnings.length > 0 && (
        <div role="alert" className="chip--warn reader-related-warnings">
          <p>Some sources did not answer; the results are partial.</p>
          <ul>{result.warnings.map((w) => <li key={w.source}>{w.source}: {w.reason}. {w.detail}</li>)}</ul>
        </div>
      )}
      {result.results.length === 0 ? (
        <p>No matching papers in the sources, the team library or past runs.</p>
      ) : result.mode === "earlier" ? (
        <>
          {own == null ? <p className="sub">This paper's year is unknown, so all results are listed by year.</p> : (
            <>
              <h4>Papers mentioning this before {own}</h4>
              {before.length ? <ol className="reader-related-list">{before.map((r, i) => <Row key={i} row={r} />)}</ol> : <p>None found before {own}.</p>}
              <p className="reader-related-self"><strong>This paper: {own}</strong></p>
              <h4>Same year or later</h4>
            </>
          )}
          {rest.length ? <ol className="reader-related-list">{rest.map((r, i) => <Row key={i} row={r} />)}</ol> : <p>None.</p>}
          <p className="sub">A list of papers found by the search, sorted by year. It does not judge whether this paper's idea was new.</p>
        </>
      ) : (
        <ol className="reader-related-list">{result.results.map((r, i) => <Row key={i} row={r} />)}</ol>
      )}
    </div>
  );
}

/** Find related / Earlier work: a search (sources + team library + past runs) for the selection's key terms. */
export function ReaderRelated({ runId, paperId, selection, disabled }: { runId: string; paperId: string; selection: string; disabled: boolean }) {
  const start = useReaderRelated(runId, paperId);
  const [jobId, setJobId] = useState<string | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const job = useJob(jobId);
  const running = start.isPending || ["queued", "running"].includes(job.data?.status ?? "");
  const result = job.data?.status === "done" ? ((job.data.progress as { result?: RelatedResult }).result ?? null) : null;

  const run = async (mode: RelatedMode) => {
    setProblem(null);
    try {
      setJobId((await start.mutateAsync({ mode, selection })).id);
    } catch (error) {
      setProblem(errorText(error));
    }
  };

  return (
    <section aria-labelledby="reader-related-heading">
      <h3 id="reader-related-heading">Related and earlier work</h3>
      <div className="actions">
        <button type="button" disabled={running || disabled} onClick={() => void run("related")}>Find related</button>
        <button type="button" disabled={running || disabled} onClick={() => void run("earlier")}>Earlier work</button>
      </div>
      <p className="sub">Searches the enabled sources (10 results each), the team library and past runs for the key terms of {selection ? "the selection" : "the paper's title"}.</p>
      <div aria-live="polite">
        {running && <p role="status">Searching…</p>}
        {problem && <p role="alert" className="form-error">{problem}</p>}
        {job.data?.status === "failed" && <p role="alert" className="form-error">No results: {job.data.error ?? "the search failed"}.</p>}
        {result && (
          <>
            <h4>{result.mode === "earlier" ? "Earlier work" : "Related papers"} ({result.results.length})</h4>
            <Results result={result} />
          </>
        )}
      </div>
    </section>
  );
}
