import type { StageOut } from "../../api/types";
import { PaperDrawer } from "./PaperDrawer";
import { StagePanel } from "./StagePanel";

type Props = { runId: string; paperId: string | null; stageId: string | null; stages: StageOut[]; onClose: () => void; detailsOpen?: boolean };

export function PapersSidePanel({ runId, paperId, stageId, stages, onClose, detailsOpen = true }: Props) {
  if (paperId) return <PaperDrawer key={`${paperId}-${detailsOpen}`} runId={runId} paperId={paperId} onClose={onClose} detailsOpen={detailsOpen} />;
  const stage = stages.find((s) => s.id === stageId);
  return stage ? <StagePanel stage={stage} onClose={onClose} /> : null;
}
