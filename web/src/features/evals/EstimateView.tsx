import type { EstimateOut } from "../../api/types";

const n = (x: number) => x.toLocaleString("en-US");
export const usd = (x: number | null) => (x === null ? "unknown price" : `about $${x < 1 ? x.toFixed(2) : x.toFixed(0)}`);

export function EstimateView({ estimate }: { estimate: EstimateOut }) {
  return (
    <section aria-label="Cost estimate" className="estimate">
      <p className="estimate-total">
        <strong>{n(estimate.calls)} model calls</strong> · {n(estimate.input_tokens)} input tokens · {n(estimate.output_tokens)} output tokens · <strong>{usd(estimate.cost_usd)}</strong>
      </p>
      {estimate.lines.length > 0 && (
        <table className="runs estimate-lines">
          <caption className="sr-only">Cost per role</caption>
          <thead><tr><th scope="col">Role</th><th scope="col">Model</th><th scope="col">Calls</th><th scope="col">Output tokens</th><th scope="col">Cost</th></tr></thead>
          <tbody>
            {estimate.lines.map((l) => (
              <tr key={l.role}><th scope="row">{l.role}</th><td>{l.model ?? "worker default"}</td><td className="tnum">{n(l.calls)}</td><td className="tnum">{n(l.output_tokens)}</td><td>{usd(l.cost_usd)}</td></tr>
            ))}
          </tbody>
        </table>
      )}
      {estimate.notes.length > 0 && <ul className="legend">{estimate.notes.map((note) => <li key={note}>{note}</li>)}</ul>}
    </section>
  );
}
