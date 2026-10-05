import { Link } from "react-router-dom";

import type { EvalDetailOut } from "../../api/types";
import type { Rate } from "./metrics";
import { HumanSection } from "./HumanSection";
import { Interval, ShareBar } from "./Interval";
import { parsePanel, type PanelView } from "./panel";
import { RatingSamples } from "./RatingSamples";
import { fixed, kappaWords, pct, ratioText } from "./words";

const paperLink = (id: string): string | null => {
  const [src, rest] = id.split(":");
  return src === "MED" || src === "PMC" ? `https://europepmc.org/article/${src}/${rest}` : src === "DOI" ? `https://doi.org/${rest}` : null;
};

function Agreement({ view }: { view: PanelView }) {
  const f = view.fleiss;
  return (
    <section aria-label="Agreement at a glance" className="report-section">
      <h2>Do the reviewers agree on the verdict?</h2>
      <div className="stat-row">
        <div className="stat stat--big">
          <span className="stat-label">Fleiss kappa, {f?.raters ?? view.reviewers.length} reviewers</span>
          <span className="stat-value">{f?.kappa != null ? `Fleiss kappa ${fixed(f.kappa)}` : "Fleiss kappa n/a"}</span>
          <span className="stat-note">{f?.kappa != null ? kappaWords(f.kappa) : f?.reason ?? view.verdictReason ?? "not measured"}</span>
        </div>
        <div className="stat"><span className="stat-label">Same verdict, any two reviewers</span><span className="stat-value">{pct(f?.agreement)} raw agreement</span><span className="stat-note">before correcting for chance</span></div>
        <div className="stat"><span className="stat-label">Most common verdict's share</span><span className="stat-value">{pct(f?.prevalence)} prevalence</span><span className="stat-note">{(f?.prevalence ?? 0) >= 0.8 ? "skewed: kappa will look low" : "balanced enough for kappa"}</span></div>
        <div className="stat"><span className="stat-label">Editor's final verdict</span><span className="stat-value">Editor agrees with the majority on {ratioText(view.editor)}</span><span className="stat-note">on {view.n} papers · {view.textSources.map((s) => `${s.count} ${s.source === "fulltext" ? "full text" : s.source}`).join(", ")}</span></div>
      </div>
      <p className="explain">
        Read the three numbers together. Raw agreement is how often reviewers give the same verdict; kappa corrects for chance, and the
        chance level rises when one verdict dominates (high prevalence). So with 80% of papers getting the same verdict, a kappa of 0.4 can
        still mean reviewers rarely disagree. Bands: below 0.2 slight, 0.2–0.4 fair, 0.4–0.6 moderate, 0.6–0.8 substantial, above 0.8 almost perfect.
      </p>
      {view.pairwise.length > 0 && (
        <table className="data-table" aria-label="Agreement per reviewer pair">
          <thead><tr><th scope="col">Pair</th><th scope="col">Cohen kappa</th><th scope="col">Raw agreement</th><th scope="col">Prevalence</th></tr></thead>
          <tbody>{view.pairwise.map((p) => <tr key={`${p.a}|${p.b}`}><th scope="row">{p.a} and {p.b}</th><td>{fixed(p.kappa)} <span className="sub-inline">{kappaWords(p.kappa)}</span></td><td>{pct(p.agreement)}</td><td>{pct(p.prevalence)}</td></tr>)}</tbody>
        </table>
      )}
    </section>
  );
}

