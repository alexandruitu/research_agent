import { useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";

import { ApiError } from "../api/client";
import { useFieldVersion, usePapers, useRun, useRuns, useStages } from "../api/hooks";
import { hasRole } from "../api/types";
import { useAuth } from "../auth/AuthProvider";
import { EmptyState } from "../components/ui/EmptyState";
import { useShortcuts, type ShortcutMap } from "../components/ui/shortcuts";
import { ShortcutsHelp } from "../components/ui/ShortcutsHelp";
import { Skeleton } from "../components/ui/Skeleton";
import { LIBRARY_STATUSES } from "../components/ui/StatusMark";
import { useStatusChange } from "../features/library/optimistic";
import { activeFilterChips, clearPaperFilters } from "../features/papers/activeFilters";
import { HomeEmpty } from "./HomeEmpty";
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

export const PAPERS_SHORTCUTS = [
  { keys: ["j", "k"], what: "Next / previous paper" },
  { keys: ["o"], what: "Open the paper under the cursor (or Enter on its title)" },
  { keys: ["x"], what: "Select or unselect it" },
  { keys: ["s"], what: "Save the selection (or this paper) to the library" },
  { keys: ["1", "2", "3", "4"], what: "Library status of a saved paper: to read, read, relevant, rejected" },
  { keys: ["Esc"], what: "Close the side panel" },
  { keys: ["?"], what: "This list" },
];

export function PapersPage() {
  const { user } = useAuth();
  const member = hasRole(user, "member");
  const [search, setSearch] = useSearchParams();
  const [picked, setPicked] = useState<{ runId: string | null; ids: Set<string> }>({ runId: null, ids: new Set() });
  const [saving, setSaving] = useState(false);
  const saveFlow = useSaveFlow();
  const status = useStatusChange();
  const [cursor, setCursor] = useState<string | null>(null);
  const [help, setHelp] = useState(false);
  const keysRef = useRef<ShortcutMap>({});
  const relay = (key: string) => (event: KeyboardEvent) => keysRef.current[key]?.(event);
  useShortcuts(Object.fromEntries(["j", "k", "o", "x", "s", "1", "2", "3", "4", "?"].map((key) => [key, relay(key)])));
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

  if (runs.isLoading) return <section><h1>Papers</h1><Skeleton label="the runs" rows={6} /></section>;
  if (runs.isError) return <p role="alert">{errorText(runs.error)}</p>;
  if (!runId) return <HomeEmpty member={member} hasRuns={(runs.data ?? []).length > 0} />;

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

  const rows = papers.data?.items ?? [];
  const cursorIndex = Math.max(0, rows.findIndex((r) => r.paper.id === (cursor ?? view.paperId)));
  const cursorRow = rows[cursorIndex];
  const move = (delta: number) => {
    if (!rows.length) return;
    const next = rows[Math.min(rows.length - 1, Math.max(0, cursorIndex + (cursor || view.paperId ? delta : 0)))]!;
    setCursor(next.paper.id);
    document.querySelector<HTMLElement>(`[data-open-paper="${next.paper.id}"]`)?.focus();
  };
  const statusKey = (n: number) => () => {
    const target = rows.find((r) => r.paper.id === (view.paperId ?? cursorRow?.paper.id));
    const ref = target?.library;
    const to = LIBRARY_STATUSES[n];
    if (member && ref && to && !ref.item_id.startsWith("pending-")) void status.change(ref.item_id, ref.status, to);
  };
  keysRef.current = {
    j: () => move(1), k: () => move(-1),
    o: () => cursorRow && change({ paper: cursorRow.paper.id }, false),
    x: () => member && cursorRow && toggle(cursorRow.paper.id, !selectedIds.has(cursorRow.paper.id)),
    s: () => {
      if (!member) return;
      if (selectedIds.size === 0 && cursorRow) setSelected(new Set([cursorRow.paper.id]));
      if (selectedIds.size > 0 || cursorRow) setSaving(true);
    },
    "1": statusKey(0), "2": statusKey(1), "3": statusKey(2), "4": statusKey(3),
    "?": () => setHelp(true),
  };
  const chips = activeFilterChips(view, criteria);

  const counts = run.data?.counts;
  const total = papers.data?.total ?? 0;
  const pages = Math.max(1, Math.ceil(total / view.params.page_size));
  const panelOpen = !!(view.paperId || view.stageId);

  return (
    <section className="papers-page">
      <div className="page-head">
        <h1>Papers</h1>
        <button type="button" className="kbd-button" onClick={() => setHelp(true)} aria-label="Keyboard shortcuts"><kbd aria-hidden="true">?</kbd></button>
      </div>
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
      {saving && <SaveDialog count={Math.max(1, selectedIds.size)} onSave={(choice) => void doSave(choice)} onClose={() => setSaving(false)} />}
      {help && <ShortcutsHelp title="Papers shortcuts" items={PAPERS_SHORTCUTS} onClose={() => setHelp(false)} />}
      <FilterBar view={view} showSr={hasGoldSet} showPanel={selected?.settings_version != null || isPanelRun(papers.data?.items ?? [])} legacy={legacy} criteria={criteria} onChange={(changes) => change(changes)} />
      {chips.length > 0 && (
        <div className="active-filters" role="group" aria-label="Active filters">
          {chips.map((chip) => (
            <button key={chip.label} type="button" className="active-chip" onClick={() => change(chip.clear)}>
              {chip.label} <span aria-hidden="true">×</span><span className="sr-only"> (remove filter)</span>
            </button>
          ))}
          <button type="button" className="linklike" onClick={() => setSearch(clearPaperFilters(search))}>Clear all</button>
        </div>
      )}
      <div className={`papers-layout ${panelOpen ? "with-panel" : ""}`}>
        <div className="papers-main">
          {papers.isError || (!selected && run.isError) ? (
            <p role="alert" className="form-error">{errorText(papers.isError ? papers.error : run.error)}</p>
          ) : !papers.data ? (
            <Skeleton label="papers" rows={8} />
          ) : papers.data.items.length === 0 ? (
            chips.length > 0 ? (
              <EmptyState title="No papers match these filters" action={<button type="button" onClick={() => setSearch(clearPaperFilters(search))}>Clear all filters</button>}>
                Remove a filter above, or clear them all.
              </EmptyState>
            ) : (
              <EmptyState title="This run has no papers yet">If it is still running, its papers appear when it finishes (see Runs).</EmptyState>
            )
          ) : (
            <ErrorBoundary label="the paper table">
              <PaperTable
                legacy={legacy}
                rows={papers.data.items} stages={stages.data ?? []} sort={view.params.sort} direction={view.params.direction}
                onSort={(sort) => change({ sort, dir: view.params.sort === sort && view.params.direction === "asc" ? "desc" : "asc" })}
                selectedPaperId={view.paperId} onOpen={(paper) => change({ paper }, false)}
                selectedStageId={view.stageId} onSelectStage={(stage) => change({ stage: view.stageId === stage ? null : stage }, false)}
                selection={member ? { ids: selectedIds, onToggle: toggle, onToggleAll: toggleAll } : null}
                cursorId={cursor}
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
