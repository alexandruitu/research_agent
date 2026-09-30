import { useEffect, useRef, useState, type RefObject } from "react";
import { Link } from "react-router-dom";

import { ApiError } from "../../api/client";
import { useDeleteLibraryItems, useLibraryItem, usePatchLibraryItem, useRuns, useSnapshotItem } from "../../api/hooks";
import { isTypingTarget } from "../../components/ui/shortcuts";
import { hasRole, type LibraryEventOut, type LibraryItemDetail } from "../../api/types";
import { useAuth } from "../../auth/AuthProvider";
import { Skeleton } from "../../components/ui/Skeleton";
import { statusMeta } from "../../components/ui/StatusMark";
import { useToast } from "../../components/ui/Toast";
import { TagInput } from "../fieldflow/TagInput";
import { shortDate } from "../fields/labels";
import { CollectionsEditor } from "./CollectionsEditor";
import { useStatusChange } from "./optimistic";
import { SnapshotView } from "./SnapshotView";
import { StatusControl } from "./StatusControl";

const errorText = (error: unknown) => (error instanceof ApiError ? error.message : "Could not reach the server.");
const list = (value: unknown) => (Array.isArray(value) && value.length ? value.join(", ") : null);

/** One history event in words. */
export function eventSentence(event: LibraryEventOut): string {
  const d = event.detail as Record<string, unknown>;
  const who = event.user_name ?? "Someone";
  switch (event.kind) {
    case "added": return `${who} saved it${list(d.collections) ? ` to ${list(d.collections)}` : ""} as ${statusMeta(String(d.status ?? "to_read")).word.toLowerCase()}.`;
    case "resaved": return `${who} saved it again${list(d.collections_added) ? `, adding ${list(d.collections_added)}` : ""}${list(d.tags_added) ? `, tags ${list(d.tags_added)}` : ""}.`;
    case "status": return `${who} changed the status from ${statusMeta(String(d.from)).word.toLowerCase()} to ${statusMeta(String(d.to)).word.toLowerCase()}.`;
    case "note": return `${who} ${d.to ? "edited the note" : "cleared the note"}.`;
    case "tags": return `${who} ${[list(d.added) && `added tags ${list(d.added)}`, list(d.removed) && `removed tags ${list(d.removed)}`].filter(Boolean).join(" and ")}.`;
    case "collections": return `${who} ${[list(d.added) && `added it to ${list(d.added)}`, list(d.removed) && `removed it from ${list(d.removed)}`].filter(Boolean).join(" and ")}.`;
    case "snapshot": return `${who} updated the evidence from a newer run.`;
    default: return `${who}: ${event.kind}.`;
  }
}

function NoteEditor({ item, canEdit }: { item: LibraryItemDetail; canEdit: boolean }) {
  const patch = usePatchLibraryItem();
  const toast = useToast();
  const [note, setNote] = useState(item.note);
  const changed = note !== item.note;
  const save = async () => {
    try {
      await patch.mutateAsync({ id: item.id, note });
      toast.show({ text: "Note saved" });
    } catch (error) {
      toast.show({ tone: "bad", text: errorText(error) });
    }
  };
  return (
    <div className="note-editor">
      <label className="block">Note
        <textarea rows={4} maxLength={5000} value={note} disabled={!canEdit} onChange={(e) => setNote(e.target.value)} placeholder={canEdit ? "Why it matters, what to check, who should read it" : "No note."} />
      </label>
      {canEdit && (
        <div className="actions">
          <button type="button" onClick={save} disabled={!changed || patch.isPending}>Save note</button>
          {changed && <span className="hint">Unsaved note.</span>}
        </div>
      )}
    </div>
  );
}

/** The newest finished run of the item's field, when it is newer than the one the evidence came from. */
function useNewerRun(item: LibraryItemDetail) {
  const runs = useRuns();
  const fromRun = (item.snapshot as { run?: { created_at?: string } }).run?.created_at ?? null;
  const candidates = (runs.data ?? [])
    .filter((r) => r.field_id === item.field?.id && r.status === "done" && r.id !== item.run_id && (!fromRun || r.created_at > fromRun))
    .sort((a, b) => b.created_at.localeCompare(a.created_at));
  return candidates[0] ?? null;
}

type Props = { itemId: string; onClose: () => void; statusRef?: RefObject<HTMLDivElement> };

