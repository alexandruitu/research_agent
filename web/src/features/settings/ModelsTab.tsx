import { useState } from "react";

import { ApiError } from "../../api/client";
import { useModelsAvailable, useReviewers, useSaveReviewer, useWorkers } from "../../api/hooks";
import { hasRole, type AvailableModelOut, type ReviewerOut, type ReviewSettingsOut, type RoleModelsIO, type WorkerStatusOut } from "../../api/types";
import { useAuth } from "../../auth/AuthProvider";
import { useReportDirty } from "./dirtyGuard";
import { modelOptions, sharedFamily } from "./models";
import { withModel } from "./reviewerForm";
import { SettingsFrame } from "./SettingsFrame";
import { errorText, useSettingsSave } from "./useSettingsSave";

const ROLE_LABEL: Record<string, string> = {
  plan: "Plan", screen: "Screen", screen_criteria: "Screen (per criterion)", extract: "Extract",
  review_a: "Reviewer A", review_b: "Reviewer B", adjudicate: "Adjudicator", jev: "Jev",
};
const PIPELINE_ROLES: { key: keyof RoleModelsIO; label: string; does: string }[] = [
  { key: "plan", label: "Plan", does: "Turns the topic into search queries." },
  { key: "screen", label: "Screen", does: "Decides the papers Jev is unsure about (legacy topic match)." },
  { key: "screen_criteria", label: "Screen (per criterion)", does: "Answers each field criterion for the papers Jev is unsure about." },
  { key: "extract", label: "Extract", does: "Pulls claims with exact quotes from each kept paper." },
];

function ModelSelect({ label, value, models, onChange }: { label: string; value: string | null; models: AvailableModelOut[]; onChange: (value: string | null) => void }) {
  return (
    <select aria-label={`Model for ${label}`} value={value ?? ""} onChange={(e) => onChange(e.target.value || null)}>
      <option value="">Worker default</option>
      {modelOptions(models, value).map((o) => <option key={o.id} value={o.id}>{o.label}</option>)}
    </select>
  );
}

function keyText(worker: WorkerStatusOut): string {
  const detail = worker.detail ? `: ${worker.detail}` : "";
  if (!worker.key_present) return `✗ missing${detail || ": no key in the worker"}`;
  if (worker.key_accepted === true) return "✓ accepted";
  if (worker.key_accepted === false) return `✗ rejected${detail}`;
  return `present, not checked${detail}`;
}

