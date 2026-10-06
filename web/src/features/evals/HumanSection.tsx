import type { HumanView } from "./panel";
import { fixed, kappaWords, ratioText } from "./words";
import { Term } from "../../components/ui/Term";

export function HumanSection({ human }: { human: HumanView }) {
  return (
    <section aria-label="Against human ratings" className="report-section report-section--lead">
      <h2>Against human ratings</h2>
      <p className="lede-sm">People rated the same checklist items blind; their majority answer is the reference. This is the only check of whether the panel is <em>right</em>, not just consistent.</p>
      <div className="stat-row">
        <div className="stat"><span className="stat-label">Panel matches the human consensus</span><span className="stat-value">{ratioText(human.panelAccuracy)}</span><span className="stat-note">kappa {fixed(human.panelKappa)} · {kappaWords(human.panelKappa)}</span></div>
        <div className="stat"><span className="stat-label">Humans agree with each other</span><span className="stat-value">{ratioText(human.interRater)}</span><span className="stat-note">{human.interRaterKappa !== null ? `Fleiss kappa ${fixed(human.interRaterKappa)} · ${kappaWords(human.interRaterKappa)}` : human.interRaterReason ?? "kappa not defined"}</span></div>
        <div className="stat"><span className="stat-label">Score order, panel vs humans</span><span className="stat-value">Spearman {fixed(human.spearman?.rho ?? null)}</span><span className="stat-note">{human.spearman?.reason ?? `${human.spearman?.n ?? 0} papers, both scored by the same code`}</span></div>
      </div>
      <p className="report-meta">{human.raters} raters · {human.units} answers on {human.papers} papers{human.stale > 0 ? ` · ${human.stale} ratings ignored because the item wording changed since` : ""}</p>
      <table className="data-table" aria-label="Panel vs humans per reviewer">
        <thead><tr><th scope="col">Reviewer</th><th scope="col">Matches humans</th><th scope="col"><Term k="kappa">Kappa</Term></th></tr></thead>
        <tbody>{human.perReviewer.map((r) => <tr key={r.key}><th scope="row">{r.name}</th><td>{ratioText(r.accuracy)}</td><td>{fixed(r.kappa)} <span className="sub-inline">{kappaWords(r.kappa)}</span></td></tr>)}</tbody>
      </table>
      <table className="data-table" aria-label="Panel vs humans per item">
        <thead><tr><th scope="col">Item</th><th scope="col">Reviewer</th><th scope="col">Papers</th><th scope="col">Matches humans</th><th scope="col">Kappa</th></tr></thead>
        <tbody>{human.perItem.map((r) => <tr key={`${r.reviewer}|${r.text}`}><th scope="row" className="item-text">{r.text}</th><td>{r.reviewer}</td><td className="tnum">{r.n}</td><td>{ratioText(r.accuracy)}</td><td>{fixed(r.kappa)} <span className="sub-inline">{kappaWords(r.kappa)}</span></td></tr>)}</tbody>
      </table>
    </section>
  );
}
