import type { StageOut } from "../../api/types";
import { statusText } from "../papers/PipelineStrip";

export function SystemMap({ stages, selectedId, onSelect }: { stages: StageOut[]; selectedId: string | null; onSelect: (id: string) => void }) {
  return (
    <ol className="pipeline" aria-label="Pipeline">
      {stages.map((stage, index) => (
        <li key={stage.id}>
          <button type="button" className={`stage stage--${stage.status}`} data-status={stage.status} aria-pressed={selectedId === stage.id} onClick={() => onSelect(stage.id)}>
            <span className="stage-index" aria-hidden="true">{index + 1}</span>
            <span className="stage-title">{stage.title}</span>
            <span className="stage-status">{statusText(stage)}</span>
            {stage.headline && <span className="stage-headline">{stage.headline}</span>}
          </button>
        </li>
      ))}
    </ol>
  );
}
