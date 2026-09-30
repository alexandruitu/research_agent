import { useState, type FormEvent } from "react";

import { ApiError } from "../../api/client";
import { useCollections, useCreateCollection } from "../../api/hooks";
import type { CollectionRef } from "../../api/types";

type Props = { value: CollectionRef[]; onChange: (ids: string[]) => void; disabled?: boolean; legend?: string };

/** Pick collections by checkbox; a new one can be created on the spot and is picked at once. */
export function CollectionsEditor({ value, onChange, disabled = false, legend = "Collections" }: Props) {
  const collections = useCollections();
  const create = useCreateCollection();
  const [name, setName] = useState("");
  const [problem, setProblem] = useState<string | null>(null);
  const chosen = new Set(value.map((c) => c.id));
  const all = [...(collections.data ?? [])];
  for (const c of value) if (!all.some((x) => x.id === c.id)) all.push({ ...c, description: "", archived_at: null, item_count: 0, created_by_name: null, created_at: "" });
  const toggle = (id: string, on: boolean) => onChange(on ? [...chosen, id] : [...chosen].filter((c) => c !== id));
  const add = async (event?: FormEvent) => {
    event?.preventDefault();
    if (!name.trim()) return;
    setProblem(null);
    try {
      const made = await create.mutateAsync({ name: name.trim() });
      setName("");
      onChange([...chosen, made.id]);
    } catch (error) {
      setProblem(error instanceof ApiError && error.code === "name_taken" ? `A collection called “${name.trim()}” exists already: tick it above.` : error instanceof ApiError ? error.message : "Could not create the collection.");
    }
  };
  return (
    <fieldset className="collections-editor" disabled={disabled}>
      <legend>{legend}</legend>
      {all.length === 0 ? <p className="hint">No collections yet: name the first one below.</p> : (
        <ul className="check-list">
          {all.map((c) => (
            <li key={c.id}><label className="check"><input type="checkbox" checked={chosen.has(c.id)} onChange={(e) => toggle(c.id, e.target.checked)} /> {c.name}</label></li>
          ))}
        </ul>
      )}
      <div className="inline-add">
        <label className="sr-only" htmlFor="new-collection-name">New collection name</label>
        <input id="new-collection-name" value={name} maxLength={100} placeholder="New collection" onChange={(e) => setName(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); void add(); } }} />
        <button type="button" onClick={() => void add()} disabled={!name.trim() || create.isPending}>Create</button>
      </div>
      {problem && <p role="alert" className="form-error">{problem}</p>}
    </fieldset>
  );
}
