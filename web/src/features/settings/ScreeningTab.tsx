import { useState } from "react";

import { useEvals } from "../../api/hooks";
import { hasRole, type ReviewSettingsOut, type ScreeningIO } from "../../api/types";
import { useAuth } from "../../auth/AuthProvider";
import type { Pair } from "../evals/metrics";
import { useReportDirty } from "./dirtyGuard";
import { bands, fromEvals, validateScreening, widthClass } from "./screening";
import { SettingsFrame } from "./SettingsFrame";
import { errorText, useSettingsSave } from "./useSettingsSave";

const fmt = (value: number) => (Number.isFinite(value) ? value.toFixed(2) : "?");

function Threshold({ label, hint, value, onChange }: { label: string; hint: string; value: number; onChange: (value: number) => void }) {
  const id = label.toLowerCase().replace(/[^a-z]+/g, "-");
  return (
    <div className="threshold">
      <label htmlFor={id} className="threshold-label">{label}</label>
      <input type="range" min={0} max={1} step={0.01} value={Number.isFinite(value) ? value : 0} aria-label={`${label} (slider)`} onChange={(e) => onChange(Number(e.target.value))} />
      <input id={id} type="number" min={0} max={1} step={0.01} value={Number.isFinite(value) ? value : ""} aria-describedby={`${id}-hint`} onChange={(e) => onChange(e.target.value === "" ? Number.NaN : Number(e.target.value))} />
      <p id={`${id}-hint`} className="hint">{hint}</p>
    </div>
  );
}

/** Three zones on the probability scale; the words next to it carry the meaning (not the colours). */
function Band({ low, high, lowWord, highWord }: { low: number; high: number; lowWord: string; highWord: string }) {
  const zones = bands(low, high);
  return (
    <>
      <div className="band" aria-hidden="true">
        {zones.low > 0 && <span className={`band-zone band-zone--${lowWord === "dropped" ? "drop" : "keep"} ${widthClass(zones.low)}`}>{lowWord}</span>}
        {zones.middle > 0 && <span className={`band-zone band-zone--ask ${widthClass(zones.middle)}`}>LLM</span>}
        {zones.high > 0 && <span className={`band-zone band-zone--${highWord === "dropped" ? "drop" : "keep"} ${widthClass(zones.high)}`}>{highWord}</span>}
      </div>
      <p className="band-words">
        Jev probability ≤ {fmt(low)}: {lowWord} by Jev · between: the LLM decides · ≥ {fmt(high)}: {highWord} by Jev.
      </p>
    </>
  );
}

function latestRecommendation(evals: ReturnType<typeof useEvals>["data"]): { pair: Pair; gold: string; when: string } | null {
  const found = [...(evals ?? [])].sort((a, b) => b.created_at.localeCompare(a.created_at)).find((e) => e.headline.recommended);
  const rec = found?.headline.recommended;
  return found && rec ? { pair: { include: rec.min_confidence, exclude: rec.exclude_min_confidence }, gold: found.gold_set.name, when: new Date(found.created_at).toLocaleDateString() } : null;
}

function EvalsHint({ admin, values, onApply }: { admin: boolean; values: ScreeningIO; onApply: (patch: Partial<ScreeningIO>) => void }) {
  const evals = useEvals();
  const rec = latestRecommendation(evals.data);
  if (evals.isLoading) return null;
  if (!rec) return <aside className="card evals-hint" aria-label="Evals recommendation"><h3>Evals recommendation</h3><p>No evaluation has recommended thresholds yet. Run an eval on a gold set to get one.</p></aside>;
  const mapped = fromEvals(rec.pair);
  const applied = mapped.keep_min === values.keep_min && mapped.include_fail_max === values.include_fail_max;
  return (
    <aside className="card evals-hint" aria-label="Evals recommendation">
      <h3>Evals recommends</h3>
      <p>Jev confidence {rec.pair.include} to keep and {rec.pair.exclude} to drop ({rec.gold}, {rec.when}).</p>
      <p>For inclusion criteria that is exactly: keep from <strong>{fmt(mapped.keep_min)}</strong>, drop at or below <strong>{fmt(mapped.include_fail_max)}</strong>.</p>
      <p className="hint">Measured on one gold set with a single topic criterion. Exclusion criteria have no measured recommendation, so their bands stay as you set them.</p>
      {applied ? <p className="hint">✓ Inclusion bands already match.</p> : admin && <button type="button" onClick={() => onApply(mapped)}>Apply to inclusion criteria</button>}
    </aside>
  );
}

function ScreeningForm({ data, admin, saver }: { data: ReviewSettingsOut; admin: boolean; saver: ReturnType<typeof useSettingsSave> }) {
  const saved = data.current.screening;
  const [values, setValues] = useState<ScreeningIO>(saved);
  const [errors, setErrors] = useState<string[]>([]);
  const dirty = JSON.stringify(values) !== JSON.stringify(saved);
  useReportDirty(dirty);
  const set = (patch: Partial<ScreeningIO>) => setValues((v) => ({ ...v, ...patch }));
  const onSave = async (note: string) => {
    const found = validateScreening(values);
    setErrors(found);
    return found.length === 0 && saver.save({ screening: values }, note);
  };
  return (
    <SettingsFrame
      id="screening" title="Screening" admin={admin} version={data.current.version} dirty={dirty} saving={saver.saving}
      intro="Jev scores every criterion of every paper with a probability. Confident scores decide on their own; everything in between goes to the LLM. Wider middle bands cost more LLM calls but lose fewer papers."
      onSave={onSave} onReset={() => setValues(data.defaults.screening)} stale={saver.stale} onReload={saver.reload} problem={saver.problem} message={saver.message} errors={errors}
    >
      <div className="screening-layout">
        <div className="bands">
          <fieldset>
            <legend>Inclusion criteria (the paper must meet each one)</legend>
            <Threshold label="Keep from" hint="At or above this, Jev counts the criterion as met." value={values.keep_min} onChange={(keep_min) => set({ keep_min })} />
            <Threshold label="Drop at or below" hint="At or below this, Jev drops the paper for failing the criterion. Keep it low: a lost paper is worse than an LLM call." value={values.include_fail_max} onChange={(include_fail_max) => set({ include_fail_max })} />
            <Band low={values.include_fail_max} high={values.keep_min} lowWord="dropped" highWord="kept" />
          </fieldset>
          <fieldset>
            <legend>Exclusion criteria (any one drops the paper)</legend>
            <Threshold label="Drop from" hint="At or above this, Jev drops the paper because the exclusion applies." value={values.exclude_hit_min} onChange={(exclude_hit_min) => set({ exclude_hit_min })} />
            <Threshold label="Clear at or below" hint="At or below this, Jev counts the exclusion as not applying." value={values.exclude_clear_max} onChange={(exclude_clear_max) => set({ exclude_clear_max })} />
            <Band low={values.exclude_clear_max} high={values.exclude_hit_min} lowWord="cleared" highWord="dropped" />
          </fieldset>
        </div>
        <EvalsHint admin={admin} values={values} onApply={set} />
      </div>
    </SettingsFrame>
  );
}

export function ScreeningTab() {
  const { user } = useAuth();
  const saver = useSettingsSave();
  const { settings } = saver;
  if (settings.isLoading) return <p role="status">Loading…</p>;
  if (settings.isError || !settings.data) return <p role="alert" className="form-error">{errorText(settings.error)}</p>;
  return <ScreeningForm key={settings.data.current.version} data={settings.data} admin={hasRole(user, "admin")} saver={saver} />;
}
