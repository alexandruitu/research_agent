export const STEPS = [
  { n: 1, title: "Describe", hint: "In your own words" },
  { n: 2, title: "Keywords & criteria", hint: "What the search and screen use" },
  { n: 3, title: "Preview & save", hint: "See what comes back" },
] as const;
export type StepNumber = 1 | 2 | 3;

/** The spine of the editor: three numbered steps; the line fills as steps are done. All stay reachable. */
export function Stepper({ step, done, onStep }: { step: StepNumber; done: Record<StepNumber, boolean>; onStep: (step: StepNumber) => void }) {
  return (
    <nav aria-label="Steps" className="stepper">
      <ol>
        {STEPS.map((s) => (
          <li key={s.n} className={`${s.n === step ? "is-current" : ""} ${done[s.n] ? "is-done" : ""}`}>
            <button type="button" aria-current={s.n === step ? "step" : undefined} onClick={() => onStep(s.n)}>
              <span className="step-dot" aria-hidden="true">{done[s.n] && s.n !== step ? "✓" : s.n}</span>
              <span className="step-text">
                <span className="step-title">{s.title}</span>
                <span className="step-hint">{done[s.n] ? "done" : s.hint}</span>
              </span>
              <span className="sr-only">{`Step ${s.n} of 3`}</span>
            </button>
          </li>
        ))}
      </ol>
    </nav>
  );
}
