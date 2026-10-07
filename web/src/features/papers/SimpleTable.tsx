import type { PaperRow } from "../../api/types";
import { CriteriaLine } from "./cells";
import { QUALITY_ICON, QUALITY_LABEL } from "./groups";
import { LibraryBadge } from "./PaperTable";
import { whySentence } from "./why";
import { Term } from "../../components/ui/Term";

type Props = {
  rows: PaperRow[];
  selectedPaperId: string | null;
  onOpen: (paperId: string) => void;
  /** Criterion key → text, for the why sentence and the criteria tooltip. */
  texts: Record<string, string>;
  selection?: { ids: Set<string>; onToggle: (paperId: string, on: boolean) => void; onToggleAll: (on: boolean) => void } | null;
  cursorId?: string | null;
  /** Members save one paper from its row; null for viewers. */
  onSave?: ((paperId: string) => void) | null;
};

/** The Simple view: what the paper is, which group it is in, why, and whether it is in the library. */
export function SimpleTable({ rows, selectedPaperId, onOpen, texts, selection = null, cursorId = null, onSave = null }: Props) {
  return (
    <div className="table-scroll">
      <table className="papers papers--simple">
        <thead>
          <tr>
            {selection && (
              <th scope="col" className="select-col">
                <input type="checkbox" aria-label="Select all papers on this page" checked={rows.length > 0 && rows.every((r) => selection.ids.has(r.paper.id))}
                  onChange={(e) => selection.onToggleAll(e.target.checked)} />
              </th>
            )}
            <th scope="col" className="col-paper">Paper</th>
            <th scope="col"><Term k="quality">Quality</Term></th>
            <th scope="col"><Term k="criterion">Criteria</Term></th>
            <th scope="col" className="col-why">Why</th>
            <th scope="col"><Term k="team_decision">Team decision</Term></th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => {
            const selected = selectedPaperId === row.paper.id;
            const group = row.group ?? null;
            return (
              <tr key={row.paper.id} className={`${row.screen.decision === "exclude" ? "dropped" : ""} ${selected ? "selected" : ""} ${cursorId === row.paper.id ? "is-cursor" : ""} ${selection?.ids.has(row.paper.id) ? "is-checked" : ""}`} aria-current={selected ? "true" : undefined} onClick={() => onOpen(row.paper.id)}>
                {selection && (
                  <td className="select-col" onClick={(e) => e.stopPropagation()}>
                    <input type="checkbox" aria-label={`Select ${row.paper.title}`} checked={selection.ids.has(row.paper.id)} onChange={(e) => selection.onToggle(row.paper.id, e.target.checked)} />
                  </td>
                )}
                <td className="col-paper">
                  <button type="button" id={`title-${row.paper.id}`} className="linklike title-clamp" title={row.paper.title} data-open-paper={row.paper.id} onClick={(event) => { event.stopPropagation(); onOpen(row.paper.id); }}>
                    {row.paper.title}
                  </button>
                  <span className="sub">{row.paper.year ?? "year unknown"} · {row.paper.source_id}</span>
                </td>
                <td className={`col-group group-tag--${group ?? "none"}`}>
                  {group ? <span className="group-tag"><span aria-hidden="true">{QUALITY_ICON[group] ?? ""}</span> {QUALITY_LABEL[group] ?? group}</span> : <span className="na">–</span>}
                </td>
                <td onClick={(e) => e.stopPropagation()}><CriteriaLine screen={row.screen} texts={texts} /></td>
                <td className="col-why">{whySentence(row, { texts })}</td>
                <td onClick={(e) => e.stopPropagation()}>
                  {row.library ? <LibraryBadge library={row.library} />
                    : onSave ? <button type="button" className="row-save" aria-describedby={`title-${row.paper.id}`} onClick={() => onSave(row.paper.id)}>Save</button>
                      : <span className="sub">not saved</span>}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
