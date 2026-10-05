import type { EvalDetailOut } from "../../api/types";
import { AblationChart } from "./AblationChart";
import { parseAblation } from "./ablation";
import { fixed, pct, ratioText } from "./words";

const plural = (n: number) => `${n} reviewer${n === 1 ? "" : "s"}`;

export function AblationReport({ detail }: { detail: EvalDetailOut }) {
  const view = parseAblation(detail.metrics);
  const s = view.summary;
  return (
    <>
      <section aria-label="Summary" className="report-section report-section--lead">
        <h2>Does each extra reviewer earn its cost?</h2>
        <p className="verdict-sentence">{s?.sentence ?? "Not enough reviewers to compare (needs at least 2)."}</p>
        {s && (
          <div className="stat-row">
            <div className="stat"><span className="stat-label">Verdict changed by reviewer {s.toSize}</span><span className="stat-value">{pct(s.verdictChanged)} of papers</span></div>
            <div className="stat"><span className="stat-label">Red flags it added</span><span className="stat-value">{fixed(s.redFlagsAdded, 1)} on average</span></div>
            <div className="stat"><span className="stat-label">Extra cost</span><span className="stat-value">+{pct(s.costIncrease)}</span><span className="stat-note">prompt + output characters</span></div>
          </div>
        )}
        <p className="report-meta">
          {view.papers} papers · {view.reviewers.join(", ")} · {view.rerunEditor ? "the editor was re-run for every subset" : "offline: the verdict is the reviewers' majority (editor not re-run)"} · full panel's editor agrees with its majority on {ratioText(view.editorVsMajority)}
        </p>
      </section>
      <section aria-label="By size" className="report-section">
        <h2>1, 2, {view.sizes.length > 2 ? "3 " : ""}reviewers against the full panel</h2>
        <AblationChart sizes={view.sizes} />
        <table className="data-table" aria-label="By number of reviewers">
          <thead><tr><th scope="col">Panel size</th><th scope="col">Subsets</th><th scope="col">Verdict changed</th><th scope="col">Red flags missed</th><th scope="col">Mean score shift</th><th scope="col">Cost</th></tr></thead>
          <tbody>
            {view.sizes.map((r) => (
              <tr key={r.size}><th scope="row">{plural(r.size)}</th><td className="tnum">{r.subsets}</td><td>{pct(r.verdictChanged)}</td><td>{pct(r.redFlagsMissed)}</td><td>{fixed(r.scoreDelta, 1)} points</td><td>{r.costCalls ?? "?"} calls</td></tr>
            ))}
          </tbody>
        </table>
      </section>
      <section aria-label="Subsets" className="report-section">
        <h2>Every subset</h2>
        <table className="data-table" aria-label="Every reviewer subset">
          <thead><tr><th scope="col">Reviewers</th><th scope="col">Verdict changed</th>{view.rerunEditor && <th scope="col">Editor verdict changed</th>}<th scope="col">Red flags missed</th><th scope="col">Mean score shift</th><th scope="col">Calls</th></tr></thead>
          <tbody>
            {view.subsets.map((r) => (
              <tr key={r.subset}><th scope="row">{r.reviewers.join(" + ")}</th><td>{ratioText(r.verdictChanged)}</td>{view.rerunEditor && <td>{ratioText(r.editorChanged)}</td>}<td>{ratioText(r.redFlagsMissed)}</td><td>{fixed(r.scoreDelta, 1)}</td><td className="tnum">{r.calls ?? "?"}</td></tr>
            ))}
          </tbody>
        </table>
      </section>
    </>
  );
}
