import { useState, type FormEvent } from "react";
import { useNavigate, useParams } from "react-router-dom";

import { ApiError } from "../api/client";
import { useArchiveField, useField, useSaveField, useSources, useTestCriteria } from "../api/hooks";
import { hasRole, type FieldOut, type SourceOut } from "../api/types";
import { useAuth } from "../auth/AuthProvider";
import { CriteriaList } from "../features/fields/CriteriaList";
import { CriteriaTestPanel } from "../features/fields/CriteriaTestPanel";
import { FieldSidePanel } from "../features/fields/FieldSidePanel";
import { emptyForm, formFromVersion, toBody, toDraft, validate, type FieldForm } from "../features/fields/fieldForm";
import { SOURCE_NAMES, sourceLabel } from "../features/fields/labels";

const errorText = (error: unknown) => (error instanceof ApiError ? error.message : "Could not reach the server.");

export function FieldEditorPage() {
  const { fieldId } = useParams();
  const field = useField(fieldId ?? null);
  const sources = useSources();
  if ((fieldId && field.isLoading) || sources.isLoading) return <p role="status">Loading…</p>;
  if (field.isError) return <p role="alert" className="form-error">{errorText(field.error)}</p>;
  if (sources.isError) return <p role="alert" className="form-error">{errorText(sources.error)}</p>;
  const data = fieldId ? (field.data ?? null) : null;
  // Keyed by version: a save or a reload puts the editor back on the saved text.
  return <FieldEditor key={data ? `${data.id}:${data.current_version}` : "new"} field={data} sources={sources.data ?? []} onReload={() => void field.refetch()} />;
}

