import { useSearchParams } from "react-router-dom";

import { ApiError } from "../api/client";
import { usePapers, useRun, useRuns, useStages } from "../api/hooks";
import { ErrorBoundary } from "../components/ErrorBoundary";
import { FilterBar } from "../features/papers/FilterBar";
import { PaperTable } from "../features/papers/PaperTable";
import { parseView, patchView } from "../features/papers/papersState";
import { PapersSidePanel } from "../features/papers/PapersSidePanel";

const errorText = (error: unknown) => (error instanceof ApiError ? `${error.message} (request ${error.requestId})` : "Could not reach the server.");

export function PapersPage() {
  const [search, setSearch] = useSearchParams();
  const view = parseView(search);
  const runs = useRuns();
  const runId = view.runId ?? runs.data?.find((run) => run.paper_count > 0)?.id ?? null;
  const run = useRun(runId);
  // The in_sr filter is a 422 on a run without a gold set, so it is never sent there (even from a pasted URL);
  // the papers wait until it is known whether the run has one.
  const selected = runs.data?.find((r) => r.id === runId) ?? run.data;
  const hasGoldSet = !!selected?.gold_set_name;
  const params = hasGoldSet ? view.params : { ...view.params, in_sr: undefined };
  const papers = usePapers(selected ? runId : null, params);
  const stages = useStages();
  const change = (changes: Parameters<typeof patchView>[1], reset = true) => setSearch(patchView(search, changes, reset));
  const close = () => {
    const open = view.paperId;
    change({ paper: null, stage: null }, false);
    if (open) requestAnimationFrame(() => document.querySelector<HTMLElement>(`[data-open-paper="${open}"]`)?.focus());
  };

  if (runs.isLoading) return <p role="status">Loading…</p>;
  if (runs.isError) return <p role="alert">{errorText(runs.error)}</p>;
  if (!runId) return <section><h1>Papers</h1><p>No runs yet. Import a run or start one from the Runs page.</p></section>;

  const counts = run.data?.counts;
  const total = papers.data?.total ?? 0;
  const pages = Math.max(1, Math.ceil(total / view.params.page_size));
  const panelOpen = !!(view.paperId || view.stageId);

  return (
    <section className="papers-page">
      <h1>Papers</h1>
      <div className="toolbar">
        <label>
          Run
          <select value={runId} onChange={(e) => change({ run: e.target.value })}>
            {runs.data?.map((r) => (
              <option key={r.id} value={r.id}>{r.field_name} · {r.kind}{r.gold_set_name ? ` · ${r.gold_set_name}` : ""} · {r.paper_count} papers</option>
            ))}
          </select>
        </label>
        {counts && (
          <p className="summary">
            {counts.screened} screened · {counts.kept} kept · {counts.dropped} dropped · {counts.escalated} escalated to the LLM{counts.in_sr !== null ? ` · ${counts.in_sr} in the SR` : ""}
          </p>
        )}
      </div>
      <FilterBar view={view} showSr={hasGoldSet} onChange={(changes) => change(changes)} />
      <div className={`papers-layout ${panelOpen ? "with-panel" : ""}`}>
        <div className="papers-main">
          {papers.isError || (!selected && run.isError) ? (
            <p role="alert" className="form-error">{errorText(papers.isError ? papers.error : run.error)}</p>
          ) : !papers.data ? (
            <p role="status">Loading papers…</p>
          ) : papers.data.items.length === 0 ? (
            <p>No papers match these filters.</p>
          ) : (
            <ErrorBoundary label="the paper table">
              <PaperTable
                rows={papers.data.items} stages={stages.data ?? []} sort={view.params.sort} direction={view.params.direction}
                onSort={(sort) => change({ sort, dir: view.params.sort === sort && view.params.direction === "asc" ? "desc" : "asc" })}
                selectedPaperId={view.paperId} onOpen={(paper) => change({ paper }, false)}
                selectedStageId={view.stageId} onSelectStage={(stage) => change({ stage: view.stageId === stage ? null : stage }, false)}
              />
            </ErrorBoundary>
          )}
          <nav className="pager" aria-label="Pages">
            <button type="button" disabled={view.params.page <= 1} onClick={() => change({ page: view.params.page - 1 }, false)}>Previous page</button>
            <span aria-live="polite">Page {view.params.page} of {pages}</span>
            <button type="button" disabled={view.params.page >= pages} onClick={() => change({ page: view.params.page + 1 }, false)}>Next page</button>
          </nav>
        </div>
        {panelOpen && (
          <ErrorBoundary label="the side panel">
            <PapersSidePanel runId={runId} paperId={view.paperId} stageId={view.stageId} stages={stages.data ?? []} onClose={close} />
          </ErrorBoundary>
        )}
      </div>
    </section>
  );
}
