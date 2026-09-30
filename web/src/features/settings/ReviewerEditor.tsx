import { useState, type FormEvent } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import { ApiError } from "../../api/client";
import { useArchiveReviewer, useModelsAvailable, useReviewer, useReviewerVersion, useSaveReviewer } from "../../api/hooks";
import { hasRole, type AvailableModelOut, type ReviewerOut } from "../../api/types";
import { useAuth } from "../../auth/AuthProvider";
import { useReportDirty } from "./dirtyGuard";
import { modelOptions } from "./models";
import { diffReviewers } from "./reviewerDiff";
import {
  emptyForm, emptyItem, formFromContent, MAX_ITEMS, moveItem, preview, signature, SOURCE_FAMILIES, toBody, validateReviewer,
  type ItemForm, type RedFlagRule, type ReviewerForm, type SourceFamily, type Weight,
} from "./reviewerForm";
import { errorText } from "./useSettingsSave";

const WEIGHTS: { value: Weight; word: string }[] = [{ value: 1, word: "low" }, { value: 2, word: "normal" }, { value: 3, word: "high" }];
const FAMILY_LABEL: Record<SourceFamily, string> = { CLAIM: "CLAIM", "TRIPOD+AI": "TRIPOD+AI", other: "Other", none: "No source" };

function ItemEditor({ item, index, count, onChange, onMove, onRemove }: {
  item: ItemForm; index: number; count: number; onChange: (patch: Partial<ItemForm>) => void; onMove: (by: -1 | 1) => void; onRemove: () => void;
}) {
  const name = `Item ${index + 1}`;
  const id = item.uid;
  return (
    <li className="item-card">
      <div className="item-head">
        <strong>{name}</strong> <span className="sub">{item.key ?? "new"}</span>
        <span className="item-tools">
          <button type="button" aria-label={`Move ${name} up`} disabled={index === 0} onClick={() => onMove(-1)}>↑</button>
          <button type="button" aria-label={`Move ${name} down`} disabled={index === count - 1} onClick={() => onMove(1)}>↓</button>
          <button type="button" aria-label={`Remove ${name}`} onClick={onRemove}>Remove</button>
        </span>
      </div>
      <label className="block">Question for {name.toLowerCase()}{" "}<span className="sr-only">text</span>
        <textarea rows={2} maxLength={500} value={item.text} onChange={(e) => onChange({ text: e.target.value })} placeholder="A statement the reviewer answers yes, no, unclear or not reported" />
      </label>
      <div className="item-controls">
        <fieldset className="segmented">
          <legend>Weight <span className="sr-only">of {name.toLowerCase()}</span></legend>
          {WEIGHTS.map((w) => (
            <label key={w.value} className={item.weight === w.value ? "is-checked" : undefined}>
              <input type="radio" name={`${id}-weight`} value={w.value} checked={item.weight === w.value} onChange={() => onChange({ weight: w.value })} />
              {w.value} · {w.word}
            </label>
          ))}
        </fieldset>
        <label>A good answer is
          <select value={item.passIf} onChange={(e) => onChange({ passIf: e.target.value as "yes" | "no" })} aria-label={`A good answer for ${name.toLowerCase()}`}>
            <option value="yes">yes</option>
            <option value="no">no (the item is phrased negatively)</option>
          </select>
        </label>
        <label>Red flag if the answer is
          <select value={item.redFlagIf} onChange={(e) => onChange({ redFlagIf: e.target.value as RedFlagRule })} aria-label={`Red flag rule for ${name.toLowerCase()}`}>
            <option value="never">never a red flag</option>
            <option value="no">no</option>
            <option value="yes">yes</option>
          </select>
        </label>
        <label>Source
          <select value={item.family} onChange={(e) => onChange({ family: e.target.value as SourceFamily })} aria-label={`Source checklist for ${name.toLowerCase()}`}>
            {SOURCE_FAMILIES.map((f) => <option key={f} value={f}>{FAMILY_LABEL[f]}</option>)}
          </select>
        </label>
        {item.family !== "none" && (
          <label>{item.family === "other" ? "Reference" : "Item no."}
            <input className="ref-input" value={item.ref} maxLength={50} onChange={(e) => onChange({ ref: e.target.value })} aria-label={`Source reference for ${name.toLowerCase()}`} />
          </label>
        )}
      </div>
    </li>
  );
}

function ModelPreview({ form }: { form: ReviewerForm }) {
  const shown = preview(form);
  return (
    <aside className="model-preview" aria-labelledby="preview-heading">
      <h2 id="preview-heading">What the model reads</h2>
      <p className="hint">Live preview, updated as you type. The paper's text comes after it.</p>
      <div className="preview-body" aria-live="off">
        <p className="preview-label">Your perspective</p>
        <p>{shown.perspective || <span className="na">No perspective yet.</span>}</p>
        <p className="preview-label">Checklist: answer each with yes, no, unclear or not reported, and quote the sentence you relied on</p>
        {shown.items.length === 0 ? <p className="na">No items yet.</p> : (
          <ol className="preview-items">{shown.items.map((i) => <li key={i.key}><code>{i.key}</code> {i.text}</li>)}</ol>
        )}
      </div>
      <p className="hint"><strong>Not shown to the model:</strong> weights, what a good answer is and red-flag rules. Code applies them to the answers afterwards, so the model cannot game the score.</p>
    </aside>
  );
}

