import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";

import { ApiError } from "../api/client";
import { usePaper, useReader } from "../api/hooks";
import { hasRole, type ReaderHighlight, type ReaderOut } from "../api/types";
import { useAuth } from "../auth/AuthProvider";
import { Skeleton } from "../components/ui/Skeleton";
import { statusMeta } from "../components/ui/StatusMark";
import { QualityCell } from "../features/papers/cells";
import { drawerWhy } from "../features/papers/why";
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
  const { user } = useAuth();
  const member = hasRole(user, "member");
  const reader = useReader(runId, paperId);
  const paper = usePaper(runId, paperId);
  const article = useRef<HTMLElement>(null);
  const heading = useRef<HTMLHeadingElement>(null);
  const [selection, setSelection] = useState("");
  const [active, setActive] = useState<ReaderHighlight[] | null>(null);
  const readSelection = useCallback(() => setSelection(selectionIn(article.current)), []);
  useEffect(() => {
    heading.current?.focus();
  }, [reader.data?.paper.id]);

  if (reader.isLoading) return <div className="reader"><Skeleton label="the paper" rows={8} /></div>;
  if (reader.isError || !reader.data) {
    return (
      <div className="reader">
        <p role="alert" className="form-error">{reader.error instanceof ApiError ? reader.error.message : "Could not load this paper."}</p>
        <p><Link to="/">Back to Papers</Link></p>
      </div>
    );
  }
  const data = reader.data;
  const drawer = paper.data;
  const lost = unplaced(data.text.sections, data.highlights);
  const flags = drawer?.panel?.red_flags ?? [];

  return (
    <div className="reader">
      <header className="reader-head">
        <p className="sub"><Link to={`/?run=${data.run_id}&paper=${data.paper.id}`}>← Back to the paper in its run</Link>{data.run_name ? ` · ${data.run_name}` : ""}</p>
        <h1 ref={heading} tabIndex={-1}>{data.paper.title}</h1>
        <p className="sub">{data.paper.year ?? ""}{data.paper.doi ? ` · ${data.paper.doi}` : ""} · {data.paper.source_id}</p>
        <p className="trust-link"><Link to="/validation">How do we know this is right? <span aria-hidden="true">→</span></Link></p>
      </header>
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
          <section aria-labelledby="reader-context-heading" className="reader-context">
            <h2 id="reader-context-heading">In this run</h2>
            <p>Quality: <QualityCell group={data.group ?? null} /></p>
            {drawer && <p className="drawer-why"><span className="sr-only">Why: </span>{drawerWhy(drawer)}</p>}
            {flags.length > 0 && (
              <>
                <h3>Red flags</h3>
                <ul>{flags.map((f, i) => <li key={i}>{f.text}</li>)}</ul>
              </>
            )}
            <p>Team status: {drawer?.library ? statusMeta(drawer.library.status).word : "Not in the library"}</p>
          </section>
          {data.highlights.length > 0 && (
            <details className="reader-quotes">
              <summary>Quotes from this run ({data.highlights.length})</summary>
              <ul>{data.highlights.map((h, i) => <li key={i} id={hlId(i)}>{describe(h)}</li>)}</ul>
              {lost.length > 0 && <p className="sub">{lost.length} quote{lost.length === 1 ? "" : "s"} could not be placed in the text shown (e.g. spanning two sections).</p>}
            </details>
          )}
          <p className="reader-selection" aria-live="polite">
            {selection ? <>Selected: “{selection.length > 160 ? `${selection.slice(0, 159)}…` : selection}” ({selection.length.toLocaleString()} characters) <button type="button" className="linklike" onClick={() => { window.getSelection()?.removeAllRanges(); setSelection(""); }}>Clear</button></> : "Nothing selected: the tools use the whole paper. Select a passage in the text to ask about it."}
          </p>
          {member ? <ReaderTools runId={runId} paperId={paperId} selection={selection} drawer={drawer} /> : <p className="sub">Viewers can read the paper and the notes; members can ask the AI and save notes.</p>}
          <ReaderNotes paperId={paperId} />
        </aside>
      </div>
    </div>
  );
}
