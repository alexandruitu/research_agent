import { useEffect, useRef, useState, type FormEvent } from "react";

import { ApiError } from "../../api/client";
import { useCollections, useEligibility, useUploadPaperFile } from "../../api/hooks";
import type { CollectionOut, LibraryScope, LibrarySaveRequest } from "../../api/types";
import { TagInput } from "../fieldflow/TagInput";
import type { SaveChoice } from "./saveFlow";
import { StatusControl } from "./StatusControl";

type Props = {
  runId: string;
  paperIds: string[];
  /** Titles of the papers, to name the abstract-only ones (optional). */
  titles?: Record<string, string>;
  onSave: (choice: SaveChoice) => void;
  onClose: () => void;
};

const LIBRARY_LABEL: Record<LibraryScope, string> = { personal: "My library", company: "Company library" };
const MAX_UPLOADS_LISTED = 5;

/** One "Upload the PDF" button for an abstract-only paper: once uploaded, the paper has full text. */
function UploadPdf({ paperId, title }: { paperId: string; title: string }) {
  const upload = useUploadPaperFile(paperId);
  const input = useRef<HTMLInputElement>(null);
  const [problem, setProblem] = useState<string | null>(null);
  return (
    <li>
      <span className="upload-title">{title}</span>{" "}
      <input ref={input} type="file" accept="application/pdf,.pdf" hidden aria-label={`PDF of ${title}`}
        onChange={(e) => {
          const file = e.target.files?.[0];
          if (!file) return;
          setProblem(null);
          upload.mutateAsync({ file }).catch((error: unknown) => setProblem(error instanceof ApiError ? error.message : "The upload failed."));
        }} />
      <button type="button" onClick={() => input.current?.click()} disabled={upload.isPending}>
        {upload.isPending ? "Uploading…" : "Upload the PDF"}<span className="sr-only"> of {title}</span>
      </button>
      {problem && <span role="alert" className="form-error"> {problem}</span>}
    </li>
  );
}

function CollectionPicks({ scope, collections, chosen, onToggle }: { scope: LibraryScope; collections: CollectionOut[]; chosen: string[]; onToggle: (id: string, on: boolean) => void }) {
  return (
    <fieldset>
      <legend>Collections in {LIBRARY_LABEL[scope]}</legend>
      {collections.length === 0 ? <p className="hint">No collections yet.</p> : (
        <ul className="check-list">
          {collections.map((c) => (
            <li key={c.id}><label className="check"><input type="checkbox" checked={chosen.includes(c.id)} onChange={(e) => onToggle(c.id, e.target.checked)} /> {c.name} <span className="sub-inline">({c.item_count})</span></label></li>
          ))}
        </ul>
      )}
    </fieldset>
  );
}

/**
 * Where the selected papers go: My library (private) and/or the Company library (everyone; only papers with
 * full text), collections in each (or a new one), tags, the status and a note.
 */
