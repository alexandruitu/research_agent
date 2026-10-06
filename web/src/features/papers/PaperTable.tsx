import { Link } from "react-router-dom";

import type { PaperRow } from "../../api/types";
import { statusMeta } from "../../components/ui/StatusMark";
import { CriteriaCell, DecisionCell, ExtractCellView, FoundByCell, InSrCell, isPanelRun, PanelScoreCell, RedFlagsCell, ReviewsCellView, ScoreCell, TextSourceCell } from "./cells";

type Props = {
  rows: PaperRow[]; sort: string; direction: "asc" | "desc"; onSort: (sort: string) => void;
  selectedPaperId: string | null; onOpen: (paperId: string) => void; legacy: boolean;
  /** Members pick rows to save to the library; null hides the checkboxes. */
  selection?: { ids: Set<string>; onToggle: (paperId: string, on: boolean) => void; onToggleAll: (on: boolean) => void } | null;
  cursorId?: string | null;
};

/** "In library · ★ Relevant", linking to the item (a pending save shows "Saving…"). */
export function LibraryBadge({ library }: { library: PaperRow["library"] }) {
  if (!library) return null;
  const { icon, word } = statusMeta(library.status);
  if (library.item_id.startsWith("pending-")) return <span className="lib-badge is-pending">Saving to library…</span>;
  return (
    <Link className="lib-badge" to={`/library?item=${library.item_id}`} onClick={(e) => e.stopPropagation()}>
      In library · <span aria-hidden="true">{icon}</span> {word}
    </Link>
  );
}

function SortHeader({ label, sortKey, sort, direction, onSort, className }: { label: string; sortKey: string; sort: string; direction: string; onSort: (key: string) => void; className?: string }) {
  const active = sort === sortKey;
  return (
    <th scope="col" className={className} aria-sort={active ? (direction === "asc" ? "ascending" : "descending") : "none"}>
      <button type="button" className="sort" onClick={() => onSort(sortKey)}>
        {label}{active ? (direction === "asc" ? " ▲" : " ▼") : ""}
      </button>
    </th>
  );
}

export function PaperTable({ rows, sort, direction, onSort, selectedPaperId, onOpen, legacy, selection = null, cursorId = null }: Props) {
  const sortProps = { sort, direction, onSort };
  const panel = isPanelRun(rows);
  return (
    <div className="table-scroll">
      <table className="papers">
        <thead>
          <tr>
            {selection && (
              <th scope="col" className="select-col">
                <input type="checkbox" aria-label="Select all papers on this page" checked={rows.length > 0 && rows.every((r) => selection.ids.has(r.paper.id))}
                  onChange={(e) => selection.onToggleAll(e.target.checked)} />
              </th>
            )}
            <SortHeader label="Paper" sortKey="title" className="col-paper" {...sortProps} />
            <th scope="col">Found by</th>
            {legacy ? <SortHeader label="Criteria" sortKey="criterion:topic_match" className="col-criteria" {...sortProps} /> : <th scope="col" className="col-criteria">Criteria</th>}
            <th scope="col">Decision</th>
            <th scope="col">Claims</th>
            {panel ? (
              <>
                <SortHeader label="Peer review score" sortKey="score" {...sortProps} />
                <th scope="col">Red flags</th>
                <th scope="col">Text reviewed</th>
              </>
            ) : (
              <>
                <th scope="col">Reviewers A / B</th>
                <SortHeader label="Score" sortKey="score" {...sortProps} />
              </>
            )}
            <th scope="col">In SR</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => {
            const selected = selectedPaperId === row.paper.id;
            return (
              <tr key={row.paper.id} className={`${row.screen.decision === "exclude" ? "dropped" : ""} ${selected ? "selected" : ""} ${cursorId === row.paper.id ? "is-cursor" : ""} ${selection?.ids.has(row.paper.id) ? "is-checked" : ""}`} aria-current={selected ? "true" : undefined} onClick={() => onOpen(row.paper.id)}>
                {selection && (
                  <td className="select-col" onClick={(e) => e.stopPropagation()}>
                    <input type="checkbox" aria-label={`Select ${row.paper.title}`} checked={selection.ids.has(row.paper.id)} onChange={(e) => selection.onToggle(row.paper.id, e.target.checked)} />
                  </td>
                )}
                <td className="col-paper">
                  <button type="button" className="linklike title-clamp" title={row.paper.title} data-open-paper={row.paper.id} onClick={(event) => { event.stopPropagation(); onOpen(row.paper.id); }}>
                    {row.paper.title}
                  </button>
                  <span className="sub">{row.paper.year ?? "year unknown"} · {row.paper.source_id}</span>
                  <LibraryBadge library={row.library ?? null} />
                </td>
                <td><FoundByCell foundBy={row.found_by} sources={row.sources ?? []} /></td>
                <td className="col-criteria"><CriteriaCell screen={row.screen} /></td>
                <td><DecisionCell screen={row.screen} /></td>
                <td><ExtractCellView cell={row.extract} /></td>
                {panel ? (
                  <>
                    <td><PanelScoreCell score={row.score} coverage={row.coverage} provisional={row.provisional} answered={row.checklist_answered} total={row.checklist_total} /></td>
                    <td><RedFlagsCell count={row.red_flag_count} /></td>
                    <td><TextSourceCell source={row.text_source} /></td>
                  </>
                ) : (
                  <>
                    <td><ReviewsCellView cell={row.reviews} /></td>
                    <td><ScoreCell rank={row.rank} /></td>
                  </>
                )}
                <td><InSrCell value={row.in_sr} /></td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
