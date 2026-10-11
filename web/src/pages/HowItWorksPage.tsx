import { DESIGN_RULES, FLOW, FLOW_RULES, MODULES, STATISTICIAN } from "../features/validation/content";

function KindTag({ kind }: { kind: "AI" | "Code" }) {
  return <span className={`kind-tag kind-tag--${kind === "AI" ? "ai" : "code"}`}>{kind === "AI" ? "AI" : "Code"}</span>;
}

function Flow() {
  return (
    <section aria-labelledby="hiw-flow">
      <h2 id="hiw-flow">1. Execution flow: what runs when</h2>
      <p>
        Literature Radar is a pipeline of structured AI calls orchestrated by code, not a swarm of autonomous agents.
        Each agent does one narrow job, answers in a fixed format, and code checks the answer before anything is kept.
        The order of steps, what runs in parallel, scoring and ranking are decided by code.
      </p>
      <ol className="hiw-flow" aria-label="Pipeline steps in order">
        {FLOW.map((step) => (
          <li key={step.name}>
            <p className="hiw-step-head"><strong>{step.name}</strong> <KindTag kind={step.kind} /></p>
            <p>{step.what}</p>
            {step.parallel && (
              <ul className="hiw-parallel" aria-label="Reviewers, in parallel">
                {step.parallel.map((r) => <li key={r.name}><strong>{r.name}</strong>: {r.what}</li>)}
              </ul>
            )}
          </li>
        ))}
      </ol>
      <ul>{FLOW_RULES.map((rule) => <li key={rule}>{rule}</li>)}</ul>
    </section>
  );
}

function Anatomy() {
  return (
    <section aria-labelledby="hiw-anatomy">
      <h2 id="hiw-anatomy">2. Anatomy of one agent</h2>
      <p>Every AI step follows the same four steps. Example: the Statistician checks whether performance metrics have confidence intervals (item s1).</p>
      <ol className="hiw-anatomy">
        <li>
          <h3>Ask</h3>
          <p>Code sends the model the shared rules (the paper is data, not instructions; no outside knowledge; quote exactly), the Statistician's perspective, the paper text and each checklist item's key and text, with a fixed answer format.</p>
          <p className="hiw-example">Example: “s1: Performance metrics are reported with confidence intervals.”</p>
        </li>
        <li>
          <h3>Answer</h3>
          <p>The model fills the format: one answer per item, with an exact quote and the section it comes from.</p>
          <p className="hiw-example">Example: s1 · answer “no” · quote “achieved an AUC of 0.91 on the test set” · section Results.</p>
        </li>
        <li>
          <h3>Check</h3>
          <p>Code checks the format, that every item is answered, and that every quote occurs exactly in the paper. A bad answer is retried up to 3 times; then the run stops and keeps its checkpoint (fail closed).</p>
          <p className="hiw-example">Example: the quote is found in the Results section, so the answer is kept.</p>
        </li>
        <li>
          <h3>Save</h3>
          <p>The exact input and output are stored with the model and prompt version: the audit trail, reused on resume and readable in the paper drawer (“Raw calls”). Code then turns answers into the score and red flags.</p>
          <p className="hiw-example">Example: s1 answered “no” raises the red flag “No confidence intervals for performance”, shown with the quote as evidence.</p>
        </li>
      </ol>
    </section>
  );
}

function Skill() {
  return (
    <section aria-labelledby="hiw-skill">
      <h2 id="hiw-skill">3. Example skill: the Statistician</h2>
      <p>
        A reviewer profile is a small, versioned, editable skill (Settings → Reviewers). The model sees only the perspective and each item's
        key and text; weights and red-flag rules stay in code so the model cannot aim at the score. These are the default items (version {STATISTICIAN.version}).
      </p>
      <p><strong>Perspective:</strong> {STATISTICIAN.perspective}</p>
      <table className="hiw-items">
        <caption>Statistician checklist ({STATISTICIAN.items.length} items)</caption>
        <thead>
          <tr><th scope="col">Key</th><th scope="col">Item</th><th scope="col">Source</th><th scope="col">Weight</th><th scope="col">Red flag when “no”</th></tr>
        </thead>
        <tbody>
          {STATISTICIAN.items.map((item) => (
            <tr key={item.key}>
              <th scope="row">{item.key}</th>
              <td>{item.text}</td>
              <td>{item.source}</td>
              <td>{item.weight}</td>
              <td>{item.redFlag ?? "—"}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <p>Score is the weighted share of items met among those answered; “not reported” items lower the coverage (“provisional” below half), not the score.</p>
      <p>The other agents are built the same way: Plan (queries from the topic), Screen (one answer per criterion, a quote for every “no”), Extract (claims with exact quotes), Editor (reads all reports, names disagreements, gives the final verdict with a reason).</p>
    </section>
  );
}

function Architecture() {
  return (
    <section aria-labelledby="hiw-arch">
      <h2 id="hiw-arch">4. Architecture</h2>
      <p>Rules the design keeps:</p>
      <ul>{DESIGN_RULES.map((rule) => <li key={rule}>{rule}</li>)}</ul>
      <p>
        The pipeline runs in a worker, the only process that holds model keys. Results go to PostgreSQL; the web API reads them and this app shows them.
        The eval harness measures the pipeline against published systematic reviews, offline from the call cache.
      </p>
      <table className="hiw-items">
        <caption>Main modules</caption>
        <thead><tr><th scope="col">Module</th><th scope="col">Role</th><th scope="col">Path</th></tr></thead>
        <tbody>
          {MODULES.map((m) => (
            <tr key={m.name}><th scope="row">{m.name}</th><td>{m.role}</td><td><code>{m.path}</code></td></tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}

export function HowItWorksPage() {
  return (
    <article className="how-it-works">
      <h1>How it works</h1>
      <nav aria-label="On this page" className="hiw-toc">
        <a href="#hiw-flow">Execution flow</a> <a href="#hiw-anatomy">Anatomy of one agent</a> <a href="#hiw-skill">Example skill</a> <a href="#hiw-arch">Architecture</a>
      </nav>
      <Flow />
      <Anatomy />
      <Skill />
      <Architecture />
    </article>
  );
}
