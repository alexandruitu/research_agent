import type { PaperRow, StageOut } from "../../api/types";
import { DecisionCell, ExtractCellView, FoundByCell, InSrCell, ReviewsCellView, ScoreCell, TopicMatchCell } from "./cells";
import { PipelineStrip } from "./PipelineStrip";

type Props = {
  rows: PaperRow[]; stages: StageOut[]; sort: string; direction: "asc" | "desc"; onSort: (sort: string) => void;
  selectedPaperId: string | null; onOpen: (paperId: string) => void; selectedStageId: string | null; onSelectStage: (id: string) => void;
};

function SortHeader({ label, sortKey, sort, direction, onSort }: { label: string; sortKey: string; sort: string; direction: string; onSort: (key: string) => void }) {
  const active = sort === sortKey;
  return (
    <th scope="col" aria-sort={active ? (direction === "asc" ? "ascending" : "descending") : "none"}>
      <button type="button" className="sort" onClick={() => onSort(sortKey)}>
        {label}{active ? (direction === "asc" ? " ▲" : " ▼") : ""}
      </button>
    </th>
  );
}

export function PaperTable({ rows, stages, sort, direction, onSort, selectedPaperId, onOpen, selectedStageId, onSelectStage }: Props) {
  const sortProps = { sort, direction, onSort };
  return (
    <div className="table-scroll">
      <table className="papers">
        <thead>
          <PipelineStrip stages={stages} selectedId={selectedStageId} onSelect={onSelectStage} />
          <tr>
            <SortHeader label="Paper" sortKey="title" {...sortProps} />
            <th scope="col">Found by</th>
            <SortHeader label="Topic match" sortKey="criterion:topic_match" {...sortProps} />
            <th scope="col">Decision</th>
            <th scope="col">Claims</th>
            <th scope="col">Reviewers A / B</th>
            <SortHeader label="Score" sortKey="score" {...sortProps} />
            <th scope="col">In SR</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => {
            const selected = selectedPaperId === row.paper.id;
            return (
              <tr key={row.paper.id} className={`${row.screen.decision === "exclude" ? "dropped" : ""} ${selected ? "selected" : ""}`} aria-current={selected ? "true" : undefined} onClick={() => onOpen(row.paper.id)}>
                <td>
                  <button type="button" className="linklike" data-open-paper={row.paper.id} onClick={(event) => { event.stopPropagation(); onOpen(row.paper.id); }}>
                    {row.paper.title}
                  </button>
                  <span className="sub">{row.paper.year ?? ""} {row.paper.source_id}</span>
                </td>
                <td><FoundByCell value={row.found_by} /></td>
                <td><TopicMatchCell screen={row.screen} /></td>
                <td><DecisionCell screen={row.screen} /></td>
                <td><ExtractCellView cell={row.extract} /></td>
                <td><ReviewsCellView cell={row.reviews} /></td>
                <td><ScoreCell rank={row.rank} /></td>
                <td><InSrCell value={row.in_sr} /></td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
