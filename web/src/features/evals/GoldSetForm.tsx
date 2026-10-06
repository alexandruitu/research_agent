import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useState, type FormEvent } from "react";

import { ApiError } from "../../api/client";
import { keys, useBuildGoldSet, useJob } from "../../api/hooks";
import type { EvalJobProgress } from "../../api/types";
import { goldProblems, parseIncluded, type GoldDraft } from "./goldForm";
import { Term } from "../../components/ui/Term";

const EMPTY: GoldDraft = { name: "", citation: "", topic: "", query: "", included: "" };

/** POST /gold-sets as a disclosure; reports the new gold set id once the worker has built it. */
export function GoldSetForm({ onBuilt }: { onBuilt: (goldSetId: string) => void }) {
  const [draft, setDraft] = useState(EMPTY);
  const [srRef, setSrRef] = useState("");
  const [max, setMax] = useState("200");
  const [problems, setProblems] = useState<string[]>([]);
  const [jobId, setJobId] = useState<string | null>(null);
  const build = useBuildGoldSet();
  const job = useJob(jobId);
  const client = useQueryClient();
  const status = job.data?.status;
  const goldId = (job.data?.progress as EvalJobProgress | undefined)?.result?.gold_set_id;
  useEffect(() => {
    if (status !== "done") return;
    void client.invalidateQueries({ queryKey: keys.goldSets });
    if (goldId) onBuilt(goldId);
  }, [status, goldId, client, onBuilt]);

  const set = (key: keyof GoldDraft) => (e: { target: { value: string } }) => setDraft((d) => ({ ...d, [key]: e.target.value }));
  const submit = async (event: FormEvent) => {
    event.preventDefault();
    const found = goldProblems(draft);
    setProblems(found);
    if (found.length) return;
    try {
      const started = await build.mutateAsync({
        name: draft.name.trim(), citation: draft.citation.trim(), topic: draft.topic.trim(), query: draft.query.trim(),
        included: parseIncluded(draft.included), sr_reference: srRef.trim() || null, max_candidates: Number(max) || 200,
      });
      setJobId(started.id);
    } catch (error) {
      setProblems([error instanceof ApiError ? error.message : "Could not reach the server."]);
    }
  };
  const count = parseIncluded(draft.included).length;
  return (
    <details className="disclosure gold-builder">
      <summary>Build a <Term k="gold_set" /> from a <Term k="sr">systematic review</Term></summary>
      <fieldset aria-label="New gold set" className="gold-form">
        <p className="hint">Paste the studies the review included. The worker searches Europe PMC with your query for candidates, resolves the included studies, and stores the set. The review's own DOI is kept as its citation only: its included list is not read automatically.</p>
        <div className="two-up">
          <label>Name<input value={draft.name} onChange={set("name")} placeholder="e.g. ffrct-sr-2025" /></label>
          <label>Citation of the review<input value={draft.citation} onChange={set("citation")} placeholder="Author et al. 2025, Journal" /></label>
          <label>Topic<input value={draft.topic} onChange={set("topic")} /></label>
          <label>Search query for candidates<input value={draft.query} onChange={set("query")} /></label>
          <label>Review DOI or PMID (optional)<input value={srRef} onChange={(e) => setSrRef(e.target.value)} /></label>
          <label>Candidates to fetch (max)<input inputMode="numeric" value={max} onChange={(e) => setMax(e.target.value)} /></label>
        </div>
        <label className="block">Included studies, one per line: <code>DOI</code> or <code>DOI | title | year</code>
          <textarea rows={6} value={draft.included} onChange={set("included")} />
        </label>
        <p className="hint" aria-live="polite">{count} {count === 1 ? "study" : "studies"} read.</p>
        {problems.length > 0 && <ul role="alert" className="form-error">{problems.map((p) => <li key={p}>{p}</li>)}</ul>}
        <button type="button" onClick={submit} disabled={build.isPending || status === "queued" || status === "running"}>Build gold set</button>
        {jobId && (
          <p role="status" className="job">
            {!job.data ? "Waiting for the worker…" : status === "done" ? "✓ done: the gold set is selected above." : status === "failed" ? `! failed: ${job.data.error ?? "no details"}` : `↻ ${status}…`}
          </p>
        )}
      </fieldset>
    </details>
  );
}
