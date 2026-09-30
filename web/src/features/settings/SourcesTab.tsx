import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useState, type FormEvent } from "react";

import { ApiError } from "../../api/client";
import { keys, useCheckSource, useJob, usePatchSettings, usePatchSource, useSettings, useSources } from "../../api/hooks";
import { hasRole, type SourceCheckResult, type SourceOut } from "../../api/types";
import { useAuth } from "../../auth/AuthProvider";
import { authWords, enableBlocked, groupSources, keyStatusWords, keyTone, rateWords, searchable } from "./sources";

const errorText = (error: unknown) => (error instanceof ApiError ? error.message : "Could not reach the server.");
const seconds = (ms: number | null) => (ms === null ? "" : ` · ${(ms / 1000).toFixed(1)} s`);

function lastCheck(source: SourceOut): string {
  if (!source.last_check_at) return "never checked";
  const when = new Date(source.last_check_at).toLocaleString();
  return source.last_check_ok
    ? `✓ OK${seconds(source.last_check_ms)} · ${when}`
    : `✗ failed: ${source.last_check_error ?? "no details"}${seconds(source.last_check_ms)} · ${when}`;
}

function CheckStatus({ source, jobId }: { source: SourceOut; jobId: string | null }) {
  const job = useJob(jobId);
  const client = useQueryClient();
  const finished = job.data?.status === "done" || job.data?.status === "failed";
  useEffect(() => {
    if (finished) void client.invalidateQueries({ queryKey: keys.sources });
  }, [finished, client]);
  if (jobId && job.isError) return <span>✗ could not read the check</span>;
  if (jobId && !finished) return <span role="status">checking…</span>;
  if (job.data?.status === "failed") return <span>✗ the check could not run: {job.data.error ?? "no details"}</span>;
  const result = (job.data?.progress as { result?: SourceCheckResult } | undefined)?.result;
  if (result) return <span>{result.ok ? `✓ OK${seconds(result.ms)} · ${result.count} result` : `✗ failed: ${result.error ?? "no details"}${seconds(result.ms)}`}</span>;
  return <span>{lastCheck(source)}</span>;
}

type RowProps = { source: SourceOut; admin: boolean; jobId: string | null; onPatch: (body: { enabled?: boolean; max_results?: number }) => void; onCheck: () => void };

function SourceRow({ source, admin, jobId, onPatch, onCheck }: RowProps) {
  const label = source.label;
  const [max, setMax] = useState(String(source.max_results));
  const [problem, setProblem] = useState<string | null>(null);
  const saveMax = (event: FormEvent) => {
    event.preventDefault();
    const value = Number(max);
    if (!Number.isInteger(value) || value < 1 || value > 200) return setProblem("Max results must be a whole number from 1 to 200.");
    setProblem(null);
    onPatch({ max_results: value });
  };
  const state = source.enabled ? "enabled" : "disabled";
  const blocked = enableBlocked(source);
  const keyStatus = keyStatusWords(source);
  const canSearch = searchable(source);
  const why = `why-${source.name}`;
  return (
    <tr className={source.enabled ? "source-row source-row--on" : "source-row"}>
      <th scope="row">
        <span className="source-name">{label}</span>
        <span className="sub">{source.covers}</span>
        {!canSearch && <span className="sub">Full text only: its place in the order is set in Settings → Full text.</span>}
      </th>
      <td>
        <span className="source-auth">{authWords(source)}</span>
        {keyStatus && <span className={`key-status key-status--${keyTone(source)}`}>{keyStatus}</span>}
      </td>
      <td>
        {!canSearch ? <span className="na">not a search source</span> : admin ? (
          <>
            <label className="switch">
              <input type="checkbox" role="switch" checked={source.enabled} disabled={blocked !== null} aria-describedby={blocked ? why : undefined} onChange={(e) => onPatch({ enabled: e.target.checked })} />
              <span className="switch-state">{state}</span>
              <span className="sr-only"> ({label})</span>
            </label>
            {blocked && <span id={why} className="hint">{blocked}</span>}
          </>
        ) : state}
      </td>
      <td>
        {!canSearch ? <span className="na">–</span> : admin ? (
          <form className="inline" onSubmit={saveMax} noValidate>
            <label><span className="sr-only">Max results per run for {label}</span>
              <input type="number" min={1} max={200} value={max} onChange={(e) => setMax(e.target.value)} />
            </label>
            <button type="submit">Save{" "}<span className="sr-only">max results for {label}</span></button>
            {problem && <span role="alert" className="form-error">{problem}</span>}
          </form>
        ) : source.max_results}
      </td>
      <td>{rateWords(source)}</td>
      <td>{canSearch ? <CheckStatus source={source} jobId={jobId} /> : <span className="na">–</span>}</td>
      <td>{admin && canSearch && <button type="button" onClick={onCheck}>Test{" "}<span className="sr-only">{label}</span></button>}</td>
    </tr>
  );
}

