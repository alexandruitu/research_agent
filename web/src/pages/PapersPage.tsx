import { useState } from "react";
import { useSearchParams } from "react-router-dom";

import { ApiError } from "../api/client";
import { useFieldVersion, usePapers, useRun, useRuns, useStages } from "../api/hooks";
import { hasRole } from "../api/types";
import { useAuth } from "../auth/AuthProvider";
import { ErrorBoundary } from "../components/ErrorBoundary";
import { isFieldCriterion } from "../features/fields/labels";
import { isPanelRun, screenKeys } from "../features/papers/cells";
import { FilterBar, type CriterionOption } from "../features/papers/FilterBar";
import { PaperTable } from "../features/papers/PaperTable";
import { parseView, patchView } from "../features/papers/papersState";
import { PapersSidePanel } from "../features/papers/PapersSidePanel";
import { SaveDialog } from "../features/library/SaveDialog";
import { useSaveFlow } from "../features/library/saveFlow";

const errorText = (error: unknown) => (error instanceof ApiError ? `${error.message} (request ${error.requestId})` : "Could not reach the server.");

export function PapersPage() {
  const { user } = useAuth();
  const member = hasRole(user, "member");
  const [search, setSearch] = useSearchParams();
  const [picked, setPicked] = useState<{ runId: string | null; ids: Set<string> }>({ runId: null, ids: new Set() });
  const [saving, setSaving] = useState(false);
  const saveFlow = useSaveFlow();
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
  const version = useFieldVersion(selected?.field_id ?? null, selected?.field_version ?? null);
  // A run's criteria come from its field version; without one, from the keys the rows carry.
  const criteria: CriterionOption[] = version.data
    ? [...version.data.include, ...version.data.exclude, ...version.data.legacy]
    : [...new Set((papers.data?.items ?? []).flatMap((row) => screenKeys(row.screen)))].map((key) => ({ key, text: "" }));
  const legacy = !criteria.some((c) => isFieldCriterion(c.key));
  const change = (changes: Parameters<typeof patchView>[1], reset = true) => setSearch(patchView(search, changes, reset));
  const close = () => {
    const open = view.paperId;
    change({ paper: null, stage: null }, false);
    if (open) requestAnimationFrame(() => document.querySelector<HTMLElement>(`[data-open-paper="${open}"]`)?.focus());
  };

  if (runs.isLoading) return <p role="status">Loading…</p>;
  if (runs.isError) return <p role="alert">{errorText(runs.error)}</p>;
  if (!runId) return <section><h1>Papers</h1><p>No runs yet. Import a run or start one from the Runs page.</p></section>;

  // a selection belongs to one run: switching runs starts empty
  const selectedIds = picked.runId === runId ? picked.ids : new Set<string>();
  const setSelected = (ids: Set<string>) => setPicked({ runId, ids });
  const toggle = (paperId: string, on: boolean) => {
    const next = new Set(selectedIds);
    if (on) next.add(paperId);
    else next.delete(paperId);
    setSelected(next);
  };
  const toggleAll = (on: boolean) => {
    const next = new Set(selectedIds);
    for (const row of papers.data?.items ?? []) if (on) next.add(row.paper.id); else next.delete(row.paper.id);
    setSelected(next);
  };
  const doSave = async (choice: Parameters<typeof saveFlow.save>[2]) => {
    setSaving(false);
    const ok = await saveFlow.save(runId, [...selectedIds], choice);
    if (ok) setSelected(new Set());
  };

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
              <option key={r.id} value={r.id}>{r.field_name}{r.field_version ? ` · v${r.field_version}` : ""} · {r.kind}{r.gold_set_name ? ` · ${r.gold_set_name}` : ""} · {r.paper_count} papers</option>
            ))}
          </select>
        </label>
        {counts && (
          <p className="summary">
            {counts.screened} screened · {counts.kept} kept · {counts.dropped} dropped · {counts.escalated} escalated to the LLM{counts.in_sr !== null ? ` · ${counts.in_sr} in the SR` : ""}
          </p>
        )}
      </div>
      {member && selectedIds.size > 0 && (
        <div className="selection-bar" role="region" aria-label="Selection">
          <strong>{selectedIds.size} selected</strong>
          <button type="button" className="primary" onClick={() => setSaving(true)} disabled={saveFlow.pending}>Save to library…</button>
          <button type="button" onClick={() => setSelected(new Set())}>Clear selection</button>
        </div>
      )}
      {saving && <SaveDialog count={selectedIds.size} onSave={(choice) => void doSave(choice)} onClose={() => setSaving(false)} />}
      <FilterBar view={view} showSr={hasGoldSet} showPanel={selected?.settings_version != null || isPanelRun(papers.data?.items ?? [])} legacy={legacy} criteria={criteria} onChange={(changes) => change(changes)} />
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
                legacy={legacy}
                rows={papers.data.items} stages={stages.data ?? []} sort={view.params.sort} direction={view.params.direction}
                onSort={(sort) => change({ sort, dir: view.params.sort === sort && view.params.direction === "asc" ? "desc" : "asc" })}
                selectedPaperId={view.paperId} onOpen={(paper) => change({ paper }, false)}
                selectedStageId={view.stageId} onSelectStage={(stage) => change({ stage: view.stageId === stage ? null : stage }, false)}
                selection={member ? { ids: selectedIds, onToggle: toggle, onToggleAll: toggleAll } : null}
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
