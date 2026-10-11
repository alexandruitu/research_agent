import { type KeyboardEvent, useCallback, useLayoutEffect, useEffect, useRef, useState } from "react";
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
import { PaperMapView } from "../features/reader/PaperMap";
import { ReaderNotes } from "../features/reader/ReaderNotes";
import { ReaderTools } from "../features/reader/ReaderTools";
import { segments, selectionIn, unplaced } from "../features/reader/segments";

const KIND_WORD: Record<string, string> = { red_flag: "Red flag", claim: "Claim", map: "From the paper map" };
const hlId = (index: number) => `hl-${index}`;
/** A quote marked in the text: one of the run's, or the one a paper-map node jumped to. */
type Mark = ReaderHighlight | { kind: "map"; quote: string; label: string; by: string };
type Jump = { quote: string; lit: boolean; seq: number };

function describe(h: Mark) {
  return h.kind === "map" ? `${KIND_WORD.map}: ${h.label}` : `${KIND_WORD[h.kind] ?? h.kind}: ${h.label} (${h.by})`;
}

function markClass(marks: Mark[], lit: boolean) {
  const base = marks.some((m) => m.kind === "red_flag") ? "reader-mark--flag" : marks.some((m) => m.kind === "claim") ? "reader-mark--claim" : "reader-mark--plain";
  return `reader-mark ${base}${marks.some((m) => m.kind === "map") ? ` reader-mark--focus${lit ? " is-lit" : ""}` : ""}`;
}

/** The paper's text by sections, the run's quotes marked in place (and the quote a map node jumped to). */
function PaperText({ data, jump, onActive }: { data: ReaderOut; jump: Jump | null; onActive: (h: Mark[] | null, anchor?: HTMLElement) => void }) {
  const index = new Map(data.highlights.map((h, i) => [h, i]));
  const marks: Mark[] = jump ? [...data.highlights, { kind: "map", quote: jump.quote, label: "the passage you opened from the map", by: "" }] : data.highlights;
  let placed = false;
  return (
    <>
      {data.text.sections.map((section, s) => (
        <section key={s} className="reader-section" aria-labelledby={section.title ? `sec-${s}` : undefined}>
          {section.title && <h2 id={`sec-${s}`}>{section.title}</h2>}
          <p className="reader-paragraph">
            {segments(section.text, marks).map((piece, p) => {
              const focus = !placed && piece.marks.some((m) => m.kind === "map");
              if (focus) placed = true;
              return piece.marks.length === 0 ? (
                <span key={p}>{piece.text}</span>
              ) : (
                <mark
                  key={p}
                  id={focus ? "map-focus" : undefined}
                  tabIndex={0}
                  className={markClass(piece.marks, !!jump?.lit)}
                  aria-describedby={piece.marks.filter((m) => m.kind !== "map").map((m) => hlId(index.get(m as ReaderHighlight) ?? 0)).join(" ") || undefined}
                  onMouseEnter={(e) => onActive(piece.marks, e.currentTarget)}
                  onMouseLeave={() => onActive(null)}
                  onFocus={(e) => onActive(piece.marks, e.currentTarget)}
                  onBlur={() => onActive(null)}
                >
                  <span className="sr-only">{piece.marks.some((m) => m.kind === "red_flag") ? "Red flag quote: " : piece.marks.some((m) => m.kind === "claim") ? "Claim quote: " : "Map quote: "}</span>
                  {piece.text}
                </mark>
              );
            })}
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
  const [active, setActiveState] = useState<{ marks: Mark[]; anchor: HTMLElement | null } | null>(null);
  const setActive = useCallback((marks: Mark[] | null, anchor: HTMLElement | null = null) => setActiveState(marks ? { marks, anchor } : null), []);
  const [tab, setTab] = useState<"text" | "map">("text");
  const [jump, setJump] = useState<Jump | null>(null);
  const [jumpNote, setJumpNote] = useState("");
  const onJump = useCallback((quote: string) => {
    setActiveState(null);
    setTab("text");
    setJump((j) => ({ quote, lit: true, seq: (j?.seq ?? 0) + 1 }));
  }, []);
  // A map node opened: scroll to its quote, focus it, light it for 2 s (no smooth scroll with reduced motion)
  useEffect(() => {
    if (!jump?.lit || tab !== "text") return;
    const node = document.getElementById("map-focus");
    if (node) {
      const reduced = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
      node.scrollIntoView?.({ block: "center", behavior: reduced ? "auto" : "smooth" });
      node.focus({ preventScroll: true });
      setJumpNote("Showing the map's quote in the text.");
    } else {
      setJumpNote("This quote could not be placed in the text shown (it may span two sections).");
    }
    const timer = window.setTimeout(() => setJump((j) => (j ? { ...j, lit: false } : j)), 2000);
    return () => window.clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- runs once per jump
  }, [jump?.seq, tab]);
  const onTabKey = (e: KeyboardEvent) => {
    if (e.key !== "ArrowLeft" && e.key !== "ArrowRight") return;
    const next = tab === "text" ? "map" : "text";
    setTab(next);
    document.getElementById(`reader-tab-${next}`)?.focus();
  };
  const pop = useRef<HTMLDivElement>(null);
  // The source card sits next to the hovered passage (below it, or above when there is no room), never over it;
  // positioned through the CSSOM, which the CSP allows.
  useLayoutEffect(() => {
    const node = pop.current;
    const rect = active?.anchor?.getBoundingClientRect();
    if (!node || !rect) return;
    const width = node.offsetWidth;
    const left = Math.max(8, Math.min(rect.left, window.innerWidth - width - 8));
    const below = rect.bottom + 8;
    const top = below + node.offsetHeight > window.innerHeight - 8 ? Math.max(8, rect.top - node.offsetHeight - 8) : below;
    node.style.left = `${left}px`;
    node.style.top = `${top}px`;
  }, [active]);
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
        <div className="reader-main">
        <div role="tablist" aria-label="View" className="reader-tabs" onKeyDown={onTabKey}>
          {(["text", "map"] as const).map((t) => (
            <button key={t} type="button" role="tab" id={`reader-tab-${t}`} aria-selected={tab === t} aria-controls={`reader-panel-${t}`} tabIndex={tab === t ? 0 : -1} className="reader-tab" onClick={() => setTab(t)}>
              {t === "text" ? "Text" : "Map"}
            </button>
          ))}
        </div>
        <p className="sr-only" aria-live="polite">{jumpNote}</p>
        {tab === "map" ? (
          <div role="tabpanel" id="reader-panel-map" aria-labelledby="reader-tab-map" className="reader-map-panel">
            <PaperMapView runId={runId} paperId={paperId} title={data.paper.title} member={member} onJump={onJump} />
          </div>
        ) : (
        <div role="tabpanel" id="reader-panel-text" aria-labelledby="reader-tab-text">
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
          <div className="sr-only" aria-live="polite">{active && active.marks.map((h, i) => <p key={i}>{describe(h)}</p>)}</div>
          {active?.anchor && (
            <div ref={pop} className="reader-pop" aria-hidden="true">
              {active.marks.map((h, i) => <p key={i} className={h.kind === "red_flag" ? "reader-pop__flag" : h.kind === "claim" ? "reader-pop__claim" : undefined}>{describe(h)}</p>)}
            </div>
          )}
          {data.text.sections.length === 0 ? <p>No text: this paper has no abstract and no full text.</p> : <PaperText data={data} jump={jump} onActive={setActive} />}
        </article>
        </div>
        )}
        </div>
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