export function ReadingPane({ itemId, onClose, statusRef }: Props) {
  const { user } = useAuth();
  const canEdit = hasRole(user, "member");
  const item = useLibraryItem(itemId);
  const patch = usePatchLibraryItem();
  const remove = useDeleteLibraryItems();
  const snapshot = useSnapshotItem();
  const status = useStatusChange();
  const toast = useToast();
  const [tab, setTab] = useState<"overview" | "evidence" | "history">("overview");
  const heading = useRef<HTMLHeadingElement>(null);
  useEffect(() => {
    heading.current?.focus();
  }, [itemId]);
  const data = item.data;
  const newer = useNewerRunSafe(data);

  const update = async (body: { tags?: string[]; collection_ids?: string[] }, message: string) => {
    if (!data) return;
    try {
      await patch.mutateAsync({ id: data.id, ...body });
      toast.show({ text: message });
    } catch (error) {
      toast.show({ tone: "bad", text: errorText(error) });
    }
  };
  const del = async () => {
    if (!data || !window.confirm(`Remove “${data.paper.title}” from the library? Its note, tags and history are deleted too.`)) return;
    try {
      await remove.mutateAsync([data.id]);
      toast.show({ text: "Removed from the library" });
      onClose();
    } catch (error) {
      toast.show({ tone: "bad", text: errorText(error) });
    }
  };
  const refresh = async (runId: string) => {
    if (!data) return;
    try {
      await snapshot.mutateAsync({ id: data.id, runId });
      toast.show({ text: "Evidence updated from the newer run" });
    } catch (error) {
      toast.show({ tone: "bad", text: error instanceof ApiError && error.code === "not_in_run" ? "This paper is not in the newer run, so its evidence stays as saved." : errorText(error) });
    }
  };

  return (
    <aside aria-label="Reading pane" className="reading-pane" onKeyDown={(event) => event.key === "Escape" && !isTypingTarget(event.target) && onClose()}>
      <div className="pane-head">
        <div className="pane-title">
          <h2 ref={heading} tabIndex={-1}>{data ? data.paper.title : "Loading…"}</h2>
          <button type="button" onClick={onClose} aria-label="Close reading pane">×</button>
        </div>
        {data && (
          <div className="pane-tools" ref={statusRef}>
            <StatusControl value={data.status} disabled={!canEdit} onChange={(to) => void status.change(data.id, data.status, to)} />
            {data.can_delete && <button type="button" className="danger-quiet" onClick={del}>Remove from library</button>}
          </div>
        )}
      </div>
      {item.isLoading && <Skeleton label="the paper" rows={6} />}
      {item.isError && <p role="alert" className="form-error">{errorText(item.error)}</p>}
      {data && (
        <div className="pane-body">
          <p className="pane-meta">
            {[data.paper.year, data.paper.source_id, data.paper.doi && `doi ${data.paper.doi}`].filter(Boolean).join(" · ")}
            <br />
            Saved by {data.added_by_name ?? "unknown"} on {shortDate(data.added_at)}{data.field ? ` from ${data.field.name}${data.field.version ? ` v${data.field.version}` : ""}` : ""}
            {data.run_id && <> · <Link to={`/?run=${data.run_id}&paper=${data.paper.id}`}>open in its run</Link></>}
          </p>
          <div role="group" aria-label="Reading pane sections" className="sections">
            <button type="button" aria-pressed={tab === "overview"} onClick={() => setTab("overview")}>Overview</button>
            <button type="button" aria-pressed={tab === "evidence"} onClick={() => setTab("evidence")}>Evidence</button>
            <button type="button" aria-pressed={tab === "history"} onClick={() => setTab("history")}>History ({data.events.length})</button>
          </div>
          {tab === "overview" && (
            <>
              <section aria-label="Abstract" className="reading-text">{data.abstract || <span className="sub">No abstract available.</span>}</section>
              <div className="pane-grid">
                <CollectionsEditor value={data.collections} disabled={!canEdit} onChange={(ids) => void update({ collection_ids: ids }, "Collections updated")} />
                <TagInput label="Tags" tags={data.tags} disabled={!canEdit} onChange={(tags) => void update({ tags }, "Tags updated")} placeholder={canEdit ? "Add a tag and press Enter" : undefined} />
              </div>
              <NoteEditor key={data.updated_at} item={data} canEdit={canEdit} />
              <section aria-labelledby="files-title">
                <h3 id="files-title">Files</h3>
                {data.files.length === 0 ? <p className="sub">No PDF uploaded. Upload one from the paper in its run.</p> : (
                  <ul className="file-list">
                    {data.files.map((f) => (
                      <li key={f.id}><span className="file-name">{f.filename}</span>{canEdit && <a href={`/api/v1/papers/${data.paper.id}/files/${f.id}`} download={f.filename}>Download{" "}<span className="sr-only">{f.filename}</span></a>}</li>
                    ))}
                  </ul>
                )}
              </section>
            </>
          )}
          {tab === "evidence" && (
            <>
              {newer && canEdit && (
                <div className="banner">
                  <p>A newer run of this field finished on {shortDate(newer.created_at)}.</p>
                  <button type="button" onClick={() => void refresh(newer.id)} disabled={snapshot.isPending}>Update evidence from the newer run</button>
                </div>
              )}
              <SnapshotView snapshot={data.snapshot} />
            </>
          )}
          {tab === "history" && (
            <ol className="history">
              {data.events.map((event) => (
                <li key={event.id}><span>{eventSentence(event)}</span> <time className="sub-inline" dateTime={event.created_at}>{new Date(event.created_at).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" })}</time></li>
              ))}
            </ol>
          )}
        </div>
      )}
    </aside>
  );
}

function useNewerRunSafe(item: LibraryItemDetail | undefined) {
  // hooks must not be conditional: an empty stand-in while the item loads
  const stand = item ?? ({ snapshot: {}, field: null, run_id: null } as unknown as LibraryItemDetail);
  return useNewerRun(stand);
}
