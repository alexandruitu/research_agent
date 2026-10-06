import type { EvalDetailOut } from "../../api/types";
import { formatRate, parseEval } from "./metrics";
import { RecallRows } from "./RecallRows";
import { ThresholdGrid } from "./ThresholdGrid";
import { Term } from "../../components/ui/Term";

const pairText = (pair: { include: number; exclude: number }) => `include ≥ ${pair.include}, exclude ≥ ${pair.exclude}`;

/** The screening report (slice 2 content, unchanged). */
export function ScreeningReport({ detail }: { detail: EvalDetailOut }) {
  const view = parseEval(detail.metrics);
  const checkedOn = view.holdoutSweep ? "the main set or the holdout" : "the main set (no holdout run)";
  return (
    <>
      <h2>{view.gold.name} <span className="sub">{view.gold.citation}</span></h2>
      <section aria-label="Summary" className="cards">
        <div className="card"><h3><Term k="recall">Search recall</Term></h3><p>{formatRate(view.retrievalRecall)}</p><p className="sub">SR-included papers the query itself found</p></div>
        <div className="card"><h3>Recommended pair</h3><p>{view.recommended ? pairText(view.recommended) : "No admissible pair"}</p><p className="sub">{view.recommended ? `loses no SR-included paper on ${checkedOn}` : "every pair loses a paper that llm_only keeps"}</p></div>
        <div className="card"><h3>Reviewer agreement (<Term k="kappa" />)</h3><p>{view.agreement ? (view.agreement.kappa === null ? `n/a (${view.agreement.reason ?? "undefined"})` : view.agreement.kappa.toFixed(3)) : "n/a"}</p>
          <p className="sub">{view.agreement ? `${view.agreement.n} papers` : "no agreement run"}{view.agreement?.sameFamily ? " · " : ""}{view.agreement?.sameFamily && <span className="chip chip--warn">same model family</span>}</p></div>
      </section>
      <h3><Term k="recall">Recall</Term></h3>
      <RecallRows strategies={view.strategies} />
      {view.holdout && <p><Term k="holdout">Holdout</Term> ({view.holdout.gold}, {view.holdout.n} papers) at the recommended pair: recall {formatRate(view.holdout.recall)}.</p>}
      <h3><Term k="threshold">Threshold</Term> grid</h3>
      <ThresholdGrid view={view} />
      {view.rejected && (
        <p className="banner banner--warn">
          Rejected on the holdout: {pairText(view.rejected.pair)} is best on the main set but loses {view.rejected.lost.length} SR-included paper(s) there that llm_only keeps:{" "}
          {view.rejected.lost.map((m) => m.title.replace(/\.$/, "")).join("; ")}.
        </p>
      )}
      {view.warnings.length > 0 && <ul aria-label="Caveats">{view.warnings.map((w) => <li key={w}>{w}</li>)}</ul>}
    </>
  );
}
