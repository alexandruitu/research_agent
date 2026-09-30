import { useState, type FormEvent } from "react";
import { useNavigate, useParams, useSearchParams } from "react-router-dom";

import { ApiError } from "../api/client";
import { useArchiveField, useAssist, useField, useJob, usePreview, useSaveField, useSources, useTestCriteria } from "../api/hooks";
import { hasRole, type AssistResult, type FieldOut, type JobProgressData, type SourceOut } from "../api/types";
import { useAuth } from "../auth/AuthProvider";
import { Skeleton } from "../components/ui/Skeleton";
import { useToast } from "../components/ui/Toast";
import { CriteriaList } from "../features/fields/CriteriaList";
import { CriteriaTestPanel } from "../features/fields/CriteriaTestPanel";
import { FieldSidePanel } from "../features/fields/FieldSidePanel";
import {
  draftKeywords, draftOverrides, emptyForm, formFromVersion, hasKeywords, toBody, toDraft, validate, yearsOf, type FieldForm,
} from "../features/fields/fieldForm";
import { SOURCE_NAMES } from "../features/fields/labels";
import { SourcePicker } from "../features/fields/SourcePicker";
import { PreviewPanel } from "../features/fieldflow/PreviewPanel";
import { QueryPanel } from "../features/fieldflow/QueryPanel";
import { Stepper, type StepNumber } from "../features/fieldflow/Stepper";
import { Suggestions, GROUP_LABEL } from "../features/fieldflow/Suggestions";
import { SummaryCard } from "../features/fieldflow/SummaryCard";
import { TagInput } from "../features/fieldflow/TagInput";
import { useReportDirty } from "../features/settings/dirtyGuard";

const errorText = (error: unknown) => (error instanceof ApiError ? error.message : "Could not reach the server.");

export function FieldEditorPage() {
  const { fieldId } = useParams();
  const field = useField(fieldId ?? null);
  const sources = useSources();
  if ((fieldId && field.isLoading) || sources.isLoading) return <section><h1>{fieldId ? "Field" : "New field"}</h1><Skeleton label="the field" rows={6} /></section>;
  if (field.isError) return <p role="alert" className="form-error">{errorText(field.error)}</p>;
  if (sources.isError) return <p role="alert" className="form-error">{errorText(sources.error)}</p>;
  const data = fieldId ? (field.data ?? null) : null;
  // Keyed by version: a save or a reload puts the editor back on the saved text.
  return <FieldEditor key={data ? `${data.id}:${data.current_version}` : "new"} field={data} sources={sources.data ?? []} onReload={() => void field.refetch()} />;
}

/** Follows the assist job and hands its result up once it is done. */
function useAssistResult(jobId: string | null) {
  const job = useJob(jobId);
  const status = job.data?.status;
  const result = status === "done" ? (((job.data?.progress ?? {}) as JobProgressData).result as AssistResult | undefined) : undefined;
  return { result, pending: !!jobId && (!job.data || status === "queued" || status === "running"), failed: status === "failed" ? (job.data?.error ?? "no details were stored.") : null };
}

