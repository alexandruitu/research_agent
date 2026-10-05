import { Link, useSearchParams } from "react-router-dom";

import { ApiError } from "../api/client";
import { useCompare } from "../api/hooks";
import type { CompareRow, EvalSummaryOut } from "../api/types";
import { Skeleton } from "../components/ui/Skeleton";
import { reportTitle } from "../features/evals/headline";
import { KIND_LABEL, dateText, kindOf } from "../features/evals/words";

const cell = (v: CompareRow["values"][number]) => (v === null ? "n/a" : typeof v === "boolean" ? (v ? "yes" : "no") : typeof v === "number" ? (Number.isInteger(v) ? String(v) : v.toFixed(2)) : v);

function Rows({ label, rows, reports }: { label: string; rows: CompareRow[]; reports: EvalSummaryOut[] }) {
  let section = "";
  return (
    <table className="data-table compare-table" aria-label={label}>
      <thead>
        <tr>
          <th scope="col">Measure</th>
          {reports.map((r, i) => <th key={r.id} scope="col"><span className="compare-col">{String.fromCharCode(65 + i)}</span> {KIND_LABEL[kindOf(r.kind)]} · {reportTitle(r)} <span className="sub">{dateText(r.created_at)}</span></th>)}
          <th scope="col">Same?</th>
        </tr>
      </thead>
      <tbody>
        {rows.flatMap((row) => {
          const out = [];
          if (row.section !== section) {
            section = row.section;
            out.push(<tr key={`s-${section}`} className="group-row"><th scope="rowgroup" colSpan={reports.length + 2}>{section}</th></tr>);
          }
          out.push(
            <tr key={row.key} className={row.differs ? "differs" : undefined}>
              <th scope="row">{row.label}</th>
              {row.values.map((v, i) => <td key={i} className="tnum">{cell(v)}</td>)}
              <td>{row.differs ? <strong><span aria-hidden="true">≠ </span>differs</strong> : <span className="na">same</span>}</td>
            </tr>,
          );
          return out;
        })}
      </tbody>
    </table>
  );
}

export function ComparePage() {
  const [search] = useSearchParams();
  const ids = (search.get("ids") ?? "").split(",").filter(Boolean);
  const compare = useCompare(ids);
  const back = <nav aria-label="Breadcrumb" className="crumbs"><Link to="/evals">← All evaluations</Link></nav>;
  if (ids.length < 2) return <section>{back}<p role="alert" className="form-error">Pick 2 or 3 reports on the Evals page to compare them.</p></section>;
  if (compare.isLoading) return <section>{back}<Skeleton label="the comparison" rows={6} /></section>;
  if (compare.isError || !compare.data) return <section>{back}<p role="alert" className="form-error">{compare.error instanceof ApiError ? compare.error.message : "Could not compare these reports."}</p></section>;
  const { reports, metrics, config } = compare.data;
  const differing = metrics.filter((m) => m.differs).length + config.filter((m) => m.differs).length;
  return (
    <section className="compare-page">
      {back}
      <h1>Compare {reports.length} reports</h1>
      <p className="lede">{differing} of {metrics.length + config.length} rows differ. Differing rows are shaded and marked “differs”. </p>
      <p className="compare-links">{reports.map((r, i) => <Link key={r.id} to={`/evals/${r.id}`}>Open report {String.fromCharCode(65 + i)}<span className="sr-only">: {KIND_LABEL[kindOf(r.kind)]} · {reportTitle(r)}</span></Link>)}</p>
      <Rows label="Metrics side by side" rows={metrics} reports={reports} />
      <h2>Configuration</h2>
      <p className="lede-sm">What was frozen in each report. A metric difference is only meaningful when you know which of these changed.</p>
      <Rows label="Configuration side by side" rows={config} reports={reports} />
    </section>
  );
}
