import { Link } from "react-router-dom";

import { useJob } from "../../api/hooks";
import type { RelatedPaper, RelatedResult } from "../../api/types";

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

/** One Find related / Earlier work answer: a search (sources + team library + past runs) for the key terms. */
export function RelatedCard({ jobId }: { jobId: string }) {
  const job = useJob(jobId);
  const status = job.data?.status;
  const result = status === "done" ? ((job.data!.progress as { result?: RelatedResult }).result ?? null) : null;
  return (
    <li className="answer-card answer-card--related">
      {(!status || status === "queued" || status === "running") && <p role="status">Searching…</p>}
      {status === "failed" && <p role="alert" className="form-error">No results: {job.data?.error ?? "the search failed"}.</p>}
      {result && (
        <>
          <h3>{result.mode === "earlier" ? "Earlier work" : "Related papers"} ({result.results.length})</h3>
          <Results result={result} />
        </>
      )}
    </li>
  );
}
