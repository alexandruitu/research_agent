import type { ReactNode } from "react";
import { Link } from "react-router-dom";

export type FlowStep = 1 | 2 | 3 | 4;

const STEPS: { n: FlowStep; label: string; to: string | null }[] = [
  { n: 1, label: "Topics", to: "/topics" },
  { n: 2, label: "Screening", to: "/screening" },
  { n: 3, label: "Results", to: "/results" },
  // Read opens from a paper in Results or the Library: there is no page to jump to
  { n: 4, label: "Read", to: null },
];

/** A thin line over the four flow pages: where you are (in words, not only by colour), and an optional Next. */
export function FlowStepper({ current, next }: { current: FlowStep; next?: ReactNode }) {
  return (
    <div className="flow-bar">
      <nav aria-label="Research steps" className="flow-stepper">
        <ol>
          {STEPS.map((step) => {
            const here = step.n === current;
            const state = here ? "is-current" : step.n < current ? "is-done" : "";
            const body = (
              <>
                <span className="flow-num" aria-hidden="true">{step.n}</span>
                <span className="sr-only">Step {step.n}:</span>{" "}
                <span className="flow-label">{step.label}</span>
                {here && <span className="sr-only"> (you are here)</span>}
              </>
            );
            return (
              <li key={step.n} className={state}>
                {step.to && !here ? <Link to={step.to}>{body}</Link> : <span aria-current={here ? "step" : undefined}>{body}</span>}
              </li>
            );
          })}
        </ol>
      </nav>
      {next && <div className="flow-next">{next}</div>}
    </div>
  );
}