export function SaveDialog({ runId, paperIds, titles = {}, onSave, onClose }: Props) {
  const dialog = useRef<HTMLDialogElement>(null);
  const [scopes, setScopes] = useState<LibraryScope[]>(["personal"]);
  const mineOn = scopes.includes("personal");
  const companyOn = scopes.includes("company");
  const mine = useCollections(false, "personal", mineOn);
  const company = useCollections(false, "company", companyOn);
  const eligibility = useEligibility(runId, paperIds);
  const [chosen, setChosen] = useState<Record<LibraryScope, string[]>>({ personal: [], company: [] });
  const [newName, setNewName] = useState("");
  const [tags, setTags] = useState<string[]>([]);
  const [status, setStatus] = useState("to_read");
  const [note, setNote] = useState("");
  useEffect(() => {
    const opener = document.activeElement as HTMLElement | null;
    const node = dialog.current;
    if (node && !node.open) {
      if (typeof node.showModal === "function") node.showModal();
      else node.setAttribute("open", "");
    }
    node?.querySelector<HTMLElement>("input, button")?.focus();
    return () => opener?.focus?.();
  }, []);

  const papers = eligibility.data?.papers ?? [];
  const abstractOnly = papers.filter((p) => !p.has_full_text).map((p) => p.paper_id);
  const checking = eligibility.isLoading;
  const companyBlocked = checking || eligibility.isError || abstractOnly.length > 0;
  const blockedReason = checking
    ? "Checking which papers have full text…"
    : eligibility.isError
      ? "Could not check whether these papers have full text. Reload the page to try again."
      : abstractOnly.length === paperIds.length
        ? `${paperIds.length === 1 ? "This paper has" : "These papers have"} only an abstract. The Company library keeps papers with full text.`
        : `${abstractOnly.length} of these ${paperIds.length} papers ${abstractOnly.length === 1 ? "has" : "have"} only an abstract. The Company library keeps papers with full text.`;
  // a paper that just got its PDF can go to the Company library: the box stays as the user left it otherwise
  useEffect(() => {
    if (companyBlocked) setScopes((list) => list.filter((s) => s !== "company"));
  }, [companyBlocked]);

  const setScope = (scope: LibraryScope, on: boolean) => setScopes((list) => (on ? [...new Set([...list, scope])] : list.filter((s) => s !== scope)));
  const toggle = (scope: LibraryScope) => (id: string, on: boolean) =>
    setChosen((all) => ({ ...all, [scope]: on ? [...all[scope], id] : all[scope].filter((c) => c !== id) }));
  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (!scopes.length) return;
    const name = newName.trim();
    // a "new" name that already exists in a chosen library means that collection: never fail on a name clash
    const collections: Partial<Record<LibraryScope, string[]>> = {};
    let clash = false;
    for (const scope of scopes) {
      const list = (scope === "personal" ? mine.data : company.data) ?? [];
      const same = name ? list.find((c) => c.name.toLowerCase() === name.toLowerCase()) : undefined;
      if (same) clash = true;
      collections[scope] = same && !chosen[scope].includes(same.id) ? [...chosen[scope], same.id] : chosen[scope];
    }
    onSave({
      scopes, collections, new_collection: name && !clash ? { name, description: "", scope: "personal" } : null, tags,
      status: status as LibrarySaveRequest["status"], note: note.trim(),
    });
  };
  const count = paperIds.length;
  return (
    <dialog ref={dialog} className="modal save-dialog" aria-labelledby="save-title" onCancel={(e) => { e.preventDefault(); onClose(); }}>
      <form onSubmit={submit} className="save-form">
        <h2 id="save-title">Save {count} paper{count === 1 ? "" : "s"} to the library</h2>
        <fieldset className="library-choice">
          <legend>Which library</legend>
          <label className="check">
            <input type="checkbox" checked={mineOn} onChange={(e) => setScope("personal", e.target.checked)} /> My library
            <span className="sub-inline"> (only you see it)</span>
          </label>
          <label className="check">
            <input type="checkbox" checked={companyOn} disabled={companyBlocked} aria-describedby={companyBlocked ? "company-reason" : undefined}
              onChange={(e) => setScope("company", e.target.checked)} /> Company library
            <span className="sub-inline"> (everyone in the company sees it; full text only)</span>
          </label>
          {companyBlocked && (
            <div id="company-reason" className="hint company-reason" role="note">
              <p>{blockedReason}</p>
              {abstractOnly.length > 0 && (
                <>
                  <ul className="upload-list">
                    {abstractOnly.slice(0, MAX_UPLOADS_LISTED).map((id) => <UploadPdf key={id} paperId={id} title={titles[id] ?? (count === 1 ? "this paper" : "a paper")} />)}
                  </ul>
                  {abstractOnly.length > MAX_UPLOADS_LISTED && <p>and {abstractOnly.length - MAX_UPLOADS_LISTED} more: upload their PDFs from each paper’s details.</p>}
                </>
              )}
            </div>
          )}
          {!scopes.length && <p role="alert" className="form-error">Choose at least one library.</p>}
        </fieldset>
        {mineOn && <CollectionPicks scope="personal" collections={mine.data ?? []} chosen={chosen.personal} onToggle={toggle("personal")} />}
        {companyOn && <CollectionPicks scope="company" collections={company.data ?? []} chosen={chosen.company} onToggle={toggle("company")} />}
        <label className="block">New collection (optional)<input value={newName} maxLength={100} onChange={(e) => setNewName(e.target.value)} placeholder="e.g. Plaque: to discuss on Friday" /></label>
        <TagInput label="Tags" tags={tags} onChange={setTags} placeholder="Add a tag and press Enter" />
        <StatusControl value={status} onChange={setStatus} label="Status" />
        <label className="block">Note (optional)<textarea rows={2} maxLength={5000} value={note} onChange={(e) => setNote(e.target.value)} /></label>
        <p className="hint">Papers already in a library keep their status and note there; the collections and tags are added to them.</p>
        <div className="actions">
          <button type="submit" className="primary" disabled={!scopes.length}>Save to library</button>
          <button type="button" onClick={onClose}>Cancel</button>
        </div>
      </form>
    </dialog>
  );
}
