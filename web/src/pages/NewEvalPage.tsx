import { useCallback, useState } from "react";
import { Link } from "react-router-dom";

import { ApiError } from "../api/client";
import { useEstimate, useEvals, useGoldSets, useJob, useReviewSettings, useRuns, useStartEval } from "../api/hooks";
import type { EstimateOut, EvalJobProgress, EvalKind, EvalRequest } from "../api/types";
import { EstimateView } from "../features/evals/EstimateView";
import { stepText } from "../features/evals/EvalJobs";
import { GoldSetForm } from "../features/evals/GoldSetForm";
import { reportTitle } from "../features/evals/headline";
import { KIND_ICON, KIND_LABEL, KIND_WHAT, dateText } from "../features/evals/words";
import { newestFirst, runOption } from "../features/runs/runWords";

const KINDS: EvalKind[] = ["panel", "ablation", "screening", "human"];
const COST: Record<EvalKind, string> = {
  screening: "Jev and LLM screening calls (cached calls are reused).",
  panel: "Full text, every reviewer and the editor per sampled paper.",
  ablation: "Free: re-scored offline from the panel's cached calls, unless you re-run the editor.",
  human: "Free: people's ratings.",
};

type Inputs = { gold: string; run: string; source: "gold" | "run"; sample: string; seed: string; panelEval: string; rerunEditor: boolean; demo: boolean };
const START: Inputs = { gold: "", run: "", source: "gold", sample: "20", seed: "0", panelEval: "", rerunEditor: false, demo: false };

function requestFor(kind: EvalKind, i: Inputs): EvalRequest | string {
  const mode = i.demo ? "demo" : "live";
  const sample = Number(i.sample);
  const seed = Number(i.seed);
  if (kind === "screening") return i.gold ? { kind, mode, gold_set_id: i.gold, sample: 20, seed: 0, rerun_editor: false } : "Choose a gold set.";
  if (kind === "panel") {
    if (i.source === "gold" && !i.gold) return "Choose a gold set.";
    if (i.source === "run" && !i.run) return "Choose a run.";
    if (!Number.isInteger(sample) || sample < 1 || sample > 500) return "Sample between 1 and 500 papers.";
    if (!Number.isInteger(seed) || seed < 0) return "The seed is a whole number, 0 or more.";
    return { kind, mode, ...(i.source === "gold" ? { gold_set_id: i.gold } : { run_id: i.run }), sample, seed, rerun_editor: false };
  }
  if (kind === "ablation") return i.panelEval ? { kind, mode, panel_eval_id: i.panelEval, rerun_editor: i.rerunEditor, sample: 20, seed: 0 } : "Choose a panel report.";
  return "Human reference reports are not started here.";
}

function Follow({ jobId }: { jobId: string }) {
  const job = useJob(jobId);
  const progress = (job.data?.progress ?? {}) as EvalJobProgress;
  const evalId = progress.result?.eval_id;
  const step = stepText(progress);
  return (
    <section aria-label="Progress" className="job wizard-follow">
      <p role="status">
        {!job.data ? "Waiting for the worker…" : job.data.status === "done" ? "✓ Done. The report is ready." : job.data.status === "failed" ? "! Failed." : `↻ ${job.data.status}${step ? `, ${step}` : ""}${progress.total ? ` · ${progress.done ?? 0} of ${progress.total} papers` : ""}`}
      </p>
      {progress.total ? <progress max={progress.total} value={progress.done ?? 0} aria-label="Papers done" /> : null}
      {job.data?.error && <p className="form-error">{job.data.error}</p>}
      {evalId && <Link className="button-link" to={`/evals/${evalId}`}>Open report</Link>}
      <p className="hint">You can leave this page: the evaluation keeps running and shows under “In progress” on <Link to="/evals">Evals</Link>.</p>
    </section>
  );
}

