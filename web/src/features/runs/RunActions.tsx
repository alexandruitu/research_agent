import { useState, type FormEvent, type ReactNode } from "react";
import { useNavigate } from "react-router-dom";

import { ApiError } from "../../api/client";
import { isActive, runExportUrl, useCancelRun, useDeleteRuns, usePatchRun, useRerun, useResumeRun } from "../../api/hooks";
import { hasRole, type RunOut } from "../../api/types";
import { useAuth } from "../../auth/AuthProvider";
import { ConfirmDialog } from "../../components/ui/ConfirmDialog";
import type { MenuItem } from "../../components/ui/MenuButton";
import { useToast } from "../../components/ui/Toast";
import { canManageRun, runLabel } from "./runWords";

/** Starts a file download from a same-origin API URL (the session cookie goes with it). */
export function download(url: string) {
  const link = document.createElement("a");
  link.href = url;
  link.download = "";
  document.body.appendChild(link);
  link.click();
  link.remove();
}

type Pending = { kind: "cancel" | "delete"; runs: RunOut[] } | { kind: "rename"; run: RunOut } | null;

const message = (error: unknown) => (error instanceof ApiError ? error.message : "Could not reach the server.");

/**
 * Every action on a run, as menu items, with the dialogs they need (confirm cancel/delete, rename) and toasts.
 * Who may do what: viewers open and export; members also run again; the run's creator or an admin also
 * resumes, cancels, renames, pins and deletes.
 */
export function useRunActions({ onDeleted }: { onDeleted?: (ids: string[]) => void } = {}) {
  const { user } = useAuth();
  const navigate = useNavigate();
  const toast = useToast();
  const rerun = useRerun();
  const resume = useResumeRun();
  const cancel = useCancelRun();
  const patch = usePatchRun();
  const remove = useDeleteRuns();
  const [pending, setPending] = useState<Pending>(null);
  const member = hasRole(user, "member");

  const runAgain = async (run: RunOut, config: "same" | "current") => {
    try {
      const started = await rerun.mutateAsync({ runId: run.id, config });
      toast.show({
        text: config === "same" ? `Started again with the same configuration: ${runLabel(run)}.` : `Started again with current settings: ${runLabel(run)}.`,
        action: { label: "Open", run: () => navigate(`/runs/${started.run_id}`) },
      });
    } catch (error) {
      toast.show({ tone: "bad", text: message(error) });
    }
  };

  const doResume = async (run: RunOut) => {
    try {
      await resume.mutateAsync(run.id);
      toast.show({ text: `Resuming ${runLabel(run)} from its checkpoint.` });
    } catch (error) {
      if (error instanceof ApiError && error.code === "prompt_version_changed") {
        toast.show({ tone: "bad", text: error.message, action: { label: "Run again (same configuration)", run: () => void runAgain(run, "same") } });
      } else {
        toast.show({ tone: "bad", text: message(error) });
      }
    }
  };

  const togglePin = async (run: RunOut) => {
    try {
      await patch.mutateAsync({ runId: run.id, patch: { pinned: !run.pinned } });
      toast.show({ text: run.pinned ? `Unpinned ${runLabel(run)}.` : `Pinned ${runLabel(run)} to the top.` });
    } catch (error) {
      toast.show({ tone: "bad", text: message(error) });
    }
  };

  const confirmCancel = async (runs: RunOut[]) => {
    for (const run of runs) {
      try {
        const out = await cancel.mutateAsync(run.id);
        toast.show({ text: out.status === "cancelled" ? `Cancelled ${runLabel(run)}.` : `Stopping ${runLabel(run)}; its checkpoint is kept.` });
      } catch (error) {
        toast.show({ tone: "bad", text: message(error) });
      }
    }
    setPending(null);
  };

  const confirmDelete = async (runs: RunOut[]) => {
    try {
      const out = await remove.mutateAsync(runs.map((r) => r.id));
      if (out.deleted.length) toast.show({ text: out.deleted.length === 1 ? `Deleted ${runLabel(runs.find((r) => r.id === out.deleted[0]) ?? runs[0]!)}; its folder is in the trash.` : `Deleted ${out.deleted.length} runs; their folders are in the trash.` });
      for (const refusal of out.refused) toast.show({ tone: "bad", text: `${runLabel(runs.find((r) => r.id === refusal.id) ?? runs[0]!)}: ${refusal.message}` });
      onDeleted?.(out.deleted);
    } catch (error) {
      toast.show({ tone: "bad", text: message(error) });
    }
    setPending(null);
  };

  const items = (run: RunOut, { open = true }: { open?: boolean } = {}): MenuItem[] => {
    const manage = canManageRun(user, run);
    const research = run.kind === "research";
    const list: MenuItem[] = [];
    if (open) list.push({ label: "Open", onSelect: () => navigate(`/runs/${run.id}`) });
    if (member && research) {
      list.push({ label: "Run again (same configuration)", onSelect: () => void runAgain(run, "same") });
      list.push({ label: "Run again with current settings", onSelect: () => void runAgain(run, "current") });
    }
    if (manage && research && ["failed", "cancelled"].includes(run.status)) list.push({ label: "Resume", onSelect: () => void doResume(run) });
    if (manage && research && isActive(run.status)) list.push({ label: "Cancel run…", onSelect: () => setPending({ kind: "cancel", runs: [run] }), danger: true });
    list.push({ label: "Export CSV", onSelect: () => download(runExportUrl(run.id, "csv")) });
    list.push({ label: "Export bundle (zip)", onSelect: () => download(runExportUrl(run.id, "bundle")) });
    if (manage) {
      list.push({ label: "Rename or add a note…", onSelect: () => setPending({ kind: "rename", run }) });
      list.push({ label: run.pinned ? "Unpin" : "Pin to top", onSelect: () => void togglePin(run) });
    }
    if (manage && research) list.push({ label: "Delete…", onSelect: () => setPending({ kind: "delete", runs: [run] }), danger: true, disabled: isActive(run.status) });
    return list;
  };

  let dialog: ReactNode = null;
  if (pending?.kind === "delete") {
    const n = pending.runs.length;
    dialog = (
      <ConfirmDialog title={n === 1 ? `Delete ${runLabel(pending.runs[0]!)}?` : `Delete ${n} runs?`} confirmLabel={n === 1 ? "Delete run" : `Delete ${n} runs`}
        busy={remove.isPending} onCancel={() => setPending(null)} onConfirm={() => void confirmDelete(pending.runs)}>
        <p>The run's screenings, reviews and rankings are removed from the database. Library items saved from it keep their evidence snapshot. The run folder moves to the trash on the server; nothing is erased from disk.</p>
      </ConfirmDialog>
    );
  } else if (pending?.kind === "cancel") {
    dialog = (
      <ConfirmDialog title={`Cancel ${runLabel(pending.runs[0]!)}?`} confirmLabel="Cancel run" busy={cancel.isPending}
        onCancel={() => setPending(null)} onConfirm={() => void confirmCancel(pending.runs)}>
        <p>A queued run never starts. A running one stops at the worker's next check; its checkpoint is kept and you can resume it later.</p>
      </ConfirmDialog>
    );
  } else if (pending?.kind === "rename") {
    dialog = <RenameDialog run={pending.run} onClose={() => setPending(null)} />;
  }

  return { items, dialog, askDelete: (runs: RunOut[]) => setPending({ kind: "delete", runs }), canManage: (run: RunOut) => canManageRun(user, run) };
}

