import { rowFor, samePair, type EvalView, type Pair } from "./metrics";

// The grid of `research_agent.eval.metrics.sweep` (INCLUDE_GRID x EXCLUDE_GRID).
const INCLUDES = [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9];
const EXCLUDES = [0.5, 0.6, 0.7, 0.8, 0.9, 0.95, 0.99];

/** Rows are the include threshold, columns the exclude threshold, a cell is the screening calls saved. */
export function ThresholdGrid({ view }: { view: EvalView }) {
  const holdout = view.holdoutSweep;
  return (
    <div>
      <table className="grid" aria-label="Threshold grid">
        <thead>
          <tr><th scope="col">include ↓ / exclude →</th>{EXCLUDES.map((e) => <th key={e} scope="col">{e}</th>)}</tr>
        </thead>
        <tbody>
          {INCLUDES.map((include) => (
            <tr key={include}>
              <th scope="row">{include}</th>
              {EXCLUDES.map((exclude) => {
                const pair: Pair = { include, exclude };
                const main = rowFor(view.sweep, pair);
                if (!main) {
                  const why = exclude < include ? "not allowed: the exclude bar cannot be lower than the include bar" : "not in this report";
                  return (
                    <td key={exclude} className="not-allowed" title={why}>
                      <span aria-hidden="true">–</span><span className="sr-only">{why}</span>
                    </td>
                  );
                }
                const other = holdout ? rowFor(holdout.rows, pair) : undefined;
                const isDefault = samePair(view.defaultPair, pair);
                const isRecommended = samePair(view.recommended, pair);
                const risks = [main.lost > 0 && `loses ${main.lost} on the main set`, other && other.lost > 0 && `loses ${other.lost} on the holdout`].filter(Boolean) as string[];
                const label = `include ${include}, exclude ${exclude}: ${main.callsSaved} calls saved${isDefault ? ", shipped default" : ""}${isRecommended ? ", recommended" : ""}${risks.length ? `, ${risks.join(", ")}` : ""}`;
                return (
                  <td key={exclude} aria-label={label} className={[isDefault && "is-default", risks.length > 0 && "is-risky"].filter(Boolean).join(" ")}>
                    <span>{main.callsSaved}</span>{isRecommended && <span aria-hidden="true"> ★</span>}
                    {risks.map((risk) => <span key={risk} className="risk">{risk}</span>)}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
      <p className="legend">
        Cells show screening calls saved by the cascade. Outlined = shipped default. ★ = recommended (loses no SR-included paper on the main set{holdout ? " or the holdout" : ""}). Red with text = the pair loses an SR-included paper that llm_only keeps.
        {!holdout && " No holdout run: risky pairs can only be judged on the main set."}
      </p>
    </div>
  );
}
