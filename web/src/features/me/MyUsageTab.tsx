import { useMyUsage } from "../../api/meHooks";

const usd = (value: number) => `$${value.toFixed(2)}`;

export function MyUsageTab() {
  const usage = useMyUsage();
  if (usage.isLoading) return <p role="status">Loading…</p>;
  if (usage.isError || !usage.data) return <p role="alert">Could not load your usage. Reload the page to try again.</p>;
  const months = usage.data.months;
  return (
    <section>
      <h2>My usage</h2>
      <p className="intro">What your searches cost: the AI calls of the searches you started, per month, with an estimated cost from approximate list prices. Your provider’s bill is the exact figure.</p>
      {months.length === 0 ? (
        <p>No searches yet. Start one from a topic to see its usage here.</p>
      ) : (
        <table className="runs">
          <thead><tr><th scope="col">Month</th><th scope="col">Searches</th><th scope="col">AI calls</th><th scope="col">Estimated cost</th></tr></thead>
          <tbody>
            {months.map((m) => (
              <tr key={m.month}>
                <th scope="row">{m.month}</th>
                <td>{m.runs}</td>
                <td>{m.calls}</td>
                <td>{usd(m.cost_usd)} (estimate){m.unpriced_models.length > 0 && <span className="sub"> · no price for {m.unpriced_models.join(", ")}</span>}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}
