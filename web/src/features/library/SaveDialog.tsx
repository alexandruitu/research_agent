import { useEffect, useRef, useState, type FormEvent } from "react";

import { useCollections } from "../../api/hooks";
import type { LibrarySaveRequest } from "../../api/types";
import { TagInput } from "../fieldflow/TagInput";
import type { SaveChoice } from "./saveFlow";
import { StatusControl } from "./StatusControl";

type Props = { count: number; onSave: (choice: SaveChoice) => void; onClose: () => void };

/** Where the selected papers go: collections (or a new one), tags, the team status and a note. */
export function SaveDialog({ count, onSave, onClose }: Props) {
  const dialog = useRef<HTMLDialogElement>(null);
  const collections = useCollections();
  const [chosen, setChosen] = useState<string[]>([]);
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
  const submit = (event: FormEvent) => {
    event.preventDefault();
    const name = newName.trim();
    // a "new" name that already exists means that collection: never fail the save on a name clash
    const same = (collections.data ?? []).find((c) => c.name.toLowerCase() === name.toLowerCase());
    const ids = same && !chosen.includes(same.id) ? [...chosen, same.id] : chosen;
    onSave({
      collection_ids: ids, new_collection: name && !same ? { name, description: "" } : null, tags, status: status as LibrarySaveRequest["status"], note: note.trim(),
    });
  };
  const toggle = (id: string, on: boolean) => setChosen((list) => (on ? [...list, id] : list.filter((c) => c !== id)));
  return (
    <dialog ref={dialog} className="modal save-dialog" aria-labelledby="save-title" onCancel={(e) => { e.preventDefault(); onClose(); }}>
      <form onSubmit={submit} className="save-form">
        <h2 id="save-title">Save {count} paper{count === 1 ? "" : "s"} to the library</h2>
        <fieldset>
          <legend>Collections</legend>
          {(collections.data ?? []).length === 0 && <p className="hint">No collections yet. Name one below, or save without.</p>}
          <ul className="check-list">
            {(collections.data ?? []).map((c) => (
              <li key={c.id}><label className="check"><input type="checkbox" checked={chosen.includes(c.id)} onChange={(e) => toggle(c.id, e.target.checked)} /> {c.name} <span className="sub-inline">({c.item_count})</span></label></li>
            ))}
          </ul>
          <label className="block">New collection (optional)<input value={newName} maxLength={100} onChange={(e) => setNewName(e.target.value)} placeholder="e.g. Plaque: to discuss on Friday" /></label>
        </fieldset>
        <TagInput label="Tags" tags={tags} onChange={setTags} placeholder="Add a tag and press Enter" />
        <StatusControl value={status} onChange={setStatus} label="Team status" />
        <label className="block">Note (optional)<textarea rows={2} maxLength={5000} value={note} onChange={(e) => setNote(e.target.value)} /></label>
        <p className="hint">Papers already in the library keep their status and note; the collections and tags are added to them.</p>
        <div className="actions">
          <button type="submit" className="primary">Save to library</button>
          <button type="button" onClick={onClose}>Cancel</button>
        </div>
      </form>
    </dialog>
  );
}
