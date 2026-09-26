import type { StageOut } from "../../api/types";

export const STRIP = [
  { id: "paper", span: 1 }, { id: "search", span: 1 }, { id: "screen", span: 2 }, { id: "extract", span: 1 },
  { id: "reviewers", span: 1 }, { id: "rank", span: 1 }, { id: "sr", span: 1 },
] as const;

const STATUS_WORDS: Record<StageOut["status"], string> = { measured: "measured", caveat: "caveat", unmeasured: "not measured", input: "input" };

export function statusText(stage: StageOut) {
  return stage.status === "caveat" && stage.caveat ? stage.caveat : STATUS_WORDS[stage.status];
}

/** The first header row: the pipeline as column groups. Each stage button says what the stage is and whether it is measured. */
export function PipelineStrip({ stages, selectedId, onSelect }: { stages: StageOut[]; selectedId: string | null; onSelect: (id: string) => void }) {
  const byId = new Map(stages.map((stage) => [stage.id, stage]));
  return (
    <tr className="strip">
      {STRIP.map(({ id, span }) => {
        const stage = byId.get(id);
        if (!stage) {
          return <th key={id} colSpan={span} className="strip-plain">{id === "sr" ? "SR label" : ""}</th>;
        }
        return (
          <th key={id} colSpan={span} scope="colgroup" className={`strip-stage strip-stage--${stage.status}`}>
            <button type="button" className="stage" data-status={stage.status} aria-pressed={selectedId === id} onClick={() => onSelect(id)}>
              <span className="stage-title">{stage.title}</span>
              <span className="stage-status">{statusText(stage)}</span>
              {stage.headline && <span className="stage-headline">{stage.headline}</span>}
            </button>
          </th>
        );
      })}
    </tr>
  );
}
