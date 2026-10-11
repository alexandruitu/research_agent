import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useLocation, useParams } from "react-router-dom";

import { ApiError } from "../api/client";
import { usePaper, useReader } from "../api/hooks";
import { hasRole, type ReaderHighlight, type ReaderOut } from "../api/types";
import { useAuth } from "../auth/AuthProvider";
import { FlowStepper } from "../components/FlowStepper";
import { Skeleton } from "../components/ui/Skeleton";
import { statusMeta } from "../components/ui/StatusMark";
import { QualityCell } from "../features/papers/cells";
import { drawerWhy } from "../features/papers/why";
import { useSaveFlow } from "../features/library/saveFlow";
import { readOrigin } from "../features/reader/origin";
import { ReaderNotes } from "../features/reader/ReaderNotes";
import { ReaderTools } from "../features/reader/ReaderTools";
import { segments, selectionIn, unplaced } from "../features/reader/segments";

const KIND_WORD: Record<string, string> = { red_flag: "Red flag", claim: "Claim" };
const hlId = (index: number) => `hl-${index}`;

function describe(h: ReaderHighlight) {
  return `${KIND_WORD[h.kind] ?? h.kind}: ${h.label} (${h.by})`;
}

/** The paper's text by sections, the run's quotes marked in place. */
function PaperText({ data, onActive }: { data: ReaderOut; onActive: (h: ReaderHighlight[] | null) => void }) {
  const index = new Map(data.highlights.map((h, i) => [h, i]));
  return (
    <>
      {data.text.sections.map((section, s) => (
        <section key={s} className="reader-section" aria-labelledby={section.title ? `sec-${s}` : undefined}>
          {section.title && <h2 id={`sec-${s}`}>{section.title}</h2>}
          <p className="reader-paragraph">
            {segments(section.text, data.highlights).map((piece, p) =>
              piece.marks.length === 0 ? (
                <span key={p}>{piece.text}</span>
              ) : (
                <mark
                  key={p}
                  tabIndex={0}
                  className={`reader-mark ${piece.marks.some((m) => m.kind === "red_flag") ? "reader-mark--flag" : "reader-mark--claim"}`}
                  aria-describedby={piece.marks.map((m) => hlId(index.get(m) ?? 0)).join(" ")}
                  onMouseEnter={() => onActive(piece.marks)}
                  onMouseLeave={() => onActive(null)}
                  onFocus={() => onActive(piece.marks)}
                  onBlur={() => onActive(null)}
                >
                  <span className="sr-only">{piece.marks.some((m) => m.kind === "red_flag") ? "Red flag quote: " : "Claim quote: "}</span>
                  {piece.text}
                </mark>
              ),
            )}
          </p>
        </section>
      ))}
    </>
  );
}

