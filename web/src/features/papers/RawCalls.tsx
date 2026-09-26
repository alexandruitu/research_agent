import { useState } from "react";

import { ApiError } from "../../api/client";
import { useCall } from "../../api/hooks";
import type { DrawerOut } from "../../api/types";

type Item = { label: string; key: string };

export function callItems(drawer: DrawerOut): Item[] {
  const items: Item[] = [];
  const seen = new Set<string>();
  const add = (label: string, key: string | null | undefined) => {
    if (key && !seen.has(key)) {
      seen.add(key);
      items.push({ label, key });
    }
  };
  add(drawer.screening.tier === "jev" ? "Screen (Jev)" : "Screen (LLM)", drawer.screening.call_key);
  drawer.claims.forEach((claim) => add("Extract", claim.call_key));
  drawer.reviews.forEach((review) => add(review.role === "adjudicator" ? "Adjudicator" : `Reviewer ${review.role.toUpperCase()}`, review.call_key));
  return items;
}

function CallView({ runId, callKey }: { runId: string; callKey: string }) {
  const call = useCall(runId, callKey);
  if (call.isLoading) return <p role="status">Loading the call…</p>;
  if (call.isError) return <p role="alert" className="form-error">{call.error instanceof ApiError ? call.error.message : "Could not load the call."}</p>;
  const data = call.data!;
  return (
    <div className="call">
      <p><strong>{data.role}</strong> · <span>{data.model}</span> · prompt {data.prompt_version}</p>
      <details open><summary>Input</summary><pre>{JSON.stringify(data.input, null, 2)}</pre></details>
      <details open><summary>Output</summary><pre>{JSON.stringify(data.output, null, 2)}</pre></details>
    </div>
  );
}

export function RawCalls({ runId, drawer }: { runId: string; drawer: DrawerOut }) {
  const items = callItems(drawer);
  const [selected, setSelected] = useState<string | null>(null);
  if (items.length === 0) return <p>No model calls are recorded for this paper.</p>;
  return (
    <div>
      <div className="call-list" role="group" aria-label="Model calls">
        {items.map((item) => (
          <button key={item.key} type="button" aria-pressed={selected === item.key} onClick={() => setSelected(item.key)}>{item.label}</button>
        ))}
      </div>
      {selected && <CallView runId={runId} callKey={selected} />}
    </div>
  );
}
