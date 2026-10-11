import { useState, type ReactNode } from "react";

import { ApiError } from "../../api/client";
import { useJob, useReaderAsk, useReaderRelated, useSaveNote } from "../../api/hooks";
import type { DrawerOut, ReaderResult, ReaderTool, RelatedMode } from "../../api/types";
import { useSaveFlow } from "../library/saveFlow";
import { GENERAL_LABEL, TOOL_LABEL } from "./ReaderNotes";
import { RelatedCard } from "./ReaderRelated";
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

/** One Explain / Ask / Background answer: follows its job, then offers Save as note (and the library). */
function AnswerCard({ jobId, runId, paperId, drawer }: { jobId: string; runId: string; paperId: string; drawer: DrawerOut | undefined }) {
  const job = useJob(jobId);
  const saveNote = useSaveNote(runId, paperId);
  const libraryFlow = useSaveFlow();
  const [saved, setSaved] = useState(false);
  const [offerLibrary, setOfferLibrary] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const status = job.data?.status;
  const result = status === "done" ? ((job.data!.progress as { result?: ReaderResult }).result ?? null) : null;
  const save = async () => {
    setProblem(null);
    try {
      await saveNote.mutateAsync(jobId);
      setSaved(true);
      setOfferLibrary(!drawer?.library);
    } catch (error) {
      setProblem(errorText(error));
    }
  };
  return (
    <li className="answer-card">
      {(!status || status === "queued" || status === "running") && <p role="status">Working… this takes a few seconds.</p>}
      {status === "failed" && <p role="alert" className="form-error">No answer: {job.data?.error ?? "the call failed"}. Nothing was kept.</p>}
      {result && (
        <>
          <h3>{TOOL_LABEL[result.tool] ?? result.tool}</h3>
          <Answer result={result} />
          {saved ? <p role="status">Note saved.</p> : <button type="button" onClick={() => void save()} disabled={saveNote.isPending}>Save as note</button>}
          {saved && offerLibrary && (
            <p className="reader-offer">
              This paper is not in the library.{" "}
              <button type="button" disabled={libraryFlow.pending} onClick={() => { setOfferLibrary(false); void libraryFlow.save(runId, [paperId], { status: "to_read", note: "" }); }}>Save it to the library too</button>
            </p>
          )}
        </>
      )}
      {problem && <p role="alert" className="form-error">{problem}</p>}
    </li>
  );
}

type TileProps = { id: string; icon: ReactNode; title: string; blurb: string; ready: boolean; readyWord: string; waitWord: string; disabled: boolean; onRun: () => void };

/** A large tool tile: the button is the title (its accessible name), the line under it describes it. */
function Tile({ id, icon, title, blurb, ready, readyWord, waitWord, disabled, onRun }: TileProps) {
  return (
    <li className={`tool-tile ${ready ? "is-ready" : ""}`}>
      <span className="tool-icon" aria-hidden="true">{icon}</span>
      <button type="button" className="tool-button" disabled={disabled} aria-describedby={`${id}-blurb ${id}-state`} onClick={onRun}>{title}</button>
      <span id={`${id}-blurb`} className="tool-blurb">{blurb}</span>
      <span id={`${id}-state`} className="tool-state">{ready ? <><span aria-hidden="true">●</span> {readyWord}</> : waitWord}</span>
    </li>
  );
}

function LockIcon() {
  return (
    <svg viewBox="0 0 24 24" width="22" height="22" focusable="false" aria-hidden="true">
      <rect x="5" y="11" width="14" height="9" rx="2" fill="none" stroke="currentColor" strokeWidth="1.8" />
      <path d="M8 11V8a4 4 0 0 1 8 0v3" fill="none" stroke="currentColor" strokeWidth="1.8" />
    </svg>
  );
}

type Card = { jobId: string; kind: "answer" | "related" };

