import { Link } from "react-router-dom";

import { PURPOSE } from "../features/papers/StartPoint";

const STEPS = [
  { title: "Describe your topic", text: "Say what you look for in plain words. We suggest keywords and screening criteria; you keep what fits." },
  { title: "Preview the search", text: "See how many papers each source returns and the first titles, free and before any model runs." },
  { title: "Run, read, keep", text: "Start a run (demo mode works offline), read the evidence per paper and save the good ones to the team library." },
];

/** What Papers shows before there is anything to show: how to get there, in three steps. */
export function HomeEmpty({ member, hasRuns }: { member: boolean; hasRuns: boolean }) {
  return (
    <section className="home-empty" aria-labelledby="home-title">
      <p className="kicker">Welcome</p>
      <p className="purpose">{PURPOSE}</p>
      <h1 id="home-title">Create your first topic in 3 steps</h1>
      <p className="lede">{hasRuns ? "The runs so far have no papers yet. When one finishes, its papers appear here." : "A topic is a research question the agent searches and screens for. Nothing has run yet."}</p>
      <ol className="home-steps">
        {STEPS.map((step, i) => (
          <li key={step.title} className="rise">
            <span className="home-num" aria-hidden="true">{i + 1}</span>
            <h2>{step.title}</h2>
            <p>{step.text}</p>
          </li>
        ))}
      </ol>
      <div className="actions">
        {member ? (
          <>
            <Link className="button-link" to="/topics/new">Create your first topic</Link>
            <Link className="button-link button-link--quiet" to="/screening">Or start a run</Link>
          </>
        ) : (
          <p className="hint">You can read everything here; ask a member or an admin to create a topic and start a run.</p>
        )}
      </div>
    </section>
  );
}