function FieldEditor({ field, sources, onReload }: { field: FieldOut | null; sources: SourceOut[]; onReload: () => void }) {
  const { user } = useAuth();
  const navigate = useNavigate();
  const toast = useToast();
  const [search, setSearch] = useSearchParams();
  const save = useSaveField();
  const archive = useArchiveField();
  const test = useTestCriteria();
  const assist = useAssist();
  const preview = usePreview();
  const current = field?.current ?? null;
  const archived = !!field?.archived_at;
  const member = hasRole(user, "member");
  const admin = hasRole(user, "admin");
  const canEdit = member && !archived;
  const enabled = new Set(sources.filter((s) => s.enabled).map((s) => s.name));
  const [initial] = useState<FieldForm>(() => (current ? formFromVersion(current) : emptyForm([...enabled])));
  const [form, setForm] = useState<FieldForm>(initial);
  const [errors, setErrors] = useState<string[]>([]);
  const [problem, setProblem] = useState<string | null>(null);
  const [stale, setStale] = useState<string | null>(null);
  const [testJob, setTestJob] = useState<string | null>(null);
  const [assistJob, setAssistJob] = useState<string | null>(null);
  const [previewJob, setPreviewJob] = useState<string | null>(null);
  const [assistProblem, setAssistProblem] = useState<string | null>(null);
  const [previewProblem, setPreviewProblem] = useState<string | null>(null);
  const assisted = useAssistResult(assistJob);
  const dirty = JSON.stringify(form) !== JSON.stringify(initial);
  useReportDirty(dirty && canEdit);
  const update = (patch: Partial<FieldForm>) => setForm((f) => ({ ...f, ...patch }));
  const legacy = !!current && current.include.length + current.exclude.length === 0 && current.legacy.length > 0;
  const nextVersion = (field?.current_version ?? 0) + 1;
  // demo mode lives in the URL, so it survives the remount after "Create field" and a reload
  const [demo, setDemoState] = useState(() => search.get("demo") === "1");
  const setDemo = (on: boolean) => {
    setDemoState(on); // at once: the router applies URL changes in a transition
    const params = new URLSearchParams(search);
    if (on) params.set("demo", "1");
    else params.delete("demo");
    setSearch(params, { replace: true });
  };
  const requested = Number(search.get("step"));
  const step: StepNumber = requested === 1 || requested === 2 || requested === 3 ? requested : field ? 2 : 1;
  const goTo = (next: StepNumber) => {
    const params = new URLSearchParams(search);
    params.set("step", String(next));
    setSearch(params, { replace: true });
    requestAnimationFrame(() => document.getElementById(`step-${next}-heading`)?.focus());
  };
  const done: Record<StepNumber, boolean> = {
    1: !!form.name.trim() && (!!form.description.trim() || !!form.topic.trim() || hasKeywords(form)),
    2: form.include.length + form.exclude.length > 0 && form.sources.length > 0,
    3: !!field && !dirty,
  };

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    const found = validate(form);
    setErrors(found);
    if (found.length > 0) return;
    setProblem(null);
    setStale(null);
    try {
      const saved = await save.mutateAsync({ fieldId: field?.id ?? null, baseVersion: field?.current_version ?? null, body: toBody(form) });
      toast.show({ text: field ? `Saved ${saved.name} as v${saved.current_version}` : `Created ${saved.name}` });
      if (!field) navigate(`/fields/${saved.id}?step=3${demo ? "&demo=1" : ""}`, { replace: true });
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

  const runAssist = async () => {
    setAssistProblem(null);
    try {
      const job = await assist.mutateAsync({ description: form.description.trim(), topic: form.topic.trim(), keywords: draftKeywords(form), mode: demo ? "demo" : "live" });
      setAssistJob(job.id);
    } catch (error) {
      setAssistProblem(errorText(error));
    }
  };

  const runPreview = async () => {
    setPreviewProblem(null);
    try {
      const job = await preview.mutateAsync({
        keywords: draftKeywords(form), query_override: draftOverrides(form), sources: form.sources.filter((s) => (SOURCE_NAMES as readonly string[]).includes(s)),
        years: yearsOf(form), mode: demo ? "demo" : "live",
      });
      setPreviewJob(job.id);
    } catch (error) {
      setPreviewProblem(error instanceof ApiError && error.code === "rate_limited" ? "Too many previews in a minute. Try again shortly." : errorText(error));
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
  const canPreview = hasKeywords(form) || !!draftOverrides(form);

  return (
    <section className="field-editor">
      <div className="page-head">
        <h1>{field ? `${field.name} (v${field.current_version ?? 1})` : "New field"}</h1>
        <div className="actions">
          {canEdit && <label className="check"><input type="checkbox" checked={demo} onChange={(e) => setDemo(e.target.checked)} /> Demo mode (offline stand-in: no model, no network)</label>}
          {admin && field && <button type="button" onClick={toggleArchive} disabled={archive.isPending}>{archived ? "Restore" : "Archive"}</button>}
        </div>
      </div>
      {archived && <p className="banner banner--warn">This field is archived: it cannot be edited, tested or run. {admin ? "Restore it to change it." : "An admin can restore it."}</p>}
      {!member && <p className="sub">Read-only: members and admins edit fields.</p>}
      <Stepper step={step} done={done} onStep={goTo} />
      <div className="editor-layout">
        <div>
          <form onSubmit={submit} aria-label="Field editor" className="field-form" noValidate>
            <fieldset className="plain" disabled={!canEdit}>
              {step === 1 && (
                <section className="step-panel" aria-labelledby="step-1-heading">
                  <h2 id="step-1-heading" tabIndex={-1}>1 · Describe the field</h2>
                  <p className="lede">Say what you are looking for as you would to a colleague. We suggest keywords and criteria from it; you choose what to keep.</p>
                  <label className="block">Name<input value={form.name} onChange={(e) => update({ name: e.target.value })} placeholder="e.g. AI plaque on coronary CT" /></label>
                  <label className="block">Description
                    <textarea rows={5} maxLength={2000} value={form.description} onChange={(e) => update({ description: e.target.value })}
                      placeholder="e.g. Deep learning methods that detect or characterise coronary plaque on CT angiography, validated on patient data." />
                  </label>
                  <span className="hint tnum counter" aria-live="off">{form.description.length}/2000 characters</span>
                  <details className="disclosure" open={legacy || !!form.topic || undefined}>
                    <summary>Topic line (optional)</summary>
                    <label className="block">Topic (context for screening; leave empty to use the first sentence above)<input value={form.topic} onChange={(e) => update({ topic: e.target.value })} /></label>
                  </details>
                  {canEdit && (
                    <div className="actions">
                      <button type="button" className="primary" onClick={runAssist} disabled={assist.isPending || assisted.pending}>
                        {assisted.pending ? "Suggesting…" : "Suggest keywords & criteria"}
                      </button>
                      <span className="hint">{demo ? "Demo: deterministic suggestions, no model." : "One small model call; cached."}</span>
                    </div>
                  )}
                  {assisted.pending && <Skeleton label="suggestions" rows={3} />}
                  {assistProblem && <p role="alert" className="form-error">{assistProblem}</p>}
                  {assisted.failed && <p role="alert" className="form-error">The suggestions failed: {assisted.failed}</p>}
                  {assisted.result && <Suggestions result={assisted.result} form={form} onChange={update} onDismiss={() => setAssistJob(null)} disabled={!canEdit} />}
                </section>
              )}
              {step === 2 && (
                <section className="step-panel" aria-labelledby="step-2-heading">
                  <h2 id="step-2-heading" tabIndex={-1}>2 · Keywords & criteria</h2>
                  {legacy && current && (
                    <p className="banner banner--warn">
                      This field uses the legacy topic match (“{current.legacy[0]?.text}”). Add inclusion or exclusion criteria to save v{nextVersion} with your own criteria.
                    </p>
                  )}
                  <p className="lede">Keywords decide what the search finds; criteria decide what the screen keeps.</p>
                  <div className="keyword-groups">
                    <TagInput tone="all" label={GROUP_LABEL.all} hint="Every one must appear." tags={form.keywords.all} disabled={!canEdit} onChange={(all) => update({ keywords: { ...form.keywords, all } })} placeholder="Type and press Enter" />
                    <TagInput tone="any" label={GROUP_LABEL.any} hint="Synonyms and alternatives." tags={form.keywords.any} disabled={!canEdit} onChange={(any) => update({ keywords: { ...form.keywords, any } })} placeholder="Type and press Enter" />
                    <TagInput tone="none" label={GROUP_LABEL.none} hint="Papers with these are left out." tags={form.keywords.none} disabled={!canEdit} onChange={(none) => update({ keywords: { ...form.keywords, none } })} placeholder="Type and press Enter" />
                  </div>
                  <CriteriaList kind="include" items={form.include} onChange={(include) => update({ include })} />
                  <CriteriaList kind="exclude" items={form.exclude} onChange={(exclude) => update({ exclude })} />
                  <SourcePicker sources={sources} chosen={form.sources} disabled={!canEdit} onToggle={toggleSource} />
                  <div className="two-up">
                    <fieldset>
                      <legend>Years</legend>
                      <div className="actions">
                        <label>From year <input inputMode="numeric" size={5} value={form.yearFrom} onChange={(e) => update({ yearFrom: e.target.value })} /></label>
                        <label>To year <input inputMode="numeric" size={5} value={form.yearTo} onChange={(e) => update({ yearTo: e.target.value })} /></label>
                      </div>
                      <span className="hint">Leave empty for no limit.</span>
                    </fieldset>
                  </div>
                  <QueryPanel form={form} onChange={update} disabled={!canEdit} />
                </section>
              )}
              {step === 3 && (
                <section className="step-panel" aria-labelledby="step-3-heading">
                  <h2 id="step-3-heading" tabIndex={-1}>3 · Preview & save</h2>
                  <p className="lede">A free look at what each source returns for these keywords. No model is called.</p>
                  {canEdit && (
                    <div className="actions">
                      <button type="button" onClick={runPreview} disabled={!canPreview || preview.isPending}>Preview search</button>
                      {!canPreview && <span className="hint">Add a keyword (step 2) to preview.</span>}
                    </div>
                  )}
                  {previewProblem && <p role="alert" className="form-error">{previewProblem}</p>}
                  {previewJob && <PreviewPanel key={previewJob} jobId={previewJob} />}
                  <h3>Test the criteria</h3>
                  {field ? (
                    canEdit && (
                      <div className="actions">
                        <button type="button" onClick={runTest} disabled={test.isPending}>Test criteria</button>
                        <span className="hint">Jev screens up to 20 papers with your unsaved criteria. Nothing is written to Papers.</span>
                      </div>
                    )
                  ) : (
                    <p className="sub">Save the field first to test its criteria.</p>
                  )}
                  {testJob && <CriteriaTestPanel key={testJob} jobId={testJob} />}
                </section>
              )}
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
            <div className="save-bar step-bar">
              <div className="step-nav">
                {step > 1 && <button type="button" onClick={() => goTo((step - 1) as StepNumber)}>← Back</button>}
                {step < 3 && <button type="button" onClick={() => goTo((step + 1) as StepNumber)}>Next →</button>}
              </div>
              {canEdit && (
                <>
                  <label className="note">Change note <input value={form.note} onChange={(e) => update({ note: e.target.value })} placeholder="What changed and why" /></label>
                  <button type="submit" className="primary" disabled={save.isPending}>{field ? `Save as v${nextVersion}` : "Create field"}</button>
                </>
              )}
            </div>
          </form>
        </div>
        <div className="editor-aside">
          <SummaryCard form={form} dirty={dirty} version={field?.current_version ?? null} />
          {field && <FieldSidePanel field={field} />}
        </div>
      </div>
    </section>
  );
}
