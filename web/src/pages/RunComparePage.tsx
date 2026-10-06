import { Link, useSearchParams } from "react-router-dom";

import { useRunCompare, useRuns } from "../api/hooks";
import type { ComparePaper, RunCompareOut } from "../api/types";
import { Skeleton } from "../components/ui/Skeleton";
import { runLabel, runOption } from "../features/runs/runWords";

/** Two runs side by side: what differed in how they were started, and which papers came out differently. */
export function RunComparePage() {
  const [search, setSearch] = useSearchParams();
  const [a = null, b = null] = (search.get("ids") ?? "").split(",").filter(Boolean);
  const compare = useRunCompare(a, b);
  const runs = useRuns({ kind: "research", sort: "created", direction: "desc" });
  const choose = (which: 0 | 1, id: string) => {
    const ids = [a ?? "", b ?? ""];
    ids[which] = id;
    setSearch(new URLSearchParams({ ids: ids.join(",") }), { replace: true });
  };

  return (
    <section className="run-compare">
      <p className="crumbs"><Link to="/runs">Runs</Link> <span aria-hidden="true">/</span></p>
      <h1>Compare two runs</h1>
      <form className="toolbar" aria-label="Choose runs" onSubmit={(e) => e.preventDefault()}>
        {([0, 1] as const).map((which) => (
          <label key={which}>Run {which === 0 ? "A" : "B"}
            <select className="run-picker" value={(which === 0 ? a : b) ?? ""} onChange={(e) => choose(which, e.target.value)}>
              <option value="">Choose…</option>
              {runs.data?.map((run) => {
                const option = runOption(run, [new Date(run.created_at).toLocaleDateString(), run.status]);
                return <option key={run.id} value={run.id} title={option.title}>{option.text}</option>;
              })}
            </select>
          </label>
        ))}
      </form>
      {!a || !b ? <p className="hint">Choose two runs (or tick two in the runs list and press Compare).</p>
        : a === b ? <p role="alert" className="form-error">Choose two different runs.</p>
        : compare.isLoading ? <Skeleton label="the comparison" rows={6} />
        : compare.isError || !compare.data ? <p role="alert">Could not compare these runs.</p>
        : <Comparison data={compare.data} />}
    </section>
  );
}

function PaperList({ title, papers, empty }: { title: string; papers: ComparePaper[]; empty: string }) {
  return (
    <section className="compare-list" aria-label={title}>
      <h3>{title} <span className="count">{papers.length}</span></h3>
      {papers.length === 0 ? <p className="hint">{empty}</p> : (
        <ul>{papers.map((p) => <li key={p.paper_id}>{p.title}{p.year ? <span className="hint"> · {p.year}</span> : null}</li>)}</ul>
      )}
    </section>
  );
}

function Comparison({ data }: { data: RunCompareOut }) {
  const [ra, rb] = data.runs;
  const differs = data.config.filter((row) => row.differs).length;
  return (
    <>
      <section aria-labelledby="cfg-h" className="run-detail__block">
        <h2 id="cfg-h">Configuration <span className="hint">{differs === 0 ? "identical" : `${differs} difference${differs === 1 ? "" : "s"}`}</span></h2>
        <table className="runs compare-table">
          <thead><tr><th scope="col">Setting</th><th scope="col"><Link to={`/runs/${ra!.id}`}>A · {runLabel(ra!)}</Link></th><th scope="col"><Link to={`/runs/${rb!.id}`}>B · {runLabel(rb!)}</Link></th></tr></thead>
          <tbody>{data.config.map((row) => (
            <tr key={row.label} className={row.differs ? "is-different" : undefined}>
              <th scope="row">{row.label}{row.differs && <span className="chip chip--warn">differs</span>}</th>
              <td>{row.a ?? <span className="hint">none</span>}</td><td>{row.b ?? <span className="hint">none</span>}</td>
            </tr>
          ))}</tbody>
        </table>
      </section>
      <section aria-labelledby="res-h" className="run-detail__block">
        <h2 id="res-h">Results</h2>
        <div className="compare-grid">
          <PaperList title="Kept in A, dropped in B" papers={data.kept_only_a} empty="None." />
          <PaperList title="Kept in B, dropped in A" papers={data.kept_only_b} empty="None." />
          <PaperList title="Only in A" papers={data.only_in_a} empty="Every paper of A was also screened in B." />
          <PaperList title="Only in B" papers={data.only_in_b} empty="Every paper of B was also screened in A." />
        </div>
        <h3>Score changes <span className="count">{data.score_changes.length}</span></h3>
        {data.score_changes.length === 0 ? <p className="hint">No paper scored differently in both runs.</p> : (
          <table className="runs compact">
            <thead><tr><th scope="col">Paper</th><th scope="col">A</th><th scope="col">B</th><th scope="col">Change</th></tr></thead>
            <tbody>{data.score_changes.map((c) => (
              <tr key={c.paper_id}><th scope="row">{c.title}</th><td className="num">{c.a.toFixed(1)}</td><td className="num">{c.b.toFixed(1)}</td>
                <td className="num">{c.delta > 0 ? "▲ +" : "▼ "}{c.delta.toFixed(1)}<span className="sr-only">{c.delta > 0 ? " higher in B" : " lower in B"}</span></td></tr>
            ))}</tbody>
          </table>
        )}
      </section>
    </>
  );
}
