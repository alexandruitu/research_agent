import { useNavigate, useParams } from "react-router-dom";

import { ApiError } from "../api/client";
import { useEval, useEvals } from "../api/hooks";
import { formatRate, parseEval } from "../features/evals/metrics";
import { RecallRows } from "../features/evals/RecallRows";
import { ThresholdGrid } from "../features/evals/ThresholdGrid";

const pairText = (pair: { include: number; exclude: number }) => `include ≥ ${pair.include}, exclude ≥ ${pair.exclude}`;

export function EvalsPage() {
  const { evalId } = useParams();
  const navigate = useNavigate();
  const evals = useEvals();
  const selected = evalId ?? evals.data?.[0]?.id ?? null;
  const detail = useEval(selected);

  if (evals.isLoading) return <p role="status">Loading…</p>;
  if (evals.isError) return <p role="alert">Could not load the eval reports.</p>;
  if (!evals.data?.length) return <section><h1>Evals</h1><p>No eval reports yet. Import an eval folder with <code>research-web import</code>.</p></section>;

  const view = detail.data ? parseEval(detail.data.metrics) : null;
  const checkedOn = view?.holdoutSweep ? "the main set or the holdout" : "the main set (no holdout run)";
  return (
    <section>
      <h1>Evals</h1>
      <label>Eval set
        <select value={selected ?? ""} onChange={(e) => navigate(`/evals/${e.target.value}`)}>
          {evals.data.map((e) => <option key={e.id} value={e.id}>{e.gold_set.name}</option>)}
        </select>
      </label>
      {detail.isError && <p role="alert" className="form-error">{detail.error instanceof ApiError ? `${detail.error.message} (request ${detail.error.requestId})` : "Could not load this report."}</p>}
      {view && (
        <>
          <h2>{view.gold.name} <span className="sub">{view.gold.citation}</span></h2>
          <section aria-label="Summary" className="cards">
            <div className="card"><h3>Search recall</h3><p>{formatRate(view.retrievalRecall)}</p><p className="sub">SR-included papers the query itself found</p></div>
            <div className="card"><h3>Recommended pair</h3><p>{view.recommended ? pairText(view.recommended) : "No admissible pair"}</p><p className="sub">{view.recommended ? `loses no SR-included paper on ${checkedOn}` : "every pair loses a paper that llm_only keeps"}</p></div>
            <div className="card"><h3>Reviewer agreement (kappa)</h3><p>{view.agreement ? (view.agreement.kappa === null ? `n/a (${view.agreement.reason ?? "undefined"})` : view.agreement.kappa.toFixed(3)) : "n/a"}</p>
              <p className="sub">{view.agreement ? `${view.agreement.n} papers` : "no agreement run"}{view.agreement?.sameFamily ? " · " : ""}{view.agreement?.sameFamily && <span className="chip chip--warn">same model family</span>}</p></div>
          </section>
          <h3>Recall</h3>
          <RecallRows strategies={view.strategies} />
          {view.holdout && <p>Holdout ({view.holdout.gold}, {view.holdout.n} papers) at the recommended pair: recall {formatRate(view.holdout.recall)}.</p>}
          <h3>Threshold grid</h3>
          <ThresholdGrid view={view} />
          {view.rejected && (
            <p className="banner banner--warn">
              Rejected on the holdout: {pairText(view.rejected.pair)} is best on the main set but loses {view.rejected.lost.length} SR-included paper(s) there that llm_only keeps:{" "}
              {view.rejected.lost.map((m) => m.title.replace(/\.$/, "")).join("; ")}.
            </p>
          )}
          {view.warnings.length > 0 && <ul aria-label="Caveats">{view.warnings.map((w) => <li key={w}>{w}</li>)}</ul>}
        </>
      )}
    </section>
  );
}