function FieldEditor({ field, sources, onReload }: { field: FieldOut | null; sources: SourceOut[]; onReload: () => void }) {
  const { user } = useAuth();
  const navigate = useNavigate();
  const save = useSaveField();
  const archive = useArchiveField();
  const test = useTestCriteria();
  const current = field?.current ?? null;
  const archived = !!field?.archived_at;
  const member = hasRole(user, "member");
  const admin = hasRole(user, "admin");
  const canEdit = member && !archived;
  const enabled = new Set(sources.filter((s) => s.enabled).map((s) => s.name));
  const [form, setForm] = useState<FieldForm>(() => (current ? formFromVersion(current) : emptyForm([...enabled])));
  const [errors, setErrors] = useState<string[]>([]);
  const [problem, setProblem] = useState<string | null>(null);
  const [stale, setStale] = useState<string | null>(null);
  const [testJob, setTestJob] = useState<string | null>(null);
  const [demo, setDemo] = useState(false);
  const update = (patch: Partial<FieldForm>) => setForm((f) => ({ ...f, ...patch }));
  const legacy = !!current && current.include.length + current.exclude.length === 0 && current.legacy.length > 0;
  const nextVersion = (field?.current_version ?? 0) + 1;

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    const found = validate(form);
    setErrors(found);
    if (found.length > 0) return;
    setProblem(null);
    setStale(null);
    try {
      const saved = await save.mutateAsync({ fieldId: field?.id ?? null, baseVersion: field?.current_version ?? null, body: toBody(form) });
      if (!field) navigate(`/fields/${saved.id}`, { replace: true });
    } catch (error) {
      if (error instanceof ApiError && error.code === "stale_version") setStale(error.message);
      else setProblem(errorText(error));
    }
  };

  const runTest = async () => {
    const found = validate(form);
    setErrors(found);
    if (found.length > 0 || !field) return;
    setProblem(null);
    try {
      const job = await test.mutateAsync({ fieldId: field.id, draft: toDraft(form), mode: demo ? "demo" : "live" });
      setTestJob(job.id);
    } catch (error) {
      setProblem(errorText(error));
    }
  };

  const toggleArchive = async () => {
    if (!field) return;
    setProblem(null);
    try {
      await archive.mutateAsync({ fieldId: field.id, archive: !archived });
    } catch (error) {
      setProblem(errorText(error));
    }
  };

  const toggleSource = (name: string, on: boolean) =>
    update({ sources: on ? [...form.sources, name] : form.sources.filter((s) => s !== name) });

  return (
    <section>
      <div className="page-head">
        <h1>{field ? `${field.name} (v${field.current_version ?? 1})` : "New field"}</h1>
        {admin && field && <button type="button" onClick={toggleArchive} disabled={archive.isPending}>{archived ? "Restore" : "Archive"}</button>}
      </div>
      {archived && <p className="banner banner--warn">This field is archived: it cannot be edited, tested or run. {admin ? "Restore it to change it." : "An admin can restore it."}</p>}
      <div className={field ? "editor-layout" : undefined}>
        <div>
          <form onSubmit={submit} aria-label="Field editor" className="field-form" noValidate>
            <fieldset className="plain" disabled={!canEdit}>
              <label className="block">Name<input value={form.name} onChange={(e) => update({ name: e.target.value })} /></label>
              <label className="block">Topic (used for the search and as context for screening)<input value={form.topic} onChange={(e) => update({ topic: e.target.value })} /></label>
              {legacy && current && (
                <p className="banner banner--warn">
                  This field uses the legacy topic match (“{current.legacy[0]?.text}”). Add inclusion or exclusion criteria to save v{nextVersion} with your own criteria.
                </p>
              )}
              <CriteriaList kind="include" items={form.include} onChange={(include) => update({ include })} />
              <CriteriaList kind="exclude" items={form.exclude} onChange={(exclude) => update({ exclude })} />
              <fieldset>
                <legend>Sources</legend>
                {SOURCE_NAMES.map((name) => {
                  const on = enabled.has(name);
                  const checked = form.sources.includes(name);
                  return (
                    <label key={name} className="check source-choice">
                      <input type="checkbox" checked={checked} disabled={!on && !checked} onChange={(e) => toggleSource(name, e.target.checked)} />
                      {sourceLabel(name)}{on ? "" : " (disabled in Settings)"}
                    </label>
                  );
                })}
              </fieldset>
              <fieldset>
                <legend>Years</legend>
                <div className="actions">
                  <label>From year <input inputMode="numeric" value={form.yearFrom} onChange={(e) => update({ yearFrom: e.target.value })} /></label>
                  <label>To year <input inputMode="numeric" value={form.yearTo} onChange={(e) => update({ yearTo: e.target.value })} /></label>
                  <span className="sub">Leave empty for no limit.</span>
                </div>
              </fieldset>
              <label className="block">Change note<input value={form.note} onChange={(e) => update({ note: e.target.value })} /></label>
            </fieldset>
            {errors.length > 0 && (
              <div role="alert" className="form-error"><p>Fix these first:</p><ul>{errors.map((e) => <li key={e}>{e}</li>)}</ul></div>
            )}
            {stale && (
              <div role="alert" className="banner banner--warn">
                <p>{stale}</p>
                <button type="button" onClick={onReload}>Reload the latest version</button> <span className="sub">Reloading discards your unsaved edits.</span>
              </div>
            )}
            {problem && <p role="alert" className="form-error">{problem}</p>}
            {canEdit && (
              <div className="actions">
                <button type="submit" disabled={save.isPending}>{field ? `Save as v${nextVersion}` : "Create field"}</button>
                {field ? (
                  <>
                    <button type="button" onClick={runTest} disabled={test.isPending}>Test criteria</button>
                    <label className="check"><input type="checkbox" checked={demo} onChange={(e) => setDemo(e.target.checked)} /> Demo mode (offline stand-in for Jev)</label>
                  </>
                ) : (
                  <span className="sub">Save the field first to test its criteria.</span>
                )}
              </div>
            )}
          </form>
          {testJob && <CriteriaTestPanel key={testJob} jobId={testJob} />}
        </div>
        {field && <FieldSidePanel field={field} />}
      </div>
    </section>
  );
}