export function ReaderPage() {
  const { runId = "", paperId = "" } = useParams();
  const origin = readOrigin(useLocation().state);
  const { user } = useAuth();
  const member = hasRole(user, "member");
  const reader = useReader(runId, paperId);
  const paper = usePaper(runId, paperId);
  const libraryFlow = useSaveFlow();
  const article = useRef<HTMLElement>(null);
  const heading = useRef<HTMLHeadingElement>(null);
  const [selection, setSelection] = useState("");
  const [active, setActive] = useState<ReaderHighlight[] | null>(null);
  const readSelection = useCallback(() => setSelection(selectionIn(article.current)), []);
  useEffect(() => {
    heading.current?.focus();
  }, [reader.data?.paper.id]);
  // Back to where the reader came from; opened from a link elsewhere, back to the paper in its run's Results
  const back = origin?.from === "library"
    ? { to: origin.back, word: "Back to Library" }
    : { to: origin?.back ?? `/results?run=${runId}&paper=${paperId}`, word: "Back to Results" };

  if (reader.isLoading) return <div className="reader"><Skeleton label="the paper" rows={8} /></div>;
  if (reader.isError || !reader.data) {
    return (
      <div className="reader">
        <p role="alert" className="form-error">{reader.error instanceof ApiError ? reader.error.message : "Could not load this paper."}</p>
        <p><Link to={back.to}>{back.word}</Link></p>
      </div>
    );
  }
  const data = reader.data;
  const drawer = paper.data;
  const lost = unplaced(data.text.sections, data.highlights);
  const flags = drawer?.panel?.red_flags ?? [];
  const inLibrary = drawer?.library ?? null;
  const saveToLibrary = member && drawer && !inLibrary
    ? <button type="button" className="primary" disabled={libraryFlow.pending} onClick={() => void libraryFlow.save(runId, [paperId], { status: "to_read", note: "" })}>Save to library</button>
    : undefined;

  return (
    <div className={`reader ${origin?.from === "library" ? "reader--from-library" : ""}`}>
      <FlowStepper current={4} next={saveToLibrary} />
      <header className="reader-head">
        <p className="reader-back"><Link to={back.to}><span aria-hidden="true">←</span> {back.word}</Link>{data.run_name ? <span className="sub"> · {data.run_name}</span> : null}</p>
        <h1 ref={heading} tabIndex={-1}>{data.paper.title}</h1>
        <p className="sub">{data.paper.year ?? ""}{data.paper.doi ? ` · ${data.paper.doi}` : ""} · {data.paper.source_id} · <Link to="/validation">How do we know this is right?</Link></p>
      </header>
      <details className="reader-strip">
        <summary>
          <span className="strip-title">In this run</span>
          <span className="strip-item">Quality: <QualityCell group={data.group ?? null} /></span>
          <span className="strip-item">{flags.length ? <><span aria-hidden="true">⚑</span> {flags.length} red flag{flags.length === 1 ? "" : "s"}</> : "No red flags"}</span>
          <span className="strip-item">Team status: {inLibrary ? statusMeta(inLibrary.status).word : "Not in the library"}</span>
          {data.highlights.length > 0 && <span className="strip-item">{data.highlights.length} quote{data.highlights.length === 1 ? "" : "s"} from this run</span>}
          <span className="strip-more">Details</span>
        </summary>
        <div className="strip-body">
          <section aria-labelledby="reader-context-heading" className="reader-context">
            <h2 id="reader-context-heading">Why it is here</h2>
            {drawer ? <p className="drawer-why"><span className="sr-only">Why: </span>{drawerWhy(drawer)}</p> : <p className="sub">Loading the run's verdict…</p>}
            {flags.length > 0 && (
              <>
                <h3>Red flags</h3>
                <ul>{flags.map((f, i) => <li key={i}>{f.text}</li>)}</ul>
              </>
            )}
            <p className="strip-links">
              <Link to={`/results?run=${data.run_id}&paper=${data.paper.id}`}>The paper in its run</Link>
              {inLibrary && <> · <Link to={`/library?item=${inLibrary.item_id}`}>Library details (note, tags, history)</Link></>}
            </p>
          </section>
          {data.highlights.length > 0 && (
            <section aria-labelledby="reader-quotes-heading" className="reader-quotes">
              <h2 id="reader-quotes-heading">Quotes from this run ({data.highlights.length})</h2>
              <ul>{data.highlights.map((h, i) => <li key={i} id={hlId(i)}>{describe(h)}</li>)}</ul>
              {lost.length > 0 && <p className="sub">{lost.length} quote{lost.length === 1 ? "" : "s"} could not be placed in the text shown (e.g. spanning two sections).</p>}
            </section>
          )}
        </div>
      </details>
      <div className="reader-layout">
        <article ref={article} className="reader-text" aria-label="Paper text" onMouseUp={readSelection} onKeyUp={readSelection} onTouchEnd={readSelection}>
          {data.text.kind === "abstract" ? (
            <p className="banner banner--warn" role="note">Abstract only — upload the PDF to read and ask about the full paper.</p>
          ) : (
            <p className="sub">Full text ({data.text.source === "upload" ? "uploaded PDF" : data.text.source}){data.text.truncated ? "; shortened to the length the reviewers read" : ""}.</p>
          )}
          {data.highlights.length > 0 && (
            <p className="reader-legend sub">
              <mark className="reader-mark reader-mark--flag">Red flag quote</mark> <mark className="reader-mark reader-mark--claim">Claim quote</mark>{" "}
              Hover or focus a marked passage to see where it came from.
            </p>
          )}
          <div className="reader-active" aria-live="polite">{active && active.map((h, i) => <p key={i}>{describe(h)}</p>)}</div>
          {data.text.sections.length === 0 ? <p>No text: this paper has no abstract and no full text.</p> : <PaperText data={data} onActive={setActive} />}
        </article>
        <aside className="reader-panel" aria-label="Reading tools">
          <p className={`reader-selection ${selection ? "has-selection" : ""}`} aria-live="polite">
            {selection ? <>Selected: “{selection.length > 160 ? `${selection.slice(0, 159)}…` : selection}” ({selection.length.toLocaleString()} characters) <button type="button" className="linklike" onClick={() => { window.getSelection()?.removeAllRanges(); setSelection(""); }}>Clear</button></> : "Nothing selected: the tools use the whole paper. Select a passage in the text to ask about it."}
          </p>
          {member ? <ReaderTools runId={runId} paperId={paperId} selection={selection} drawer={drawer} /> : <p className="sub">Viewers can read the paper and the notes; members can ask the AI and save notes.</p>}
          <ReaderNotes paperId={paperId} />
        </aside>
      </div>
    </div>
  );
}
