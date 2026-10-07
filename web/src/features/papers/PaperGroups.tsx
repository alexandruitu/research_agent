import { useEffect, useId, useMemo, useState } from "react";

import { ApiError } from "../../api/client";
import { usePaperGroups, usePapers, type GroupDimension, type PaperParams } from "../../api/hooks";
import type { PaperGroupOut, PaperRow } from "../../api/types";
import { Skeleton } from "../../components/ui/Skeleton";
import { Tooltip } from "../../components/ui/Tooltip";
import { emptyGroupReason, QUALITY_ONELINER, groupIcon, groupName, readCollapsed, writeCollapsed } from "./groups";

const STEP = 25;
const MAX_SIZE = 200; // the API's largest page

const errorText = (error: unknown) => (error instanceof ApiError ? `${error.message} (request ${error.requestId})` : "Could not reach the server.");

type Props = {
  runId: string;
  by: GroupDimension;
  /** The page's filters and sort (page and page size are per group). */
  params: PaperParams;
  userId: string;
  /** Renders one group's rows (the page passes its PaperTable with selection, cursor and drawer wiring). */
  renderTable: (rows: PaperRow[], key: string) => React.ReactNode;
  /** The rows each open group shows, in group order, so shortcuts and selection span the groups. */
  onRows: (key: string, rows: PaperRow[]) => void;
  onGroups?: (keys: string[], collapsed: Set<string>) => void;
  /** Simple view: headers show name, count and a one-liner; the rule moves behind a "?". */
  simple?: boolean;
};

export function PaperGroups({ runId, by, params, userId, renderTable, onRows, onGroups, simple = false }: Props) {
  const groups = usePaperGroups(runId, by, params);
  const [collapsed, setCollapsed] = useState<{ by: GroupDimension; keys: Set<string> }>(() => ({ by, keys: readCollapsed(userId, by) }));
  const keys = useMemo(() => (collapsed.by === by ? collapsed.keys : readCollapsed(userId, by)), [collapsed, by, userId]);
  const save = (next: Set<string>) => {
    setCollapsed({ by, keys: next });
    writeCollapsed(userId, by, next);
  };
  const all = useMemo(() => groups.data ?? [], [groups.data]);
  // empty groups are hidden; one line names them, each with a "why?" explanation
  const list = useMemo(() => all.filter((g) => g.count > 0), [all]);
  const empty = all.filter((g) => g.count === 0);
  useEffect(() => {
    onGroups?.(list.map((g) => g.key), keys);
  }, [list, keys, onGroups]);

  if (groups.isError) return <p role="alert" className="form-error">{errorText(groups.error)}</p>;
  if (!groups.data) return <Skeleton label="the groups" rows={6} />;
  if (list.length === 0) return <p className="sub-inline">No papers to group.</p>;
  const emptyLine = empty.length > 0 && (
    <p className="groups-empty">
      <span>Empty:</span>
      {empty.map((g) => (
        <Tooltip key={g.key} className="groups-empty-item" trigger={<span>{groupName(by, g.key, g.label)} <span className="sub-inline">— why?</span></span>}
          tip={by === "quality" ? emptyGroupReason(g.key, all) : g.rule} />
      ))}
    </p>
  );
  const toggle = (key: string) => {
    const next = new Set(keys);
    if (next.has(key)) next.delete(key); else next.add(key);
    save(next);
  };
  return (
    <div className="paper-groups">
      <div className="group-tools" role="group" aria-label="Groups">
        <button type="button" onClick={() => save(new Set())}>Expand all</button>
        <button type="button" onClick={() => save(new Set(list.map((g) => g.key)))}>Collapse all</button>
      </div>
      {emptyLine}
      {list.map((group) => (
        <GroupSection key={group.key} by={by} group={group} simple={simple} open={!keys.has(group.key)} onToggle={() => toggle(group.key)}>
          <GroupBody runId={runId} by={by} group={group} params={params} renderTable={renderTable} onRows={onRows} />
        </GroupSection>
      ))}
    </div>
  );
}

function GroupSection({ by, group, open, onToggle, children, simple }: { by: GroupDimension; group: PaperGroupOut; open: boolean; onToggle: () => void; children: React.ReactNode; simple: boolean }) {
  const id = useId();
  const icon = groupIcon(by, group.key);
  const name = groupName(by, group.key, group.label);
  return (
    <section className={`paper-group paper-group--${by === "quality" ? group.key : "plain"} ${open ? "is-open" : ""}`} aria-labelledby={`${id}-head`}>
      <h2 className="paper-group-head">
        <button type="button" id={`${id}-head`} aria-expanded={open} aria-controls={`${id}-body`} onClick={onToggle} title={group.rule}>
          <span className="group-chevron" aria-hidden="true">{open ? "▾" : "▸"}</span>
          {icon && <span className="group-icon" aria-hidden="true">{icon}</span>}
          <span className="group-name">{name}</span>{" "}
          <span className="group-count">{group.count} {group.count === 1 ? "paper" : "papers"}</span>
        </button>
      </h2>
      {simple ? (
        <p className="group-rule group-rule--simple">
          {(by === "quality" && QUALITY_ONELINER[group.key]) || null}{" "}
          <Tooltip trigger={<span className="term-q" aria-hidden="true" />} triggerLabel={`How “${name}” is decided`} className="term-tip" tip={group.rule} />
        </p>
      ) : <p className="group-rule">{group.rule}</p>}
      <div id={`${id}-body`} hidden={!open}>
        {open && (group.count === 0 ? <p className="sub-inline group-empty">No papers in this group.</p> : children)}
      </div>
    </section>
  );
}

function GroupBody({ runId, by, group, params, renderTable, onRows }: { runId: string; by: GroupDimension; group: PaperGroupOut; params: PaperParams; renderTable: Props["renderTable"]; onRows: Props["onRows"] }) {
  const [size, setSize] = useState(STEP);
  const [page, setPage] = useState(1);
  const papers = usePapers(runId, { ...params, page, page_size: size, group_by: by, group: group.key });
  const rows = papers.data?.items;
  useEffect(() => {
    if (rows) onRows(group.key, rows);
  }, [rows, group.key, onRows]);
  useEffect(() => () => onRows(group.key, []), [group.key, onRows]);

  if (papers.isError) return <p role="alert" className="form-error">{errorText(papers.error)}</p>;
  if (!papers.data) return <Skeleton label={`the ${group.label} papers`} rows={3} />;
  const total = papers.data.total;
  const shown = (page - 1) * size + papers.data.items.length;
  const pages = Math.ceil(total / size);
  return (
    <>
      {renderTable(papers.data.items, group.key)}
      <div className="group-more">
        <span className="sub-inline" aria-live="polite">Showing {page > 1 ? `${(page - 1) * size + 1}–${shown}` : shown} of {total}</span>
        {size < MAX_SIZE && shown < total && (
          <button type="button" onClick={() => setSize(Math.min(MAX_SIZE, size + STEP))}>Show {Math.min(STEP, total - shown)} more</button>
        )}
        {size >= MAX_SIZE && pages > 1 && (
          <>
            <button type="button" disabled={page <= 1} onClick={() => setPage(page - 1)}>Previous {MAX_SIZE}</button>
            <button type="button" disabled={page >= pages} onClick={() => setPage(page + 1)}>Next {MAX_SIZE}</button>
          </>
        )}
      </div>
    </>
  );
}
