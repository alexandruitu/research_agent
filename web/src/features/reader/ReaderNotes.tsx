import { ApiError } from "../../api/client";
import { usePaperNotes } from "../../api/hooks";
import type { ReaderNoteOut } from "../../api/types";

export const TOOL_LABEL: Record<string, string> = { explain: "Explain", ask: "Ask", background: "Background explanation" };
export const GENERAL_LABEL = "General knowledge — not from this paper, verify before relying on it";

function Note({ note }: { note: ReaderNoteOut }) {
  return (
    <li className="reader-note">
      <p className="sub">
        {TOOL_LABEL[note.tool] ?? note.tool} · {note.created_by_name ?? "Someone"} · <time dateTime={note.created_at}>{new Date(note.created_at).toLocaleDateString()}</time>
        {note.model ? ` · ${note.model}` : ""}
      </p>
      {note.selection && <blockquote className="reader-note-selection">“{note.selection}”</blockquote>}
      {note.question && <p><strong>Q:</strong> {note.question}</p>}
      {note.general && <p className="chip chip--warn">{GENERAL_LABEL}</p>}
      <p>{note.answer}</p>
      {note.not_in_paper && <p className="sub">The paper does not say.</p>}
      {note.quotes.length > 0 && (
        <ul className="reader-statements">
          {note.quotes.map((q, i) => <li key={i}>{q.text} <q className="reader-quote">{q.quote}</q></li>)}
        </ul>
      )}
    </li>
  );
}

/** The team's Reader notes on one paper (Reader and Library item). */
export function ReaderNotes({ paperId, headingLevel = 3 }: { paperId: string; headingLevel?: 2 | 3 }) {
  const notes = usePaperNotes(paperId);
  const Heading = headingLevel === 2 ? "h2" : "h3";
  return (
    <section aria-labelledby={`notes-${paperId}`} className="reader-notes">
      <Heading id={`notes-${paperId}`}>Reader notes</Heading>
      {notes.isLoading && <p role="status">Loading notes…</p>}
      {notes.isError && <p role="alert" className="form-error">{notes.error instanceof ApiError ? notes.error.message : "Could not load the notes."}</p>}
      {notes.data && notes.data.length === 0 && <p className="sub">No notes yet. Save an answer from the Reader to keep it here.</p>}
      {notes.data && notes.data.length > 0 && <ul className="reader-note-list">{notes.data.map((n) => <Note key={n.id} note={n} />)}</ul>}
    </section>
  );
}
