import { formatRate, type Strategy } from "./metrics";

const LABEL: Record<Strategy["name"], string> = {
  llm_only: "llm_only (the LLM screens everything)",
  jev_only: "jev_only (Jev alone, no LLM)",
  cascade: "cascade (Jev when confident, else the LLM)",
};

/** A dot-and-interval bar on a fixed 0 to 1 axis, next to the numbers as text. */
function Interval({ recall }: { recall: Strategy["recall"] }) {
  if (!recall || recall.value === null || !recall.ci) return <span className="na" aria-hidden="true">–</span>;
  const [low, high] = recall.ci;
  return (
    <svg viewBox="0 0 100 12" width="160" height="16" role="img" aria-label={`recall ${recall.value.toFixed(2)}, interval ${low.toFixed(2)} to ${high.toFixed(2)}`}>
      <line x1="0" y1="6" x2="100" y2="6" className="axis" />
      <line x1={low * 100} y1="6" x2={high * 100} y2="6" className="interval" />
      <circle cx={recall.value * 100} cy="6" r="3.5" className="dot" />
    </svg>
  );
}

export function RecallRows({ strategies }: { strategies: Strategy[] }) {
  return (
    <table className="recall" aria-label="Recall by strategy">
      <thead><tr><th scope="col">Strategy</th><th scope="col">Recall on SR-included papers</th><th scope="col">Interval (0 to 1)</th><th scope="col">Workload</th></tr></thead>
      <tbody>
        {strategies.map((s) => (
          <tr key={s.name}>
            <th scope="row">{LABEL[s.name]}</th>
            <td>{formatRate(s.recall)}</td>
            <td><Interval recall={s.recall} /></td>
            <td>{s.callsSaved} calls saved · {s.escalated} escalated · {s.kept} kept ({s.keptNegatives} not in the SR)</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
