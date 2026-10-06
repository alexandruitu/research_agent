import { useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";

import { runsExportUrl, useFields, useRuns, type RunListParams } from "../api/hooks";
import { hasRole } from "../api/types";
import { useAuth } from "../auth/AuthProvider";
import { Skeleton } from "../components/ui/Skeleton";
import { JobProgress } from "../features/runs/JobProgress";
import { download, useRunActions } from "../features/runs/RunActions";
import { RunList } from "../features/runs/RunList";
import { RUN_STATUSES, runStatusMeta } from "../features/runs/runWords";
import { StartRunForm } from "../features/runs/StartRunForm";

const SORTS = { created: "Created", name: "Name", status: "Status", papers: "Papers" } as const;
// `?field=` keeps preselecting the start form (Fields → "Start run"); the field filter is `?in=`.
const FILTER_KEYS = ["status", "in", "mine", "from", "to", "q"] as const;

export function RunsPage() {
  const { status, user } = useAuth();
  const [search, setSearch] = useSearchParams();
  const [jobId, setJobId] = useState<string | null>(null);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const canRun = hasRole(user, "member");
  const fields = useFields();
  const params: RunListParams = useMemo(() => ({
    status: search.get("status") || undefined,
    field_id: search.get("in") || undefined,
    mine: search.get("mine") === "1" || undefined,
    created_from: search.get("from") || undefined,
    created_to: search.get("to") || undefined,
    q: search.get("q") || undefined,
    sort: (search.get("sort") as RunListParams["sort"]) || "created",
    direction: (search.get("dir") as "asc" | "desc") || "desc",
  }), [search]);
  const runs = useRuns(params);
  const actions = useRunActions({ onDeleted: (ids) => setSelected((s) => new Set([...s].filter((id) => !ids.includes(id)))) });

  const set = (key: string, value: string | null) => {
    const next = new URLSearchParams(search);
    if (value) next.set(key, value); else next.delete(key);
    setSearch(next, { replace: true });
  };
  const filtered = FILTER_KEYS.some((key) => search.get(key));
  const clear = () => {
    const next = new URLSearchParams(search);
    FILTER_KEYS.forEach((key) => next.delete(key));
    setSearch(next, { replace: true });
  };

  if (status === "loading" || (runs.isLoading && !runs.data)) return <section><h1>Runs</h1><Skeleton label="the runs" rows={5} /></section>;
  if (runs.isError) return <p role="alert">Could not load the runs.</p>;
  const rows = runs.data ?? [];
  const chosen = rows.filter((run) => selected.has(run.id));
  const toggle = (id: string) => setSelected((s) => { const n = new Set(s); if (n.has(id)) n.delete(id); else n.add(id); return n; });
  const toggleAll = () => setSelected((s) => (rows.every((r) => s.has(r.id)) ? new Set() : new Set(rows.map((r) => r.id))));
  const deletable = chosen.filter((run) => run.kind === "research" && actions.canManage(run));

  return (
    <section className="runs-page">
      <header className="page-head">
        <h1>Runs</h1>
        <p className="lede">Every search-screen-review run, with what it was started with. Open one to see its timeline, cost and log; run it again, resume, cancel, compare or export.</p>
      </header>
      {canRun && <StartRunForm onStarted={setJobId} initialFieldId={search.get("field") ?? ""} />}
      {jobId && <JobProgress jobId={jobId} />}

      <form className="toolbar run-filters" role="search" aria-label="Filter runs" onSubmit={(e) => e.preventDefault()}>
        <label>Search
          <input type="search" placeholder="Name, topic or field" defaultValue={params.q ?? ""} onChange={(e) => set("q", e.target.value.trim() || null)} />
        </label>
        <label>Status
          <select value={params.status ?? ""} onChange={(e) => set("status", e.target.value || null)}>
            <option value="">Any</option>
            {RUN_STATUSES.map((s) => <option key={s} value={s}>{runStatusMeta(s).word}</option>)}
          </select>
        </label>
        <label>In field
          <select value={params.field_id ?? ""} onChange={(e) => set("in", e.target.value || null)}>
            <option value="">Any</option>
            {fields.data?.map((field) => <option key={field.id} value={field.id}>{field.name}</option>)}
          </select>
        </label>
        <label>From<input type="date" value={params.created_from ?? ""} onChange={(e) => set("from", e.target.value || null)} /></label>
        <label>To<input type="date" value={params.created_to ?? ""} onChange={(e) => set("to", e.target.value || null)} /></label>
        <label>Sort
          <select value={params.sort} onChange={(e) => set("sort", e.target.value)}>
            {Object.entries(SORTS).map(([value, word]) => <option key={value} value={value}>{word}</option>)}
          </select>
        </label>
        <label>Order
          <select value={params.direction} onChange={(e) => set("dir", e.target.value)}>
            <option value="desc">Descending</option><option value="asc">Ascending</option>
          </select>
        </label>
        {user && <label className="check"><input type="checkbox" checked={!!params.mine} onChange={(e) => set("mine", e.target.checked ? "1" : null)} /> Only mine</label>}
        {filtered && <button type="button" className="link-button" onClick={clear}>Clear all</button>}
      </form>
      <p className="sr-only" aria-live="polite">{rows.length} runs shown{runs.isFetching ? ", updating" : ""}.</p>

      {chosen.length > 0 && (
        <div className="selection-bar" role="region" aria-label="Selected runs">
          <strong>{chosen.length} selected</strong>
          <button type="button" onClick={() => download(runsExportUrl(chosen.map((r) => r.id), "csv"))}>Export CSV</button>
          <button type="button" onClick={() => download(runsExportUrl(chosen.map((r) => r.id), "bibtex"))}>Export BibTeX</button>
          {chosen.length === 2 && <Link className="button-link button-link--quiet" to={`/runs/compare?ids=${chosen.map((r) => r.id).join(",")}`}>Compare</Link>}
          {deletable.length > 0 && <button type="button" onClick={() => actions.askDelete(deletable)}>Delete {deletable.length === chosen.length ? "" : `${deletable.length} of them`}…</button>}
          <button type="button" onClick={() => setSelected(new Set())}>Clear selection</button>
        </div>
      )}

      <RunList runs={rows} selected={selected} onToggle={toggle} onToggleAll={toggleAll} items={(run) => actions.items(run)} filtered={filtered} />
      {actions.dialog}
    </section>
  );
}
