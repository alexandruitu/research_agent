import type { SizeRow } from "./ablation";
import { pct } from "./words";

const W = 640;
const LEFT = 110;
const RIGHT = 90;
const ROW = 34;
const x = (share: number) => LEFT + share * (W - LEFT - RIGHT);
const plural = (n: number) => `${n} reviewer${n === 1 ? "" : "s"}`;

/** Per subset size: verdict changed (circle) and red flags missed (square) vs the full panel on a 0–100% axis. */
export function AblationChart({ sizes }: { sizes: SizeRow[] }) {
  const height = 40 + sizes.length * ROW;
  const label = sizes.map((s) => `${plural(s.size)}: verdict changed on ${pct(s.verdictChanged)}, red flags missed ${pct(s.redFlagsMissed)}, ${s.costCalls ?? "?"} calls`).join("; ");
  return (
    <figure className="ablation-figure">
      <svg viewBox={`0 0 ${W} ${height}`} role="img" aria-label={label} className="ablation-chart">
        {[0, 0.25, 0.5, 0.75, 1].map((t) => (
          <g key={t}>
            <line x1={x(t)} x2={x(t)} y1={16} y2={height - 18} className="grid-line" />
            <text x={x(t)} y={height - 4} className="tick" textAnchor="middle">{pct(t)}</text>
          </g>
        ))}
        <text x={W - RIGHT + 12} y={12} className="tick">calls</text>
        {sizes.map((s, i) => {
          const y = 30 + i * ROW;
          return (
            <g key={s.size}>
              <text x={LEFT - 12} y={y + 4} className="row-label" textAnchor="end">{plural(s.size)}</text>
              <line x1={x(0)} x2={x(1)} y1={y} y2={y} className="row-line" />
              {s.verdictChanged !== null && s.redFlagsMissed !== null && <line x1={x(s.verdictChanged)} x2={x(s.redFlagsMissed)} y1={y} y2={y} className="pair-line" />}
              {s.verdictChanged !== null && <circle cx={x(s.verdictChanged)} cy={y} r={6} className="mark mark--verdict" />}
              {s.redFlagsMissed !== null && <rect x={x(s.redFlagsMissed) - 5} y={y - 5} width={10} height={10} className="mark mark--flags" />}
              <text x={W - RIGHT + 12} y={y + 4} className="row-value">{s.costCalls ?? "?"}</text>
            </g>
          );
        })}
      </svg>
      <figcaption className="legend">
        <span className="key"><svg width="12" height="12" aria-hidden="true"><circle cx="6" cy="6" r="5" className="mark mark--verdict" /></svg> verdict changed vs the full panel</span>
        <span className="key"><svg width="12" height="12" aria-hidden="true"><rect x="1" y="1" width="10" height="10" className="mark mark--flags" /></svg> red flags missed</span>
        <span>Closer to 0% means the smaller panel already gives the full panel's answer. Averages over every subset of that size.</span>
      </figcaption>
    </figure>
  );
}