type EditorProps = {
  reviewer: ReviewerOut | null; models: AvailableModelOut[]; admin: boolean; message: string | null; onSaved: (message: string) => void; onReload: () => void;
};

function Editor({ reviewer, models, admin, message, onSaved, onReload }: EditorProps) {
  const navigate = useNavigate();
  const [historyOpen, setHistoryOpen] = useState(false);
  const save = useSaveReviewer();
  const archive = useArchiveReviewer();
  const archived = !!reviewer?.archived_at;
  const canEdit = admin && !archived;
  const [initial] = useState(() => (reviewer ? formFromContent(reviewer.current) : emptyForm()));
  const [form, setForm] = useState<ReviewerForm>(initial);
  const [note, setNote] = useState("");
  const [errors, setErrors] = useState<string[]>([]);
  const [problem, setProblem] = useState<string | null>(null);
  const [stale, setStale] = useState<string | null>(null);
  const dirty = signature(form) !== signature(initial);
  useReportDirty(dirty && canEdit);
  const update = (patch: Partial<ReviewerForm>) => setForm((f) => ({ ...f, ...patch }));
  const setItem = (index: number, patch: Partial<ItemForm>) => update({ items: form.items.map((it, i) => (i === index ? { ...it, ...patch } : it)) });
  const nextVersion = (reviewer?.current_version ?? 0) + 1;

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    const found = validateReviewer(form);
    setErrors(found);
    if (found.length > 0) return;
    setProblem(null);
    setStale(null);
    try {
      const saved = await save.mutateAsync({ key: reviewer?.key ?? null, baseVersion: reviewer?.current_version ?? null, body: toBody(form, note) });
      onSaved(`Saved as v${saved.current_version}.${saved.in_default_panel ? " The next run uses it." : " Turn it on in the default panel to use it in runs."}`);
      if (!reviewer) navigate(`/settings/reviewers/${saved.key}`, { replace: true });
    } catch (error) {
      if (error instanceof ApiError && error.code === "stale_version") setStale(error.message);
      else setProblem(errorText(error));
    }
  };
  const toggleArchive = async () => {
    if (!reviewer) return;
    setProblem(null);
    try {
      await archive.mutateAsync({ key: reviewer.key, archive: !archived });
    } catch (error) {
      setProblem(errorText(error));
    }
  };

  return (
    <section className="reviewer-editor">
      <p><Link to="/settings/reviewers">← All reviewers</Link></p>
      <div className="page-head">
        <h2>{reviewer ? `${reviewer.current.name} (v${reviewer.current_version})` : "New reviewer"}</h2>
        {reviewer && (
          <span className={`pill ${reviewer.in_default_panel ? "pill--measured" : ""}`}>{reviewer.in_default_panel ? "In the default panel · used by next run" : "Not in the default panel"}</span>
        )}
        {admin && reviewer && <button type="button" onClick={toggleArchive} disabled={archive.isPending}>{archived ? "Restore" : "Archive"}</button>}
      </div>
      {archived && <p className="banner banner--warn">This reviewer is archived: it cannot be edited or put in a panel. {admin ? "Restore it to change it." : "An admin can restore it."}</p>}
      {!admin && <p className="banner">Read-only: only admins change reviewers.</p>}
      <div className="editor-layout">
        <form onSubmit={submit} aria-label="Reviewer editor" className="field-form" noValidate>
          <fieldset className="plain" disabled={!canEdit}>
            <label className="block">Name<input value={form.name} maxLength={100} onChange={(e) => update({ name: e.target.value })} /></label>
            <label className="block">Perspective
              <textarea rows={4} maxLength={2000} value={form.perspective} aria-describedby="perspective-hint" onChange={(e) => update({ perspective: e.target.value })} />
            </label>
            <p id="perspective-hint" className="hint">Who this reviewer is and what they look for, in the second person (“You judge …”). The first sentence is shown on the card.</p>
            <label className="block">Model
              <select value={form.model ?? ""} onChange={(e) => update({ model: e.target.value || null })}>
                <option value="">Worker default</option>
                {modelOptions(models, form.model).map((o) => <option key={o.id} value={o.id}>{o.label}</option>)}
              </select>
            </label>
            <fieldset className="items">
              <legend>Checklist ({form.items.length} of {MAX_ITEMS})</legend>
              <p className="hint">Score = weighted share of answered items that pass. “Unclear” and “not reported” do not count against the paper; they lower coverage instead.</p>
              <ol className="item-list">
                {form.items.map((item, index) => (
                  <ItemEditor
                    key={item.uid} item={item} index={index} count={form.items.length}
                    onChange={(patch) => setItem(index, patch)} onMove={(by) => update({ items: moveItem(form.items, index, by) })}
                    onRemove={() => update({ items: form.items.filter((_, i) => i !== index) })}
                  />
                ))}
              </ol>
              <button type="button" disabled={form.items.length >= MAX_ITEMS} onClick={() => update({ items: [...form.items, emptyItem()] })}>Add item</button>
            </fieldset>
          </fieldset>
          {errors.length > 0 && <div role="alert" className="form-error"><p>Fix these first:</p><ul>{errors.map((e) => <li key={e}>{e}</li>)}</ul></div>}
          {stale && (
            <div role="alert" className="banner banner--warn">
              <p>{stale}</p>
              <button type="button" onClick={onReload}>Reload the latest version</button> <span className="sub">Reloading discards your unsaved edits.</span>
            </div>
          )}
          {problem && <p role="alert" className="form-error">{problem}</p>}
          {message && !dirty && <p role="status" className="banner banner--ok">{message}</p>}
          {canEdit && (
            <div className="save-bar">
              <label className="note">Change note <input value={note} onChange={(e) => setNote(e.target.value)} placeholder="What changed and why" /></label>
              <button type="submit" className="primary" disabled={save.isPending || (!!reviewer && !dirty)}>{reviewer ? `Save as v${nextVersion}` : "Create reviewer"}</button>
              {reviewer?.default && <button type="button" onClick={() => setForm(formFromContent(reviewer.default!))}>Reset to default</button>}
              <span className="sub" aria-live="polite">{dirty ? "Unsaved changes." : "No changes."}</span>
            </div>
          )}
        </form>
        <ModelPreview form={form} />
      </div>
      {reviewer?.versions && reviewer.versions.length > 0 && (
        <details className="versions-box" onToggle={(e) => setHistoryOpen(e.currentTarget.open)}>
          <summary>Version history ({reviewer.versions.length})</summary>
          <ul className="versions">
            {reviewer.versions.map((v) => (
              <li key={v.version}>
                <strong>v{v.version}</strong> · {v.item_count} items · {v.note || "no note"} · {v.created_by_name ?? "system"}, {new Date(v.created_at).toLocaleDateString()} · used by {v.run_count} run{v.run_count === 1 ? "" : "s"}
              </li>
            ))}
          </ul>
          {historyOpen && reviewer.versions.length > 1 && <ReviewerVersionDiff reviewerKey={reviewer.key} versions={reviewer.versions.map((v) => v.version)} />}
        </details>
      )}
    </section>
  );
}

