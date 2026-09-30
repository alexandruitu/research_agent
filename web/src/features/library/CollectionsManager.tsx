import { useState } from "react";

import { ApiError } from "../../api/client";
import { useArchiveCollection, useCollections, useCreateCollection, usePatchCollection } from "../../api/hooks";
import type { CollectionOut } from "../../api/types";
import { useToast } from "../../components/ui/Toast";

const errorText = (error: unknown, name?: string) =>
  error instanceof ApiError && error.code === "name_taken" ? `A collection called “${name}” exists already.` : error instanceof ApiError ? error.message : "Could not reach the server.";

function Row({ collection, admin, member }: { collection: CollectionOut; admin: boolean; member: boolean }) {
  const [editing, setEditing] = useState(false);
  const [name, setName] = useState(collection.name);
  const patch = usePatchCollection();
  const archive = useArchiveCollection();
  const toast = useToast();
  const [problem, setProblem] = useState<string | null>(null);
  const rename = async () => {
    setProblem(null);
    try {
      await patch.mutateAsync({ id: collection.id, name: name.trim() });
      setEditing(false);
      toast.show({ text: `Renamed to ${name.trim()}` });
    } catch (error) {
      setProblem(errorText(error, name.trim()));
    }
  };
  const toggle = async () => {
    const archiving = !collection.archived_at;
    if (archiving && !window.confirm(`Archive “${collection.name}”? Its papers stay in the library; the collection is hidden from pickers.`)) return;
    try {
      await archive.mutateAsync({ id: collection.id, archive: archiving });
      toast.show({ text: archiving ? `Archived ${collection.name}` : `Restored ${collection.name}` });
    } catch (error) {
      toast.show({ tone: "bad", text: errorText(error) });
    }
  };
  return (
    <li className="collection-row">
      {editing ? (
        <form className="inline" onSubmit={(e) => { e.preventDefault(); void rename(); }}>
          <label>Name of {collection.name} <input value={name} maxLength={100} onChange={(e) => setName(e.target.value)} /></label>
          <button type="submit" className="primary" disabled={!name.trim() || patch.isPending}>Save</button>
          <button type="button" onClick={() => { setEditing(false); setName(collection.name); }}>Cancel</button>
        </form>
      ) : (
        <>
          <span className="collection-name">{collection.name}</span>
          <span className="sub-inline">{collection.item_count} paper{collection.item_count === 1 ? "" : "s"}{collection.archived_at ? " · archived" : ""}</span>
          <span className="row-tools">
            {member && !collection.archived_at && <button type="button" onClick={() => setEditing(true)}>Rename{" "}<span className="sr-only">{collection.name}</span></button>}
            {admin && <button type="button" onClick={toggle}>{collection.archived_at ? "Restore" : "Archive"}{" "}<span className="sr-only">{collection.name}</span></button>}
          </span>
        </>
      )}
      {problem && <p role="alert" className="form-error">{problem}</p>}
    </li>
  );
}

/** Create and rename collections (members), archive and restore them (admins). */
export function CollectionsManager({ admin, member }: { admin: boolean; member: boolean }) {
  const [archived, setArchived] = useState(false);
  const collections = useCollections(archived);
  const create = useCreateCollection();
  const toast = useToast();
  const [name, setName] = useState("");
  const [problem, setProblem] = useState<string | null>(null);
  const add = async () => {
    setProblem(null);
    try {
      await create.mutateAsync({ name: name.trim() });
      toast.show({ text: `Created ${name.trim()}` });
      setName("");
    } catch (error) {
      setProblem(errorText(error, name.trim()));
    }
  };
  return (
    <section aria-labelledby="collections-title" className="collections-manager">
      <h2 id="collections-title">Collections</h2>
      <label className="check"><input type="checkbox" checked={archived} onChange={(e) => setArchived(e.target.checked)} /> Show archived collections</label>
      {collections.isLoading ? <p className="sub">Loading…</p> : (collections.data ?? []).length === 0 ? <p className="hint">No collections yet.</p> : (
        <ul className="collection-list">
          {(collections.data ?? []).map((c) => <Row key={`${c.id}:${c.name}`} collection={c} admin={admin} member={member} />)}
        </ul>
      )}
      {member && (
        <form className="inline" onSubmit={(e) => { e.preventDefault(); if (name.trim()) void add(); }}>
          <label>New collection <input value={name} maxLength={100} onChange={(e) => setName(e.target.value)} /></label>
          <button type="submit" disabled={!name.trim() || create.isPending}>Create collection</button>
        </form>
      )}
      {problem && <p role="alert" className="form-error">{problem}</p>}
    </section>
  );
}