/** The Reader's tools as tiles (Understand, Explore, Coming) and their answers as cards, newest first. */
export function ReaderTools({ runId, paperId, selection, drawer }: { runId: string; paperId: string; selection: string; drawer: DrawerOut | undefined }) {
  const ask = useReaderAsk(runId, paperId);
  const related = useReaderRelated(runId, paperId);
  const [question, setQuestion] = useState("");
  const [cards, setCards] = useState<Card[]>([]);
  const [problem, setProblem] = useState<string | null>(null);
  const newest = useJob(cards[0]?.jobId ?? null);
  const tooLong = selection.length > MAX_SELECTION;
  const running = ask.isPending || related.isPending || ["queued", "running"].includes(newest.data?.status ?? "");
  const selected = !!selection && !tooLong;
  const whole = "Uses the whole paper";
  const onSelection = "Ready for your selection";

  const run = async (tool: ReaderTool) => {
    setProblem(null);
    try {
      const started = await ask.mutateAsync({ tool, selection, question: tool === "explain" ? "" : question });
      setCards((list) => [{ jobId: started.id, kind: "answer" }, ...list]);
    } catch (error) {
      setProblem(errorText(error));
    }
  };
  const search = async (mode: RelatedMode) => {
    setProblem(null);
    try {
      const started = await related.mutateAsync({ mode, selection });
      setCards((list) => [{ jobId: started.id, kind: "related" }, ...list]);
    } catch (error) {
      setProblem(errorText(error));
    }
  };
  const target = selection ? "the selection" : "the whole paper";

  return (
    <section aria-labelledby="reader-tools-heading" className="reader-tools">
      <h2 id="reader-tools-heading">Ask about {target}</h2>
      {tooLong && <p role="alert" className="form-error">The selection is {selection.length.toLocaleString()} characters; select at most {MAX_SELECTION.toLocaleString()}.</p>}

      <section aria-labelledby="tools-understand" className="tool-group">
        <h3 id="tools-understand">Understand</h3>
        <ul className="tool-tiles">
          <Tile id="tool-explain" icon="❝" title="Explain (from the paper)" blurb="Plain words, every statement quoted from the paper." ready={selected} readyWord={onSelection} waitWord={whole} disabled={running || tooLong} onRun={() => void run("explain")} />
          <Tile id="tool-background" icon="≈" title="Background explanation" blurb="General knowledge behind a term or method, not from this paper." ready={selected || !!question.trim()} readyWord={selected ? onSelection : "Ready for your question"} waitWord="Select a passage or write a question" disabled={running || tooLong || !(selection || question.trim())} onRun={() => void run("background")} />
          <li className="tool-tile tool-tile--wide">
            <span className="tool-icon" aria-hidden="true">?</span>
            <form className="reader-ask" onSubmit={(e) => { e.preventDefault(); void run("ask"); }}>
              <label className="block">Question about the paper
                <textarea rows={2} maxLength={1000} value={question} onChange={(e) => setQuestion(e.target.value)} placeholder="e.g. Was the test set external?" />
              </label>
              <button type="submit" className="primary" disabled={running || tooLong || !question.trim()}>Ask</button>
            </form>
          </li>
        </ul>
        <p className="sub">Explain and Ask answer only from this paper, each statement with an exact quote checked by code; “the paper does not say” is a valid answer. Background explanation is general knowledge, not from this paper.</p>
      </section>

      <section aria-labelledby="reader-related-heading" className="tool-group">
        <h3 id="reader-related-heading">Explore</h3>
        <ul className="tool-tiles">
          <Tile id="tool-related" icon="⌕" title="Find related" blurb="Papers on the same key terms in the sources, the library and past runs." ready={selected} readyWord={onSelection} waitWord="Uses the paper's title" disabled={running || tooLong} onRun={() => void search("related")} />
          <Tile id="tool-earlier" icon="↶" title="Earlier work" blurb="The same search, sorted by year around this paper's own." ready={selected} readyWord={onSelection} waitWord="Uses the paper's title" disabled={running || tooLong} onRun={() => void search("earlier")} />
        </ul>
        <p className="sub">Searches the enabled sources (10 results each), the team library and past runs for the key terms of {selection ? "the selection" : "the paper's title"}.</p>
      </section>

      <section aria-labelledby="tools-coming" className="tool-group tool-group--coming">
        <h3 id="tools-coming">Coming</h3>
        <ul className="tool-tiles reader-later">
          <li className="tool-tile is-locked">
            <span className="tool-icon" aria-hidden="true"><LockIcon /></span>
            <button type="button" className="tool-button" disabled aria-describedby="later-inhouse">In-house</button>
            <span id="later-inhouse" className="tool-blurb">needs an internal collection — coming</span>
            <span className="tool-state">Locked</span>
          </li>
        </ul>
      </section>

      <section aria-labelledby="answers-heading" className="answer-stack">
        <h3 id="answers-heading" className={cards.length ? undefined : "sr-only"}>Answers{cards.length ? ` (${cards.length}, newest first)` : ""}</h3>
        <div aria-live="polite">
          {problem && <p role="alert" className="form-error">{problem}</p>}
          {cards.length > 0 && (
            <ol className="answer-list">
              {cards.map((card) => card.kind === "answer"
                ? <AnswerCard key={card.jobId} jobId={card.jobId} runId={runId} paperId={paperId} drawer={drawer} />
                : <RelatedCard key={card.jobId} jobId={card.jobId} />)}
            </ol>
          )}
        </div>
      </section>
    </section>
  );
}
