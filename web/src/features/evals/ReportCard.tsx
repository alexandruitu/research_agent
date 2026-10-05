import { Link } from "react-router-dom";

import type { EvalSummaryOut } from "../../api/types";
import { headlinePhrases, reportTitle } from "./headline";
import { Chips, KindBadge } from "./KindBadge";
import { KIND_LABEL, dateText, kindOf } from "./words";

type Props = { report: EvalSummaryOut; parent: EvalSummaryOut | undefined; children: EvalSummaryOut[]; selected: boolean; onSelect: (on: boolean) => void };

export function ReportCard({ report, parent, children, selected, onSelect }: Props) {
  const name = `${KIND_LABEL[kindOf(report.kind)]} · ${reportTitle(report)}`;
  return (
    <article className={`eval-card eval-card--${kindOf(report.kind)}${selected ? " is-selected" : ""}`} aria-label={name}>
      <header className="eval-card-top">
        <KindBadge kind={report.kind} />
        <time dateTime={report.created_at}>{dateText(report.created_at)}</time>
      </header>
      <h2 className="eval-card-title">{reportTitle(report)}</h2>
      <ul className="headline-list">{headlinePhrases(report).map((p) => <li key={p}>{p}</li>)}</ul>
      <Chips chips={report.chips} />
      {(report.parent_id || children.length > 0) && (
        <p className="eval-lineage">
          {report.parent_id && <Link to={`/evals/${report.parent_id}`}>Based on {parent ? `${KIND_LABEL[kindOf(parent.kind)]} · ${reportTitle(parent)}` : "its panel report"}</Link>}
          {children.map((c) => <Link key={c.id} to={`/evals/${c.id}`}>Follow-up: {KIND_LABEL[kindOf(c.kind)]}</Link>)}
        </p>
      )}
      <footer className="eval-card-foot">
        <Link to={`/evals/${report.id}`} className="button-link button-link--quiet">Open report<span className="sr-only"> {name}</span></Link>
        <label className="check compare-pick"><input type="checkbox" checked={selected} onChange={(e) => onSelect(e.target.checked)} aria-label={`Select ${name} to compare`} /> Compare</label>
      </footer>
    </article>
  );
}
