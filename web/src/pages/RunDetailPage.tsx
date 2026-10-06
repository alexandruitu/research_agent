import { useLayoutEffect, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import { isActive, useRun, useRunCalls, useRunLog } from "../api/hooks";
import { hasRole, type RunDetailOut, type RunOut } from "../api/types";
import { useAuth } from "../auth/AuthProvider";
import { MenuButton } from "../components/ui/MenuButton";
import { Skeleton } from "../components/ui/Skeleton";
import { useRunActions } from "../features/runs/RunActions";
import { RunStatus } from "../features/runs/RunList";
import { SearchWarningPanel } from "../features/runs/SearchWarnings";
import { coverageLine, formatSeconds, formatUsd, runLabel } from "../features/runs/runWords";
import { Term } from "../components/ui/Term";

/** One run: what it was started with, how long each stage took, what it found and cost, and its log. */
export function RunDetailPage() {
  const { runId = "" } = useParams();
  const { user } = useAuth();
  const navigate = useNavigate();
  const run = useRun(runId);
  const actions = useRunActions({ onDeleted: (ids) => ids.includes(runId) && navigate("/runs") });
  const member = hasRole(user, "member");

  if (run.isLoading) return <section><h1>Run</h1><Skeleton label="the run" rows={6} /></section>;
  if (run.isError || !run.data) return <section><h1>Run</h1><p role="alert">Could not load this run. It may have been deleted. <Link to="/runs">Back to runs</Link></p></section>;
  const data = run.data;
  const asRow: RunOut = data;
  const label = runLabel(data);
  const research = data.kind === "research";
  const menu = actions.items(asRow, { open: false }).filter((item) => !["Resume", "Cancel run…", "Run again (same configuration)", "Run again with current settings"].includes(item.label));
  const find = (name: string) => actions.items(asRow).find((item) => item.label === name);
  const resume = find("Resume");
  const cancel = find("Cancel run…");
  const same = find("Run again (same configuration)");
  const current = find("Run again with current settings");

  return (
    <article className="run-detail">
      <p className="crumbs"><Link to="/runs">Runs</Link> <span aria-hidden="true">/</span></p>
      <header className="run-detail__head">
        <div>
          <h1>{label}{data.pinned && <span className="runs__mark"><span aria-hidden="true">📌</span><span className="sr-only"> pinned</span></span>}</h1>
          <p className="run-detail__meta">
            <RunStatus status={data.status} /> · {data.kind} · {data.field_name}{data.field_version ? ` v${data.field_version}` : ""} · started by {data.created_by_name ?? "import"} · <time dateTime={data.created_at}>{new Date(data.created_at).toLocaleString()}</time>
            {isActive(data.status) && <span className="sr-only"> (updates every few seconds)</span>}
          </p>
          {coverageLine(data.coverage) && <p className="run-detail__coverage">{coverageLine(data.coverage)}</p>}
          {data.note && <p className="run-detail__note">{data.note}</p>}
        </div>
        <div className="run-detail__actions">
          {resume && data.resume?.allowed && <button type="button" className="primary" onClick={resume.onSelect}>Resume</button>}
          {cancel && <button type="button" className="danger-quiet" onClick={cancel.onSelect}>Cancel run…</button>}
          {same && <button type="button" onClick={same.onSelect}>Run again (same configuration)</button>}
          {current && <button type="button" onClick={current.onSelect}>Run again with current settings</button>}
          <MenuButton label="More actions" items={menu} />
        </div>
      </header>

      <SearchWarningPanel warnings={data.search_warnings} failed={data.status === "failed"} />
      {data.status === "failed" && <div role="alert" className="banner banner--bad"><p><strong>The run failed.</strong> {data.error ?? "No details were stored."}</p></div>}
      {data.status === "cancelled" && <div className="banner"><p><strong>Cancelled.</strong> The checkpoint is kept{data.can_manage && data.resume?.allowed ? "; Resume continues where it stopped." : "."}</p></div>}
      {data.resume?.code === "prompt_version_changed" && (
        <div className="banner banner--warn" role="note">
          <p><strong>Resume is not possible.</strong> {data.resume.reason}</p>
          {same && <button type="button" onClick={same.onSelect}>Run again (same configuration)</button>}
        </div>
      )}

      <section aria-labelledby="counts-h" className="run-detail__block">
        <h2 id="counts-h">Results</h2>
        <dl className="figures">
          <div><dt>Screened</dt><dd>{data.counts.screened}</dd></div>
          <div><dt>Kept</dt><dd>{data.counts.kept}</dd></div>
          <div><dt>Dropped</dt><dd>{data.counts.dropped}</dd></div>
          <div><dt><Term k="escalated">Sent to the LLM</Term></dt><dd>{data.counts.escalated}</dd></div>
          <div><dt>Wall time</dt><dd>{formatSeconds(data.wall_seconds)}</dd></div>
        </dl>
        <p className="run-detail__links">
          <Link to={data.links?.papers ?? `/?run=${data.id}`}>See the papers</Link>
          {(data.links?.evals ?? []).map((e) => <Link key={e.id} to={`/evals/${e.id}`}>{e.kind} evaluation of {new Date(e.created_at).toLocaleDateString()}</Link>)}
          {(data.links?.library_count ?? 0) > 0 && <Link to="/library">{data.links!.library_count} saved to the library</Link>}
        </p>
      </section>

      <Timeline data={data} />
      <Config data={data} />
      {member && research && <Calls runId={data.id} />}
      {member && research && <Log runId={data.id} active={isActive(data.status)} />}
      {actions.dialog}
    </article>
  );
}

/** A bar of the given width, set through the CSSOM (the CSP forbids style attributes). */
function Bar({ percent }: { percent: number }) {
  const ref = useRef<HTMLSpanElement>(null);
  useLayoutEffect(() => {
    if (ref.current) ref.current.style.width = `${percent}%`;
  }, [percent]);
  return <span ref={ref} />;
}

function Timeline({ data }: { data: RunDetailOut }) {
  const stages = data.timeline?.stages ?? [];
  const longest = Math.max(1, ...stages.map((s) => s.seconds ?? 0));
  return (
    <section aria-labelledby="timeline-h" className="run-detail__block">
      <h2 id="timeline-h">Stages</h2>
      {stages.length === 0 ? <p className="hint">No stage has been recorded yet.</p> : (
        <>
          {!data.timeline?.recorded && <p className="hint">Times per stage were not recorded for this run (runs started before stage timing existed); the wall time comes from the run's start and last update.</p>}
          <ol className="timeline">
            {stages.map((stage) => (
              <li key={stage.name} className={`timeline__stage timeline__stage--${stage.status}`}>
                <span className="timeline__name">{stage.name}</span>
                <span className="timeline__status">{stage.status}</span>
                <span className="timeline__bar" aria-hidden="true"><Bar percent={Math.max(2, ((stage.seconds ?? 0) / longest) * 100)} /></span>
                <span className="timeline__time">
                  {stage.seconds !== null ? formatSeconds(stage.seconds) : "time not recorded"}
                  {stage.started_at && <span className="hint"> · {new Date(stage.started_at).toLocaleTimeString()}{stage.finished_at ? `–${new Date(stage.finished_at).toLocaleTimeString()}` : ""}</span>}
                </span>
              </li>
            ))}
          </ol>
        </>
      )}
    </section>
  );
}

function Config({ data }: { data: RunDetailOut }) {
  const c = data.config;
  if (!c) return null;
  const missing = <span className="hint">not recorded</span>;
  const rows: [React.ReactNode, React.ReactNode][] = [
    [<Term key="f" k="field_version">Field</Term>, <>{c.field_name}{c.field_version ? ` · version ${c.field_version}` : ""}</>],
    ["Topic", c.topic || missing],
    ["Sources", c.sources.length ? c.sources.map((s) => `${s.name} (up to ${s.max_results})`).join(", ") : <span className="hint">Europe PMC (legacy topic run)</span>],
    ["Review settings", c.settings_version ? `version ${c.settings_version}` : <span className="hint">none (legacy A/B review)</span>],
    ["Panel", c.panel.length ? c.panel.map((p) => `${p.name ?? p.key} v${p.version ?? "?"}`).join(", ") : <span className="hint">none</span>],
    [<Term key="m" k="demo_mode">Mode</Term>, c.mode ?? missing],
    ["Papers to screen", c.max_papers ?? missing],
    [<Term key="p" k="prompt_version">Prompt version</Term>, c.prompt_version ?? missing],
  ];
  return (
    <section aria-labelledby="config-h" className="run-detail__block">
      <h2 id="config-h">Frozen configuration</h2>
      <dl className="config-list">
        {rows.map(([term, value], i) => <div key={i}><dt>{term}</dt><dd>{value}</dd></div>)}
        <div><dt>Models</dt><dd>{Object.keys(c.models).length ? (
          <ul className="plain">{Object.entries(c.models).map(([role, model]) => <li key={role}><span className="hint">{role}</span> {model}</li>)}</ul>
        ) : missing}</dd></div>
      </dl>
    </section>
  );
}

function Calls({ runId }: { runId: string }) {
  const calls = useRunCalls(runId, true);
  return (
    <section aria-labelledby="calls-h" className="run-detail__block">
      <h2 id="calls-h">Model calls and cost <span className="chip chip--warn">estimate</span></h2>
      {calls.isLoading ? <Skeleton label="the calls" rows={2} /> : calls.isError || !calls.data ? <p className="hint">The calls could not be read.</p> : !calls.data.recorded ? <p className="hint">This run has no call cache on the server.</p> : (
        <>
          <p>{calls.data.totals.calls} distinct calls · estimated {formatUsd(calls.data.totals.cost_usd)}
            {calls.data.providers.length > 0 && ` (${calls.data.providers.map((p) => `${p.provider}: ${p.calls} calls, ${formatUsd(p.cost_usd)}`).join("; ")})`}</p>
          <p className="hint">From approximate list prices and characters sent (about 4 per token). Cache hits and per-call durations are not recorded by the call cache.{calls.data.totals.unpriced_models.length > 0 && ` No price for: ${calls.data.totals.unpriced_models.join(", ")}.`}</p>
          <table className="runs compact">
            <thead><tr><th scope="col">Stage</th><th scope="col">Role</th><th scope="col">Model</th><th scope="col">Calls</th><th scope="col">Chars in / out</th><th scope="col">Cost</th></tr></thead>
            <tbody>{calls.data.rows.map((r) => (
              <tr key={`${r.role}-${r.model}`}><td>{r.stage}</td><td>{r.role}</td><td>{r.model}</td><td className="num">{r.calls}</td><td className="num">{r.input_chars.toLocaleString()} / {r.output_chars.toLocaleString()}</td><td className="num">{formatUsd(r.cost_usd)}</td></tr>
            ))}</tbody>
          </table>
          <p className="hint">Exact prompts and responses: open a paper in <Link to={`/?run=${runId}`}>Papers</Link> and use its Raw calls tab.</p>
        </>
      )}
    </section>
  );
}

function Log({ runId, active }: { runId: string; active: boolean }) {
  const [open, setOpen] = useState(false);
  const log = useRunLog(runId, 300, open);
  return (
    <section aria-labelledby="log-h" className="run-detail__block">
      <h2 id="log-h">Worker log</h2>
      <details onToggle={(e) => setOpen((e.target as HTMLDetailsElement).open)}>
        <summary>Show the last 300 lines{active ? " (refresh the page for newer lines)" : ""}</summary>
        {log.isLoading ? <Skeleton label="the log" rows={4} /> : log.isError || !log.data ? <p className="hint">The log could not be read.</p> : (
          <>
            {log.data.failed_stage && <p className="form-error">Failed at stage <strong>{log.data.failed_stage}</strong>{log.data.reason ? `: ${log.data.reason}` : ""}</p>}
            {log.data.attempts.length > 0 && (
              <div><h3>Model retries</h3><ul className="plain mono">{log.data.attempts.map((a, i) => <li key={i}>{a}</li>)}</ul></div>
            )}
            {log.data.exists ? (
              <>
                <p className="hint">Secrets are replaced by ***. {log.data.truncated ? "Earlier lines are left out." : ""} <a href={`/api/v1/runs/${runId}/log?download=true`} download>Download the log</a></p>
                <pre className="log" tabIndex={0} aria-label="Worker log lines">{log.data.text}</pre>
              </>
            ) : <p className="hint">No worker.log in the run folder (runs imported from the command line have none).</p>}
          </>
        )}
      </details>
    </section>
  );
}
