import type { EvalJobOut, EvalJobProgress } from "../../api/types";
import { Chips, KindBadge } from "./KindBadge";
import { dateText } from "./words";

const STATUS: Record<string, { icon: string; word: string }> = {
  queued: { icon: "…", word: "queued" }, running: { icon: "↻", word: "running" }, failed: { icon: "!", word: "failed" }, done: { icon: "✓", word: "done" },
};

export function stepText(progress: EvalJobProgress): string | null {
  const steps = progress.steps ?? [];
  if (!progress.step || steps.length === 0) return null;
  const index = steps.indexOf(progress.step);
  return `step ${index + 1} of ${steps.length}: ${progress.step}`;
}

/** One evaluation that has no report yet. */
export function EvalJobRow({ item }: { item: EvalJobOut }) {
  const progress = item.job.progress as EvalJobProgress;
  const status = STATUS[item.job.status] ?? { icon: "·", word: item.job.status };
  const step = stepText(progress);
  const counted = typeof progress.total === "number" && progress.total > 0;
  return (
    <li className={`eval-job eval-job--${item.job.status}`}>
      <div className="eval-job-head">
        <KindBadge kind={item.kind} />
        <span className={`pill pill--run-${item.job.status}`}><span aria-hidden="true">{status.icon}</span> {status.word}</span>
        <span className="sub-inline">started {dateText(item.job.created_at)}</span>
      </div>
      {step && <p className="eval-job-step">{step}{counted && ` · ${progress.done ?? 0} of ${progress.total} papers`}</p>}
      {counted && <progress max={progress.total} value={progress.done ?? 0} aria-label="Papers done" />}
      <Chips chips={item.chips} />
      {item.job.error && <p className="form-error">{item.job.error}</p>}
    </li>
  );
}

export function EvalJobs({ jobs }: { jobs: EvalJobOut[] }) {
  if (jobs.length === 0) return null;
  return (
    <section aria-label="In progress" className="eval-jobs">
      <h2>In progress</h2>
      <ul>{jobs.map((j) => <EvalJobRow key={j.job.id} item={j} />)}</ul>
    </section>
  );
}