function WorkerKeys() {
  const workers = useWorkers();
  if (workers.isLoading) return <p role="status">Loading…</p>;
  if (workers.isError) return <p role="alert" className="form-error">{workers.error instanceof ApiError ? workers.error.message : "Could not reach the server."}</p>;
  const rows = workers.data ?? [];
  return (
    <section aria-labelledby="keys-heading">
      <h3 id="keys-heading">Keys reported by the worker</h3>
      {rows.length === 0 ? (
        <p>No worker has reported yet. A worker checks its keys when it starts.</p>
      ) : (
        <table className="runs">
          <thead><tr><th scope="col">Role</th><th scope="col">Model</th><th scope="col">Key in worker</th><th scope="col">Checked</th></tr></thead>
          <tbody>
            {rows.map((worker) => (
              <tr key={`${worker.worker_id}:${worker.role}`}>
                <th scope="row">{ROLE_LABEL[worker.role] ?? worker.role}</th>
                <td>{worker.provider ?? "–"}{worker.model ? ` · ${worker.model}` : ""}</td>
                <td>{keyText(worker)}</td>
                <td>{new Date(worker.checked_at).toLocaleString()}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <p className="legend">Only whether a key is present and whether a test call accepted it. Key values never leave the worker. A model is offered above only when its provider's key was accepted.</p>
    </section>
  );
}

type State = { models: RoleModelsIO; editor: string | null; reviewers: Record<string, string | null> };

function ModelsForm({ data, panel, models, admin, saver }: { data: ReviewSettingsOut; panel: ReviewerOut[]; models: AvailableModelOut[]; admin: boolean; saver: ReturnType<typeof useSettingsSave> }) {
  const saveReviewer = useSaveReviewer();
  const saved: State = {
    models: data.current.models, editor: data.current.editor.model ?? null,
    reviewers: Object.fromEntries(panel.map((r) => [r.key, r.current.model])),
  };
  const [state, setState] = useState<State>(saved);
  const [problem, setProblem] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const changedReviewers = panel.filter((r) => (state.reviewers[r.key] ?? null) !== r.current.model);
  const settingsChanged = JSON.stringify({ m: state.models, e: state.editor }) !== JSON.stringify({ m: saved.models, e: saved.editor });
  const dirty = settingsChanged || changedReviewers.length > 0;
  useReportDirty(dirty);
  const family = sharedFamily(panel.map((r) => state.reviewers[r.key] ?? null));

  const onSave = async (note: string) => {
    setProblem(null);
    setMessage(null);
    try {
      for (const r of changedReviewers) {
        await saveReviewer.mutateAsync({ key: r.key, baseVersion: r.current_version, body: withModel(r.current, state.reviewers[r.key] ?? null, note.trim() || "model changed") });
      }
    } catch (error) {
      setProblem(errorText(error));
      return false;
    }
    if (settingsChanged) return saver.save({ models: state.models, editor: { ...data.current.editor, model: state.editor } }, note);
    setMessage(`Saved new versions of ${changedReviewers.map((r) => r.current.name).join(", ")}. The next run uses them.`);
    return true;
  };
  const reset = () => setState({ models: data.defaults.models, editor: data.defaults.editor.model ?? null, reviewers: Object.fromEntries(panel.map((r) => [r.key, r.default?.model ?? null])) });

  return (
    <SettingsFrame
      id="models" title="AI models" admin={admin} version={data.current.version} dirty={dirty} saving={saver.saving || saveReviewer.isPending}
      intro="Which model does each job. Only models whose provider key the worker accepted are offered; “Worker default” uses the model set in the worker's environment."
      onSave={onSave} onReset={reset} stale={saver.stale} onReload={saver.reload} problem={problem ?? saver.problem} message={message ?? saver.message}
      saveHint={changedReviewers.length > 0 ? `Saving also creates a new version of ${changedReviewers.map((r) => r.current.name).join(", ")}, because a reviewer's model belongs to the reviewer.` : undefined}
    >
      <table className="runs role-models">
        <caption className="sr-only">Model per role</caption>
        <thead><tr><th scope="col">Role</th><th scope="col">What it does</th><th scope="col">Model</th></tr></thead>
        <tbody>
          {PIPELINE_ROLES.map((role) => (
            <tr key={role.key}>
              <th scope="row">{role.label}</th>
              <td className="muted-cell">{role.does}</td>
              <td><ModelSelect label={role.label} value={state.models[role.key] ?? null} models={models} onChange={(value) => setState((s) => ({ ...s, models: { ...s.models, [role.key]: value } }))} /></td>
            </tr>
          ))}
          <tr className="group-row"><th scope="rowgroup" colSpan={3}>Peer-review panel</th></tr>
          {panel.map((r) => (
            <tr key={r.key}>
              <th scope="row">{r.current.name}</th>
              <td className="muted-cell">Reviewer: completes its {r.current.items.length}-item checklist.</td>
              <td><ModelSelect label={r.current.name} value={state.reviewers[r.key] ?? null} models={models} onChange={(value) => setState((s) => ({ ...s, reviewers: { ...s.reviewers, [r.key]: value } }))} /></td>
            </tr>
          ))}
          <tr>
            <th scope="row">Editor</th>
            <td className="muted-cell">Reads the reports, names disagreements and gives the final verdict.</td>
            <td><ModelSelect label="Editor" value={state.editor} models={models} onChange={(editor) => setState((s) => ({ ...s, editor }))} /></td>
          </tr>
        </tbody>
      </table>
      {family && (
        <p className="chip chip--warn family-warning" role="note">
          ⚠ All reviewers use one model family ({family}): their mistakes may agree. Independent reviewers are stronger with models from different providers.
        </p>
      )}
    </SettingsFrame>
  );
}

export function ModelsTab() {
  const { user } = useAuth();
  const saver = useSettingsSave();
  const reviewers = useReviewers();
  const available = useModelsAvailable();
  const { settings } = saver;
  const loading = settings.isLoading || reviewers.isLoading || available.isLoading;
  const error = settings.error ?? reviewers.error ?? available.error;
  let body;
  if (loading) body = <p role="status">Loading…</p>;
  else if (error || !settings.data) body = <p role="alert" className="form-error">{errorText(error)}</p>;
  else {
    const order = settings.data.current.default_panel;
    const panel = (reviewers.data ?? []).filter((r) => order.includes(r.key)).sort((a, b) => order.indexOf(a.key) - order.indexOf(b.key));
    const key = `${settings.data.current.version}:${panel.map((r) => `${r.key}${r.current_version}`).join(",")}`;
    body = <ModelsForm key={key} data={settings.data} panel={panel} models={available.data?.models ?? []} admin={hasRole(user, "admin")} saver={saver} />;
  }
  return (
    <>
      {body}
      <WorkerKeys />
    </>
  );
}
