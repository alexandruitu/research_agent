import { useSearchParams } from "react-router-dom";

import { ApiError } from "../api/client";
import { useStages } from "../api/hooks";
import { StagePanel } from "../features/papers/StagePanel";
import { SystemMap } from "../features/system/SystemMap";

export function SystemMapPage() {
  const [search, setSearch] = useSearchParams();
  const stages = useStages();
  const selectedId = search.get("stage");
  const select = (id: string | null) => {
    const next = new URLSearchParams(search);
    if (id && id !== selectedId) next.set("stage", id);
    else next.delete("stage");
    setSearch(next);
  };

  if (stages.isLoading) return <p role="status">Loading…</p>;
  if (stages.isError) return <p role="alert">{stages.error instanceof ApiError ? `${stages.error.message} (request ${stages.error.requestId})` : "Could not load the system map."}</p>;
  const selected = stages.data?.find((stage) => stage.id === selectedId);

  return (
    <section>
      <h1>System map</h1>
      <p className="sub">Each stage is teal only when a measurement exists. Amber means a caveat applies or nothing has measured it yet.</p>
      <div className={`papers-layout ${selected ? "with-panel" : ""}`}>
        <SystemMap stages={stages.data ?? []} selectedId={selected?.id ?? null} onSelect={select} />
        {selected && <StagePanel stage={selected} onClose={() => select(null)} showPapersLink />}
      </div>
    </section>
  );
}
