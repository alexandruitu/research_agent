import { useState } from "react";

import { ApiError } from "../../api/client";
import { useJob, useReaderAsk, useSaveNote } from "../../api/hooks";
import type { DrawerOut, ReaderResult, ReaderTool } from "../../api/types";
import { useSaveFlow } from "../library/saveFlow";
import { GENERAL_LABEL, TOOL_LABEL } from "./ReaderNotes";
import { MAX_SELECTION } from "./segments";

const errorText = (error: unknown) => (error instanceof ApiError ? error.message : "Could not reach the server.");

function Answer({ result }: { result: ReaderResult }) {
  return (
    <div className="reader-answer">
      {result.general ? <p className="chip chip--warn reader-general">{GENERAL_LABEL}</p> : <p className="sub">From the paper: every statement below quotes it, and code checked each quote against the text.</p>}
      <p>{result.answer}</p>
      {result.not_in_paper && <p><strong>The paper does not say.</strong></p>}
      {result.statements.length > 0 && (
        <ul className="reader-statements">
          {result.statements.map((s, i) => <li key={i}>{s.text} <q className="reader-quote">{s.quote}</q></li>)}
        </ul>
      )}
      <p className="sub">{result.model}{result.mode === "demo" ? " · demo answer (test data)" : ""}</p>
    </div>
  );
}

/** Explain / Ask / Background on the selection (or the whole paper), the answer, and Save as note. */
export function ReaderTools({ runId, paperId, selection, drawer }: { runId: string; paperId: string; selection: string; drawer: DrawerOut | undefined }) {
  const ask = useReaderAsk(runId, paperId);
  const saveNote = useSaveNote(runId, paperId);
  const libraryFlow = useSaveFlow();
  const [question, setQuestion] = useState("");
  const [jobId, setJobId] = useState<string | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [saved, setSaved] = useState<string | null>(null);
  const [offerLibrary, setOfferLibrary] = useState(false);
  const job = useJob(jobId);
  const tooLong = selection.length > MAX_SELECTION;
  const running = ask.isPending || ["queued", "running"].includes(job.data?.status ?? "");
  const result = job.data?.status === "done" ? ((job.data.progress as { result?: ReaderResult }).result ?? null) : null;

  const run = async (tool: ReaderTool) => {
    setProblem(null);
    setSaved(null);
    setOfferLibrary(false);
    try {
      const started = await ask.mutateAsync({ tool, selection, question: tool === "explain" ? "" : question });
      setJobId(started.id);
    } catch (error) {
      setProblem(errorText(error));
    }
  };
  const save = async () => {
    if (!jobId) return;
    try {
      await saveNote.mutateAsync(jobId);
      setSaved(jobId);
      setOfferLibrary(!drawer?.library);
    } catch (error) {
      setProblem(errorText(error));
    }
  };
  const target = selection ? "the selection" : "the whole paper";

  return (
    <section aria-labelledby="reader-tools-heading" className="reader-tools">
      <h2 id="reader-tools-heading">Ask about {target}</h2>
      {tooLong && <p role="alert" className="form-error">The selection is {selection.length.toLocaleString()} characters; select at most {MAX_SELECTION.toLocaleString()}.</p>}
      <div className="actions">
        <button type="button" className="primary" disabled={running || tooLong} onClick={() => void run("explain")}>Explain (from the paper)</button>
        <button type="button" disabled={running || tooLong || !(selection || question.trim())} onClick={() => void run("background")}>Background explanation</button>
      </div>
      <form className="reader-ask" onSubmit={(e) => { e.preventDefault(); void run("ask"); }}>
        <label className="block">Question about the paper
          <textarea rows={2} maxLength={1000} value={question} onChange={(e) => setQuestion(e.target.value)} placeholder="e.g. Was the test set external?" />
        </label>
        <button type="submit" disabled={running || tooLong || !question.trim()}>Ask</button>
      </form>
      <p className="sub">Explain and Ask answer only from this paper, each statement with an exact quote checked by code; “the paper does not say” is a valid answer. Background explanation is general knowledge, not from this paper.</p>
      <div aria-live="polite">
        {running && <p role="status">Working… this takes a few seconds.</p>}
        {problem && <p role="alert" className="form-error">{problem}</p>}
        {job.data?.status === "failed" && <p role="alert" className="form-error">No answer: {job.data.error ?? "the call failed"}. Nothing was kept.</p>}
        {result && (
          <>
            <h3>{TOOL_LABEL[result.tool] ?? result.tool}</h3>
            <Answer result={result} />
            {saved === jobId ? <p role="status">Note saved.</p> : <button type="button" onClick={() => void save()} disabled={saveNote.isPending}>Save as note</button>}
            {saved === jobId && offerLibrary && (
              <p className="reader-offer">
                This paper is not in the library.{" "}
                <button type="button" disabled={libraryFlow.pending} onClick={() => { setOfferLibrary(false); void libraryFlow.save(runId, [paperId], { status: "to_read", note: "" }); }}>Save it to the library too</button>
              </p>
            )}
          </>
        )}
      </div>
      <h3>More tools</h3>
      <ul className="reader-later">
        <li><button type="button" disabled aria-describedby="later-related">Find related</button> <span id="later-related" className="sub">coming next</span></li>
        <li><button type="button" disabled aria-describedby="later-earlier">Earlier work</button> <span id="later-earlier" className="sub">coming next</span></li>
        <li><button type="button" disabled aria-describedby="later-inhouse">In-house</button> <span id="later-inhouse" className="sub">needs an internal collection — coming</span></li>
      </ul>
    </section>
  );
}
