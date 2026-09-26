import { Link } from "react-router-dom";

import type { StageOut } from "../../api/types";
import { statusText } from "./PipelineStrip";

export function StagePanel({ stage, onClose, showPapersLink = false }: { stage: StageOut; onClose?: () => void; showPapersLink?: boolean }) {
  return (
    <aside aria-label={`About ${stage.title}`} className="side-panel">
      <div className="panel-head">
        <h2>{stage.title}</h2>
        {onClose && <button type="button" onClick={onClose} aria-label="Close stage details">×</button>}
      </div>
      <p><span className={`pill pill--${stage.status}`}>{stage.status === "caveat" ? `caveat: ${stage.caveat ?? "see limits"}` : statusText(stage)}</span> {stage.headline}</p>
      <h3>What it does</h3>
      <p>{stage.summary}</p>
      <h3>Known limits</h3>
      <p>{stage.limits}</p>
      <p className="links">
        {stage.data_link === "evals" && <Link to="/evals">Open the eval report</Link>}
        {stage.data_link === "papers" && showPapersLink && <Link to="/">See the screened papers</Link>}
      </p>
    </aside>
  );
}
