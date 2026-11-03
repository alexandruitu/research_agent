import { useEffect, useState, type FormEvent } from "react";

import { ApiError } from "../../api/client";
import { useJob } from "../../api/hooks";
import { useCheckKey, useDeleteKey, useMyKeys, useSaveKey } from "../../api/meHooks";
import type { KeyOut } from "../../api/types";

const GROUPS: { kind: string; title: string; intro: string }[] = [
  { kind: "model", title: "AI models", intro: "Searches and the Reader call these with your key. Add at least one to start real (not demo) searches." },
  { kind: "jev", title: "Screening tier (Jev)", intro: "Optional: Jev, a small fast model, makes a first pass that keeps or drops the clear cases before the larger AI model; it saves cost." },
  { kind: "source", title: "Search sources", intro: "Optional for most sources; IEEE, Springer, CORE and Scopus need a key to be searched." },
];

const day = (iso: string | null | undefined) => (iso ? new Date(iso).toLocaleDateString() : "");

export function checkWords(key: KeyOut): string {
  if (!key.saved) return key.server_key ? "No key of yours saved · the server's .env key is used (development only)" : "No key saved";
  const saved = `Saved …${key.last4} on ${day(key.created_at)}`;
  if (key.check_ok === true) return `${saved} · ✓ accepted`;
  if (key.check_ok === false) return `${saved} · ✗ rejected (${key.check_detail})`;
  if (key.checked_at) return `${saved} · not checked (${key.check_detail || "no check for this provider"})`;
  return `${saved} · not tested yet`;
}

// Green chip only for a key that is actually there; the words carry the state, not the colour.
function KeyChip({ entry }: { entry: KeyOut }) {
  if (entry.saved && entry.check_ok === false) return <span className="chip chip--warn">✗ Saved, rejected</span>;
  if (entry.saved) return <span className="chip chip--ok">✓ Saved</span>;
  if (entry.server_key) return <span className="chip chip--ok" title="Development only: the server's .env key is used until you save your own">✓ Server key (dev)</span>;
  return null;
}

function KeyRow({ entry }: { entry: KeyOut }) {
  const [value, setValue] = useState("");
  const [editing, setEditing] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const [jobId, setJobId] = useState<string | null>(null);
  const save = useSaveKey();
  const remove = useDeleteKey();
  const check = useCheckKey();
  const job = useJob(jobId);
  const keys = useMyKeys();
  const done = job.data && !["queued", "running"].includes(job.data.status);
  useEffect(() => {
    if (done) void keys.refetch();
  }, [done]); // eslint-disable-line react-hooks/exhaustive-deps

  const fail = (error: unknown) => setProblem(error instanceof ApiError ? error.message : "Could not reach the server. Check your connection and try again.");
  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setProblem(null);
    try {
      await save.mutateAsync({ provider: entry.provider, key: value.trim() });
      setValue(""); // the key is never shown again
      setEditing(false);
    } catch (error) {
      fail(error);
    }
  };
  const test = async () => {
    setProblem(null);
    try {
      setJobId((await check.mutateAsync(entry.provider)).id);
    } catch (error) {
      fail(error);
    }
  };
  const del = async () => {
    setProblem(null);
    try {
      await remove.mutateAsync(entry.provider);
    } catch (error) {
      fail(error);
    }
  };
  const field = `key-${entry.provider}`;
  return (
    <tr>
      <th scope="row">{entry.label}</th>
      <td>
        <KeyChip entry={entry} /> <span>{checkWords(entry)}</span>
        {job.data && ["queued", "running"].includes(job.data.status) && <span role="status"> · testing…</span>}
        {problem && <p role="alert" className="form-error">{problem}</p>}
        {(editing || !entry.saved) && (
          <form onSubmit={submit} className="inline-form">
            <label htmlFor={field} className="sr-only">{entry.label} key</label>
            <input id={field} type="password" autoComplete="off" spellCheck={false} value={value} onChange={(e) => setValue(e.target.value)} placeholder="Paste the key" />
            <button type="submit" disabled={!value.trim() || save.isPending}>{entry.saved ? "Replace" : "Save"} {entry.label} key</button>
            {entry.saved && <button type="button" onClick={() => setEditing(false)}>Cancel</button>}
          </form>
        )}
      </td>
      <td>
        {entry.saved && (
          <span className="row-actions">
            {!editing && <button type="button" aria-label={`Replace ${entry.label} key`} onClick={() => setEditing(true)}>Replace</button>}
            {entry.checkable && <button type="button" aria-label={`Test ${entry.label} key`} onClick={test} disabled={check.isPending}>Test</button>}
            <button type="button" aria-label={`Delete ${entry.label} key`} onClick={del} disabled={remove.isPending}>Delete</button>
          </span>
        )}
      </td>
    </tr>
  );
}

export function MyKeysTab() {
  const keys = useMyKeys();
  if (keys.isLoading) return <p role="status">Loading…</p>;
  if (keys.isError) return <p role="alert">Could not load your keys. Reload the page to try again.</p>;
  return (
    <section>
      <h2>My keys</h2>
      <p className="intro">The provider keys your searches use. Add a key for at least one AI model below to start real searches. A saved key is encrypted and never shown again: you see only its last 4 characters.</p>
      {GROUPS.map((group) => {
        const rows = (keys.data ?? []).filter((k) => k.kind === group.kind);
        return (
          <div key={group.kind}>
            <h3 id={`keys-${group.kind}`}>{group.title}</h3>
            <p className="sub">{group.intro}</p>
            <table className="runs" aria-labelledby={`keys-${group.kind}`}>
              <thead><tr><th scope="col">Provider</th><th scope="col">Key</th><th scope="col"><span className="sr-only">Actions</span></th></tr></thead>
              <tbody>{rows.map((entry) => <KeyRow key={entry.provider} entry={entry} />)}</tbody>
            </table>
          </div>
        );
      })}
    </section>
  );
}