function ContactForm({ admin, value }: { admin: boolean; value: string | null }) {
  const patch = usePatchSettings();
  const [email, setEmail] = useState(value ?? "");
  const [message, setMessage] = useState<string | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  if (!admin) return <p>Contact address for public APIs: {value ?? "not set"}</p>;
  const submit = async (event: FormEvent) => {
    event.preventDefault();
    const text = email.trim();
    setMessage(null);
    if (text && !/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(text)) return setProblem("Enter an email address, or leave it empty.");
    setProblem(null);
    try {
      await patch.mutateAsync({ contact_email: text || null });
      setMessage("Saved.");
    } catch (error) {
      setProblem(errorText(error));
    }
  };
  return (
    <form className="inline" onSubmit={submit} noValidate aria-label="Contact address">
      <label>Contact address for public APIs <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} /></label>
      <button type="submit" disabled={patch.isPending}>Save contact address</button>
      {message && <span role="status">{message}</span>}
      {problem && <span role="alert" className="form-error">{problem}</span>}
    </form>
  );
}

export function SourcesTab() {
  const { user } = useAuth();
  const admin = hasRole(user, "admin");
  const sources = useSources();
  const settings = useSettings();
  const patch = usePatchSource();
  const check = useCheckSource();
  const [jobs, setJobs] = useState<Record<string, string>>({});
  const [problem, setProblem] = useState<string | null>(null);
  const act = async (work: () => Promise<unknown>) => {
    setProblem(null);
    try {
      await work();
    } catch (error) {
      setProblem(errorText(error));
    }
  };

  if (sources.isLoading) return <p role="status">Loading…</p>;
  if (sources.isError) return <p role="alert" className="form-error">{errorText(sources.error)}</p>;
  return (
    <section aria-labelledby="sources-heading">
      <h2 id="sources-heading">Sources</h2>
      <p className="intro">Where a field can search. A field picks among the enabled sources. Keys live only in the worker’s environment and are never shown here; this page says whether the worker has them.</p>
      {problem && <p role="alert" className="form-error">{problem}</p>}
      {groupSources(sources.data ?? []).map((group) => (
        <section key={group.key} className="source-group" aria-labelledby={`group-${group.key}`}>
          <h3 id={`group-${group.key}`}>{group.title}</h3>
          <p className="intro">{group.intro}</p>
          <div className="table-scroll">
            <table className="runs sources-table" aria-labelledby={`group-${group.key}`}>
              <thead>
                <tr><th scope="col">Source</th><th scope="col">Access</th><th scope="col">Status</th><th scope="col">Max results per run</th><th scope="col">Rate limit</th><th scope="col">Last check</th><th scope="col"><span className="sr-only">Actions</span></th></tr>
              </thead>
              <tbody>
                {group.sources.map((source) => (
                  <SourceRow
                    key={`${source.name}:${source.max_results}`} source={source} admin={admin} jobId={jobs[source.name] ?? null}
                    onPatch={(body) => void act(() => patch.mutateAsync({ name: source.name, ...body }))}
                    onCheck={() => void act(async () => {
                      const job = await check.mutateAsync(source.name);
                      setJobs((current) => ({ ...current, [source.name]: job.id }));
                    })}
                  />
                ))}
              </tbody>
            </table>
          </div>
        </section>
      ))}
      <aside className="banner scholar-note" aria-label="Google Scholar">
        <strong>Google Scholar is not supported, on purpose.</strong> It has no official API; scraping it breaks its terms and could not be audited. The sources above reach what it indexes for medical imaging through official APIs.
      </aside>
      <p className="legend">Test runs one real search for one result with the worker’s keys. After adding or changing a key in the worker environment, restart the worker: it checks every key when it starts. Public APIs receive the contact address below, as they ask.</p>
      {settings.isLoading ? <p role="status">Loading…</p> : settings.isError ? <p role="alert" className="form-error">{errorText(settings.error)}</p> : <ContactForm admin={admin} value={settings.data?.contact_email ?? null} />}
    </section>
  );
}
