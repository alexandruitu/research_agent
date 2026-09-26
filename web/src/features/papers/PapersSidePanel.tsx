import type { StageOut } from "../../api/types";

type Props = { runId: string; paperId: string | null; stageId: string | null; stages: StageOut[]; onClose: () => void };

export function PapersSidePanel({ paperId, stageId }: Props) {
  return <aside aria-label="Details" data-paper={paperId ?? ""} data-stage={stageId ?? ""} />;
}