function Items({ view }: { view: PanelView }) {
  return (
    <section aria-label="Checklist items" className="report-section">
      <h2>Which checklist items are unclear?</h2>
      <p className="lede-sm">Worst first. An item is a candidate to reword when reviewers who answer it disagree, or when most answers are “unclear” or “not reported”. Items only one reviewer answers have no agreement; their unanswered share still shows.</p>
      <table className="data-table" aria-label="Agreement per checklist item">
        <thead><tr><th scope="col">Item</th><th scope="col">Answered by</th><th scope="col">Agreement</th><th scope="col">Kappa</th><th scope="col">Unanswered</th></tr></thead>
        <tbody>
          {view.items.map((item) => (
            <tr key={`${item.text}|${item.reviewers.join()}`} className={item.reword ? "is-reword" : undefined}>
              <th scope="row" className="item-text">
                {item.text}
                {item.source && <span className="sub">{item.source}</span>}
                {item.reword && <span className="flag-chip"><span aria-hidden="true">✎</span> candidate to reword</span>}
              </th>
              <td>{item.reviewers.join(", ")}</td>
              <td>{item.share?.value != null ? ratioText(item.share) : <span className="na">{item.reason ?? "n/a"}</span>}</td>
              <td>{item.kappa !== null ? `${fixed(item.kappa)} ${kappaWords(item.kappa)}` : "n/a"}</td>
              <td>{pct(item.unanswered)} not answered</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}

function CoverageCell({ rate }: { rate: Rate | null }) {
  if (!rate || rate.value === null) return <td className="na">{rate?.reason ?? "n/a"}</td>;
  return <td><ShareBar share={rate.value} /> {pct(rate.value)} answered ({rate.k} of {rate.n})</td>;
}

function Coverage({ view }: { view: PanelView }) {
  if (view.coverage.length === 0) return null;
  return (
    <section aria-label="Coverage" className="report-section">
      <h2>How often can each item be answered?</h2>
      <p className="lede-sm">“Answered” means yes or no; “unclear” and “not reported” count as not answered. Abstracts rarely report methods, so compare full text with abstracts before rewording an item.</p>
      <table className="data-table coverage" aria-label="Coverage: answered per reviewer and item">
        <thead><tr><th scope="col">Reviewer · item</th><th scope="col">Full text</th><th scope="col">Abstract only</th></tr></thead>
        <tbody>{view.coverage.map((c) => <tr key={`${c.reviewer}|${c.item}`}><th scope="row">{c.reviewer} <span className="sub">{c.text}</span></th><CoverageCell rate={c.fulltext} /><CoverageCell rate={c.abstract} /></tr>)}</tbody>
      </table>
    </section>
  );
}

function Dispersion({ view }: { view: PanelView }) {
  const rows = view.dispersion.slice(0, 8);
  if (rows.length === 0) return null;
  return (
    <section aria-label="Dispersion" className="report-section">
      <h2>Where do reviewer scores differ most?</h2>
      <ol className="dispersion" aria-label="Score dispersion">
        {rows.map((r) => {
          const href = paperLink(r.paperId);
          return (
            <li key={r.paperId}>
              <span className="spread tnum">spread {r.range ?? "n/a"} points</span>
              {href ? <a href={href} target="_blank" rel="noreferrer">{r.title || r.paperId}</a> : <span>{r.title || r.paperId}</span>}
              <span className="sub">{r.paperId} · panel score {r.score ?? "n/a"} · {r.scores.map((s) => `${s.name} ${s.score ?? "n/a"}`).join(", ")}</span>
            </li>
          );
        })}
      </ol>
    </section>
  );
}

function Auc({ view }: { view: PanelView }) {
  const auc = view.auc;
  if (!auc) return null;
  return (
    <section aria-label="Against SR inclusion" className="report-section">
      <h2>Does the panel score separate SR-included papers?</h2>
      {auc.value === null ? (
        <p>Not measured: {auc.reason ?? "no SR labels"}.</p>
      ) : (
        <p className="auc-line">
          <strong>AUC {fixed(auc.value)}{auc.ci ? ` (95% CI ${fixed(auc.ci[0])}–${fixed(auc.ci[1])})` : ""}</strong> <Interval value={auc.value} ci={auc.ci} />
          <span className="sub">{auc.nPos} included, {auc.nNeg} excluded. 0.5 is chance, 1 means every included paper scores above every excluded one.</span>
        </p>
      )}
      <p className="banner banner--warn"><strong>Inclusion ≠ quality.</strong> A review includes papers for its question, not for their methods; a weak signal at best. Human reference ratings are the real check.</p>
    </section>
  );
}

function Families({ view }: { view: PanelView }) {
  const f = view.families;
  if (!f) return null;
  return (
    <section aria-label="Model families" className="report-section">
      <h2>Model families</h2>
      {f.single ? (
        <div className="banner banner--warn">
          <p><strong><span aria-hidden="true">⚠ </span>All reviewers use one model family ({f.provider ?? "unknown"}).</strong> Models of one family tend to make the same mistakes, so their agreement overstates independence.</p>
          <p>To compare families, give at least one reviewer a model from another provider, e.g. make the Statistician use Gemini, in <Link to="/settings/models">Settings → AI models</Link>, then run a new panel evaluation.</p>
        </div>
      ) : (
        <table className="data-table" aria-label="Agreement by model family">
          <thead><tr><th scope="col">Family</th><th scope="col">Reviewers</th><th scope="col">Fleiss kappa within</th></tr></thead>
          <tbody>{f.byFamily.map((b) => <tr key={b.provider}><th scope="row">{b.provider}</th><td>{b.reviewers.join(", ")}</td><td>{b.kappa !== null ? `${fixed(b.kappa)} ${kappaWords(b.kappa)}` : "n/a (needs 2 reviewers)"}</td></tr>)}</tbody>
        </table>
      )}
    </section>
  );
}

export function PanelReport({ detail }: { detail: EvalDetailOut }) {
  const view = parsePanel(detail.metrics);
  return (
    <>
      {view.human && <HumanSection human={view.human} />}
      <Agreement view={view} />
      <Items view={view} />
      <Coverage view={view} />
      <Dispersion view={view} />
      <Auc view={view} />
      <Families view={view} />
      <RatingSamples evalId={detail.id} sampleIds={detail.rating_sample_ids ?? []} allowCreate={detail.kind !== "human"} />
    </>
  );
}