export function NewEvalPage() {
  const [kind, setKind] = useState<EvalKind | null>(null);
  const [inputs, setInputs] = useState<Inputs>(START);
  const [estimate, setEstimate] = useState<{ key: string; out: EstimateOut } | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [jobId, setJobId] = useState<string | null>(null);
  const gold = useGoldSets();
  const runs = useRuns();
  const panels = useEvals("panel");
  const settings = useReviewSettings();
  const estimateCall = useEstimate();
  const start = useStartEval();
  const update = (patch: Partial<Inputs>) => setInputs((i) => ({ ...i, ...patch }));
  const onBuilt = useCallback((id: string) => setInputs((i) => ({ ...i, gold: id, source: "gold" })), []);

  const request = kind ? requestFor(kind, inputs) : "Choose what to measure.";
  const requestKey = typeof request === "string" ? null : JSON.stringify(request);
  const fresh = estimate && estimate.key === requestKey ? estimate.out : null;
  const canStart = typeof request !== "string" && (inputs.demo || !!fresh) && !jobId;

  const run = async (what: "estimate" | "start") => {
    if (typeof request === "string") return setProblem(request);
    setProblem(null);
    try {
      if (what === "estimate") setEstimate({ key: requestKey!, out: await estimateCall.mutateAsync(request) });
      else setJobId((await start.mutateAsync(request)).id);
    } catch (error) {
      setProblem(error instanceof ApiError ? error.message : "Could not reach the server.");
    }
  };

  const usableGold = (gold.data ?? []).filter((g) => g.usable !== false);
  const doneRuns = (runs.data ?? []).filter((r) => r.status === "done" && r.kind === "research");

  return (
    <section className="wizard">
      <nav aria-label="Breadcrumb" className="crumbs"><Link to="/evals">← All evaluations</Link></nav>
      <h1>New evaluation</h1>
      <ol className="wizard-steps">
        <li className="wizard-step">
          <h2><span className="step-num" aria-hidden="true">1</span> What do you want to measure?</h2>
          <fieldset className="kind-choices">
            <legend className="sr-only">Kind of evaluation</legend>
            {KINDS.map((k) => (
              <label key={k} className={`kind-choice${kind === k ? " is-checked" : ""}`}>
                <input type="radio" name="kind" value={k} checked={kind === k} onChange={() => { setKind(k); setProblem(null); }} />
                <span className="kind-choice-icon" aria-hidden="true">{KIND_ICON[k]}</span>
                <span className="kind-choice-name">{KIND_LABEL[k]}</span>
                <span className="kind-choice-what">{KIND_WHAT[k]}</span>
                <span className="kind-choice-cost">Cost: {COST[k]}</span>
              </label>
            ))}
          </fieldset>
        </li>
        {kind && (
          <li className="wizard-step">
            <h2><span className="step-num" aria-hidden="true">2</span> Inputs</h2>
            {kind === "human" ? (
              <div className="banner">
                <p>Human reference reports are recomputed each time someone submits ratings, so there is nothing to start here.</p>
                <p>To begin: open a <Link to="/evals">review panel report</Link>, create a rating sample (admins), then rate papers blind. Each submission produces a new human reference report.</p>
              </div>
            ) : (
              <div className="wizard-inputs">
                {kind === "panel" && (
                  <fieldset className="segmented-radios">
                    <legend>Papers from</legend>
                    <label><input type="radio" name="source" checked={inputs.source === "gold"} onChange={() => update({ source: "gold" })} /> A gold set (SR-labelled: gives the inclusion AUC)</label>
                    <label><input type="radio" name="source" checked={inputs.source === "run"} onChange={() => update({ source: "run" })} /> A finished run (no SR labels)</label>
                  </fieldset>
                )}
                {(kind === "screening" || (kind === "panel" && inputs.source === "gold")) && (
                  <>
                    <label>Gold set
                      <select value={inputs.gold} onChange={(e) => update({ gold: e.target.value })}>
                        <option value="">Choose…</option>
                        {usableGold.map((g) => <option key={g.id} value={g.id}>{g.name} · {g.citation}{g.positives != null ? ` · ${g.positives} included of ${g.candidates ?? "?"}` : ""}</option>)}
                      </select>
                    </label>
                    <GoldSetForm onBuilt={onBuilt} />
                  </>
                )}
                {kind === "panel" && inputs.source === "run" && (
                  <label>Run
                    <select className="run-picker" value={inputs.run} onChange={(e) => update({ run: e.target.value })}>
                      <option value="">Choose…</option>
                      {newestFirst(doneRuns).map((r) => {
                        const option = runOption(r, [`${r.paper_count} papers`]);
                        return <option key={r.id} value={r.id} title={option.title}>{option.text}</option>;
                      })}
                    </select>
                  </label>
                )}
                {kind === "panel" && (
                  <>
                    <div className="two-up">
                      <label>Papers to sample<input inputMode="numeric" value={inputs.sample} onChange={(e) => update({ sample: e.target.value })} aria-describedby="sample-hint" /></label>
                      <label>Seed<input inputMode="numeric" value={inputs.seed} onChange={(e) => update({ seed: e.target.value })} /></label>
                    </div>
                    <p id="sample-hint" className="hint">SR-included papers first, then a matched sample of excluded ones. The same seed gives the same papers.</p>
                    <p className="hint">Reviewers, items and models: the current review settings, version {settings.data?.current.version ?? "…"} (<Link to="/settings/reviewers">Settings → Reviewers</Link>, <Link to="/settings/models">AI models</Link>). The report freezes them.</p>
                  </>
                )}
                {kind === "ablation" && (
                  <>
                    <label>Panel report
                      <select value={inputs.panelEval} onChange={(e) => update({ panelEval: e.target.value })}>
                        <option value="">Choose…</option>
                        {(panels.data ?? []).map((p) => <option key={p.id} value={p.id}>{reportTitle(p)} · {p.headline.papers ?? "?"} papers · {dateText(p.created_at)}</option>)}
                      </select>
                    </label>
                    <label className="check"><input type="checkbox" checked={inputs.rerunEditor} onChange={(e) => update({ rerunEditor: e.target.checked })} /> Re-run the editor for every reviewer subset (costs editor calls; otherwise the verdict is the reviewers' majority)</label>
                  </>
                )}
                <label className="check"><input type="checkbox" checked={inputs.demo} onChange={(e) => update({ demo: e.target.checked })} /> Demo mode (no model calls, made-up answers; for trying the flow)</label>
              </div>
            )}
          </li>
        )}
        {kind && kind !== "human" && (
          <li className="wizard-step">
            <h2><span className="step-num" aria-hidden="true">3</span> Cost, then start</h2>
            <div className="wizard-actions">
              <button type="button" onClick={() => run("estimate")} disabled={estimateCall.isPending}>Estimate cost</button>
              <button type="button" className="primary" onClick={() => run("start")} disabled={!canStart || start.isPending}>Start evaluation</button>
              {!inputs.demo && !fresh && typeof request !== "string" && <span className="hint">Live evaluations start after an estimate of the current inputs.</span>}
            </div>
            {problem && <p role="alert" className="form-error">{problem}</p>}
            {fresh && <EstimateView estimate={fresh} />}
            {jobId && <Follow jobId={jobId} />}
          </li>
        )}
      </ol>
    </section>
  );
}