function ReviewerVersionDiff({ reviewerKey, versions }: { reviewerKey: string; versions: number[] }) {
  const sorted = [...versions].sort((a, b) => b - a);
  const [from, setFrom] = useState(sorted[1] ?? sorted[0]!);
  const [to, setTo] = useState(sorted[0]!);
  const before = useReviewerVersion(reviewerKey, from);
  const after = useReviewerVersion(reviewerKey, to);
  const changes = before.data && after.data ? diffReviewers(before.data, after.data) : null;
  const options = sorted.map((v) => <option key={v} value={v}>v{v}</option>);
  return (
    <div className="diff">
      <h3>Compare versions</h3>
      <div className="actions">
        <label>Compare from <select value={from} onChange={(e) => setFrom(Number(e.target.value))}>{options}</select></label>
        <label>to <select value={to} onChange={(e) => setTo(Number(e.target.value))}>{options}</select></label>
      </div>
      {before.isError || after.isError ? <p role="alert" className="form-error">Could not load a version.</p>
        : !changes ? <p className="sub">Loading…</p>
        : changes.length === 0 ? <p>No differences.</p>
        : <ul className="diff-lines">{changes.map((c, i) => <li key={i}><span className={`diff-tag diff-tag--${c.kind}`}>{c.kind}</span> {c.text}</li>)}</ul>}
    </div>
  );
}

export function ReviewerEditorPage() {
  const { reviewerKey } = useParams();
  const { user } = useAuth();
  const reviewer = useReviewer(reviewerKey ?? null);
  const models = useModelsAvailable();
  const [message, setMessage] = useState<string | null>(null);
  if ((reviewerKey && reviewer.isLoading) || models.isLoading) return <p role="status">Loading…</p>;
  if (reviewer.isError) return <p role="alert" className="form-error">{errorText(reviewer.error)}</p>;
  const data = reviewerKey ? (reviewer.data ?? null) : null;
  // Keyed by version: a save or a reload puts the editor back on the saved content.
  return <Editor key={data ? `${data.key}:${data.current_version}:${data.archived_at ?? ""}` : "new"} reviewer={data} models={models.data?.models ?? []} admin={hasRole(user, "admin")} message={message} onSaved={setMessage} onReload={() => void reviewer.refetch()} />;
}
