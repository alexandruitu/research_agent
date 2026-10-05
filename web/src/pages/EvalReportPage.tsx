import { Link, useParams } from "react-router-dom";

import { ApiError } from "../api/client";
import { useEval } from "../api/hooks";
import type { EvalDetailOut } from "../api/types";
import { Skeleton } from "../components/ui/Skeleton";
import { reportTitle } from "../features/evals/headline";
import { Chips, KindBadge } from "../features/evals/KindBadge";
import { AblationReport } from "../features/evals/AblationReport";
import { PanelReport } from "../features/evals/PanelReport";
import { ScreeningReport } from "../features/evals/ScreeningReport";
import { KIND_LABEL, KIND_WHAT, dateText, kindOf } from "../features/evals/words";

function Body({ detail }: { detail: EvalDetailOut }) {
  switch (kindOf(detail.kind)) {
    case "screening":
      return <ScreeningReport detail={detail} />;
    case "panel":
    case "human":
      return <PanelReport detail={detail} />;
    case "ablation":
      return <AblationReport detail={detail} />;
  }
}

export function EvalReportPage() {
  const { evalId } = useParams();
  const detail = useEval(evalId ?? null);
  if (detail.isLoading) return <section><Link to="/evals">← All evaluations</Link><Skeleton label="the report" rows={6} /></section>;
  if (detail.isError || !detail.data) {
    return (
      <section>
        <Link to="/evals">← All evaluations</Link>
        <p role="alert" className="form-error">{detail.error instanceof ApiError ? `${detail.error.message} (request ${detail.error.requestId})` : "Could not load this report."}</p>
      </section>
    );
  }
  const d = detail.data;
  const kind = kindOf(d.kind);
  return (
    <section className={`eval-report eval-report--${kind}`}>
      <nav aria-label="Breadcrumb" className="crumbs"><Link to="/evals">← All evaluations</Link></nav>
      <header className="report-head">
        <KindBadge kind={kind} />
        <h1>{KIND_LABEL[kind]} <span className="report-of">· {reportTitle(d)}</span></h1>
        <p className="lede">{KIND_WHAT[kind]}</p>
        <p className="report-meta"><time dateTime={d.created_at}>{dateText(d.created_at)}</time>{d.gold_set?.citation ? ` · ${d.gold_set.citation}` : ""}</p>
        <Chips chips={d.chips} />
        {(d.parent_id || (d.children ?? []).length > 0) && (
          <p className="eval-lineage">
            {d.parent_id && <Link to={`/evals/${d.parent_id}`}>Based on the panel report</Link>}
            {(d.children ?? []).map((c) => <Link key={c.id} to={`/evals/${c.id}`}>Follow-up: {KIND_LABEL[kindOf(c.kind)]} ({dateText(c.created_at)})</Link>)}
          </p>
        )}
      </header>
      <Body detail={d} />
    </section>
  );
}
