import { useEffect, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";

import { ApiError } from "../api/client";
import { exportUrl, useCollections, useFields, useLibrary } from "../api/hooks";
import { hasRole } from "../api/types";
import { useAuth } from "../auth/AuthProvider";
import { EmptyState } from "../components/ui/EmptyState";
import { useShortcuts } from "../components/ui/shortcuts";
import { ShortcutsHelp } from "../components/ui/ShortcutsHelp";
import { Skeleton } from "../components/ui/Skeleton";
import { LIBRARY_STATUSES, STATUS_META, statusMeta } from "../components/ui/StatusMark";
import { CollectionsManager } from "../features/library/CollectionsManager";
import { clearFilters, LIBRARY_PAGE_SIZE, parseLibraryView, patchLibraryView, type LibraryChange } from "../features/library/libraryState";
import { LibraryList } from "../features/library/LibraryList";
import { useStatusChange } from "../features/library/optimistic";
import { ReadingPane } from "../features/library/ReadingPane";

const SORT_LABEL: Record<string, string> = { added_at: "Date saved", title: "Title", year: "Year", score: "Score", status: "Status" };
export const LIBRARY_SHORTCUTS = [
  { keys: ["j", "k"], what: "Next / previous paper" },
  { keys: ["o"], what: "Open the paper under the cursor (or Enter on it)" },
  { keys: ["1", "2", "3", "4"], what: "Status: to read, read, useful, rejected" },
  { keys: ["/"], what: "Search" },
  { keys: ["Esc"], what: "Close the reading pane" },
  { keys: ["?"], what: "This list" },
];

export function LibraryPage() {
  const { user } = useAuth();
  const member = hasRole(user, "member");
  const admin = hasRole(user, "admin");
  const [search, setSearch] = useSearchParams();
  const view = parseLibraryView(search);
  const { params } = view;
  const library = useLibrary(params);
  const collections = useCollections();
  const fields = useFields();
  const status = useStatusChange();
  const [cursor, setCursor] = useState<string | null>(null);
  const [help, setHelp] = useState(false);
  const [manage, setManage] = useState(false);
  const [q, setQ] = useState(params.q ?? "");
  const searchBox = useRef<HTMLInputElement>(null);
  const change = (changes: LibraryChange) => setSearch(patchLibraryView(search, changes));
  useEffect(() => setQ(params.q ?? ""), [params.q]);

  const items = library.data?.items ?? [];
  const total = library.data?.total ?? 0;
  const pages = Math.max(1, Math.ceil(total / LIBRARY_PAGE_SIZE));
  const cursorIndex = Math.max(0, items.findIndex((i) => i.id === (cursor ?? view.itemId)));
  const open = (id: string | null) => {
    change({ item: id });
    if (id) setCursor(id);
  };
  const move = (delta: number) => {
    if (!items.length) return;
    const next = items[Math.min(items.length - 1, Math.max(0, cursorIndex + delta))]!;
    setCursor(next.id);
    document.querySelector<HTMLElement>(`[data-item="${next.id}"]`)?.focus();
  };
  const close = () => {
    const was = view.itemId;
    change({ item: null });
    if (was) requestAnimationFrame(() => document.querySelector<HTMLElement>(`[data-item="${was}"]`)?.focus());
  };
  const target = items.find((i) => i.id === (view.itemId ?? cursor)) ?? items[cursorIndex];
  const setStatus = (n: number) => {
    const to = LIBRARY_STATUSES[n];
    if (member && target && to) void status.change(target.id, target.status, to);
  };
  useShortcuts({
    j: () => move(1), k: () => move(-1),
    o: () => target && open(target.id),
    "1": () => setStatus(0), "2": () => setStatus(1), "3": () => setStatus(2), "4": () => setStatus(3),
    "/": () => searchBox.current?.focus(), "?": () => setHelp(true), Escape: () => (help ? setHelp(false) : view.itemId && close()),
  });

  const collectionName = (id: string) => collections.data?.find((c) => c.id === id)?.name ?? "a collection";
  const fieldName = (id: string) => fields.data?.find((f) => f.id === id)?.name ?? "a field";
  type Chip = { label: string; clear: LibraryChange };
  const chips = ([
    params.q ? { label: `Words: “${params.q}”`, clear: { q: null } } : null,
    params.collection_id ? { label: `Collection: ${collectionName(params.collection_id)}`, clear: { collection: null } } : null,
    params.status ? { label: `Status: ${statusMeta(params.status).word}`, clear: { status: null } } : null,
    params.tag ? { label: `Tag: #${params.tag}`, clear: { tag: null } } : null,
    params.field_id ? { label: `Field: ${fieldName(params.field_id)}`, clear: { field: null } } : null,
    params.min_score != null ? { label: `Score ≥ ${params.min_score}`, clear: { min: null } } : null,
    params.has_red_flags ? { label: "Has red flags", clear: { flags: null } } : null,
  ] as (Chip | null)[]).filter((c): c is Chip => c !== null);
  const tags = [...new Set(items.flatMap((i) => i.tags))].sort();
  if (params.tag && !tags.includes(params.tag)) tags.unshift(params.tag);

  return (
    <section className="library-page">
      <div className="page-head">
        <div>
          <h1>Library</h1>
          <p className="lede">Papers the team chose to keep, with their evidence frozen at the time they were saved.</p>
        </div>
        <div className="actions">
          <a className="button-link button-link--quiet" href={exportUrl(params, "csv")} download>Export CSV</a>
          <a className="button-link button-link--quiet" href={exportUrl(params, "bibtex")} download>Export BibTeX</a>
          <button type="button" aria-expanded={manage} onClick={() => setManage((m) => !m)}>Manage collections</button>
          <button type="button" className="kbd-button" onClick={() => setHelp(true)} aria-label="Keyboard shortcuts"><kbd aria-hidden="true">?</kbd></button>
        </div>
      </div>
      {manage && <CollectionsManager admin={admin} member={member} />}
      <form className="library-toolbar" role="search" onSubmit={(e) => { e.preventDefault(); change({ q: q.trim() || null }); }}>
        <label className="search-box">
          <span className="sr-only">Search title, abstract and note</span>
          <input ref={searchBox} type="search" value={q} placeholder="Search title, abstract, note…  ( / )" onChange={(e) => setQ(e.target.value)} />
        </label>
        <button type="submit">Search</button>
        <label>Sort
          <select value={params.sort} onChange={(e) => change({ sort: e.target.value })}>
            {Object.entries(SORT_LABEL).map(([key, label]) => <option key={key} value={key}>{label}</option>)}
          </select>
        </label>
        <button type="button" onClick={() => change({ dir: params.direction === "asc" ? "desc" : "asc" })} aria-label={`Sort direction: ${params.direction === "asc" ? "ascending" : "descending"}`}>
          {params.direction === "asc" ? "↑ Ascending" : "↓ Descending"}
        </button>
      </form>
      <div className="filters library-filters" role="group" aria-label="Filters">
        <div className="segmented-buttons" role="group" aria-label="Status">
          {LIBRARY_STATUSES.map((s) => (
            <button key={s} type="button" aria-pressed={params.status === s} onClick={() => change({ status: params.status === s ? null : s })}>
              <span aria-hidden="true">{STATUS_META[s].icon}</span> {STATUS_META[s].word}
            </button>
          ))}
        </div>
        <label>Collection
          <select value={params.collection_id ?? ""} onChange={(e) => change({ collection: e.target.value || null })}>
            <option value="">any</option>
            {(collections.data ?? []).map((c) => <option key={c.id} value={c.id}>{c.name} ({c.item_count})</option>)}
          </select>
        </label>
        <label>Tag
          <select value={params.tag ?? ""} onChange={(e) => change({ tag: e.target.value || null })}>
            <option value="">any</option>
            {tags.map((t) => <option key={t} value={t}>#{t}</option>)}
          </select>
        </label>
        <label>Field
          <select value={params.field_id ?? ""} onChange={(e) => change({ field: e.target.value || null })}>
            <option value="">any</option>
            {(fields.data ?? []).map((f) => <option key={f.id} value={f.id}>{f.name}</option>)}
          </select>
        </label>
        <label>Min score
          <input type="number" min={0} max={100} step={5} value={params.min_score ?? ""} onChange={(e) => change({ min: e.target.value === "" ? null : Number(e.target.value) })} />
        </label>
        <button type="button" aria-pressed={!!params.has_red_flags} onClick={() => change({ flags: params.has_red_flags ? null : true })}><span aria-hidden="true">⚑</span> Has red flags</button>
      </div>
      {chips.length > 0 && (
        <div className="active-filters" role="group" aria-label="Active filters">
          {chips.map((chip) => (
            <button key={chip.label} type="button" className="active-chip" onClick={() => change(chip.clear)}>
              {chip.label} <span aria-hidden="true">×</span><span className="sr-only"> (remove filter)</span>
            </button>
          ))}
          <button type="button" className="linklike" onClick={() => setSearch(clearFilters(search))}>Clear all</button>
        </div>
      )}
      <div className={`library-layout ${view.itemId ? "with-pane" : ""}`}>
        <div className="library-main">
          <p className="summary" aria-live="polite">{library.data ? `${total} paper${total === 1 ? "" : "s"}` : ""}</p>
          {library.isLoading ? (
            <Skeleton label="the library" rows={6} />
          ) : library.isError ? (
            <p role="alert" className="form-error">{library.error instanceof ApiError ? library.error.message : "Could not load the library."}</p>
          ) : items.length === 0 ? (
            chips.length > 0 ? (
              <EmptyState title="Nothing matches these filters" action={<button type="button" onClick={() => setSearch(clearFilters(search))}>Clear all filters</button>}>
                Try fewer filters or other words.
              </EmptyState>
            ) : (
              <EmptyState title="The library is empty" action={<Link className="button-link" to="/">Go to Papers</Link>}>
                <p>Open a run in Papers, tick the papers worth keeping and press <strong>Save to library</strong>.</p>
                <p>They arrive here with their screening and review evidence, ready for the team to read, tag and rate.</p>
              </EmptyState>
            )
          ) : (
            <>
              <LibraryList items={items} openId={view.itemId} cursorId={cursor} onOpen={open} />
              {pages > 1 && (
                <nav className="pager" aria-label="Pages">
                  <button type="button" disabled={(params.page ?? 1) <= 1} onClick={() => change({ page: (params.page ?? 1) - 1 })}>Previous page</button>
                  <span>Page {params.page} of {pages}</span>
                  <button type="button" disabled={(params.page ?? 1) >= pages} onClick={() => change({ page: (params.page ?? 1) + 1 })}>Next page</button>
                </nav>
              )}
              <p className="kbd-hint">Tip: <kbd>j</kbd> <kbd>k</kbd> to move, <kbd>o</kbd> to open, <kbd>1</kbd>–<kbd>4</kbd> to set the status, <kbd>?</kbd> for all shortcuts.</p>
            </>
          )}
        </div>
        {view.itemId && <ReadingPane key={view.itemId} itemId={view.itemId} onClose={close} />}
      </div>
      {help && <ShortcutsHelp title="Library shortcuts" items={LIBRARY_SHORTCUTS} onClose={() => setHelp(false)} />}
    </section>
  );
}