function RenameDialog({ run, onClose }: { run: RunOut; onClose: () => void }) {
  const patch = usePatchRun();
  const toast = useToast();
  const [name, setName] = useState(run.name ?? "");
  const [note, setNote] = useState(run.note ?? "");
  const [problem, setProblem] = useState<string | null>(null);
  const submit = async (event: FormEvent) => {
    event.preventDefault();
    try {
      await patch.mutateAsync({ runId: run.id, patch: { name, note } });
      toast.show({ text: "Saved the name and note." });
      onClose();
    } catch (error) {
      setProblem(message(error));
    }
  };
  return (
    <div className="confirm-backdrop">
      <form role="dialog" aria-modal="true" aria-label="Rename run" className="confirm confirm--plain" onSubmit={submit}
        onKeyDown={(event) => event.key === "Escape" && onClose()}>
        <h2>Name and note</h2>
        <label className="stack">Name <span className="hint">blank: show the field and version</span>
          <input value={name} maxLength={200} autoFocus onChange={(e) => setName(e.target.value)} placeholder={runLabel({ ...run, name: null })} />
        </label>
        <label className="stack">Note
          <textarea value={note} maxLength={5000} rows={4} onChange={(e) => setNote(e.target.value)} />
        </label>
        {problem && <p role="alert" className="form-error">{problem}</p>}
        <div className="confirm__actions">
          <button type="button" onClick={onClose}>Cancel</button>
          <button type="submit" className="primary" disabled={patch.isPending}>Save</button>
        </div>
      </form>
    </div>
  );
}
