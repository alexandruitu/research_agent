import { useState } from "react";
import { Link } from "react-router-dom";

import { useArchiveReviewer, useReviewers } from "../../api/hooks";
import { hasRole, type ReviewerOut, type ReviewSettingsOut } from "../../api/types";
import { useAuth } from "../../auth/AuthProvider";
import { useReportDirty } from "./dirtyGuard";
import { firstSentence } from "./reviewerForm";
import { SettingsFrame } from "./SettingsFrame";
import { errorText, useSettingsSave } from "./useSettingsSave";

export const PANEL_MIN = 1;
export const PANEL_MAX = 5;

function ReviewerCard({ reviewer, on, admin, canToggle, whyNot, onToggle }: {
  reviewer: ReviewerOut; on: boolean; admin: boolean; canToggle: boolean; whyNot: string | null; onToggle: (on: boolean) => void;
}) {
  const v = reviewer.current;
  const redFlags = v.items.filter((i) => i.red_flag_if).length;
  const id = `panel-${reviewer.key}`;
  return (
    <li className={`reviewer-card ${on ? "is-on" : ""}`}>
      <div className="reviewer-card-head">
        <h3><Link to={`/settings/reviewers/${reviewer.key}`}>{v.name}</Link></h3>
        <span className="sub">v{reviewer.current_version}</span>
      </div>
      <p className="reviewer-role">{firstSentence(v.perspective)}</p>
      <dl className="facts">
        <div><dt>Checklist</dt><dd>{v.items.length} item{v.items.length === 1 ? "" : "s"}{redFlags ? ` · ${redFlags} can raise a red flag` : ""}</dd></div>
        <div><dt>Model</dt><dd>{v.model ?? "worker default"}</dd></div>
      </dl>
      <label className="switch">
        <input type="checkbox" role="switch" checked={on} disabled={!admin || !canToggle} aria-describedby={whyNot ? `${id}-why` : undefined} onChange={(e) => onToggle(e.target.checked)} />
        <span className="switch-label">In the default panel{" "}<span className="sr-only">({v.name})</span></span>{" "}
        <span className="switch-state">{on ? "on" : "off"}</span>
      </label>
      {whyNot && <p id={`${id}-why`} className="hint">{whyNot}</p>}
    </li>
  );
}

function ArchivedList({ admin }: { admin: boolean }) {
  const all = useReviewers(true);
  const archive = useArchiveReviewer();
  const [problem, setProblem] = useState<string | null>(null);
  const archived = (all.data ?? []).filter((r) => r.archived_at);
  if (all.isLoading) return <p role="status">Loading…</p>;
  if (archived.length === 0) return <p className="hint">No archived reviewers.</p>;
  return (
    <>
      {problem && <p role="alert" className="form-error">{problem}</p>}
      <ul className="archived-list">
        {archived.map((r) => (
          <li key={r.key}>
            <Link to={`/settings/reviewers/${r.key}`}>{r.current.name}</Link> <span className="sub">archived {new Date(r.archived_at!).toLocaleDateString()}</span>{" "}
            {admin && (
              <button type="button" onClick={() => archive.mutateAsync({ key: r.key, archive: false }).catch((e) => setProblem(errorText(e)))}>
                Restore{" "}<span className="sr-only">{r.current.name}</span>
              </button>
            )}
          </li>
        ))}
      </ul>
    </>
  );
}

function PanelForm({ data, reviewers, admin, saver }: { data: ReviewSettingsOut; reviewers: ReviewerOut[]; admin: boolean; saver: ReturnType<typeof useSettingsSave> }) {
  const saved = { panel: data.current.default_panel, instructions: data.current.editor.instructions };
  const [panel, setPanel] = useState<string[]>(saved.panel);
  const [instructions, setInstructions] = useState(saved.instructions);
  const [showArchived, setShowArchived] = useState(false);
  const dirty = JSON.stringify(panel) !== JSON.stringify(saved.panel) || instructions !== saved.instructions;
  useReportDirty(dirty);
  const toggle = (key: string, on: boolean) => setPanel((p) => (on ? [...p, key] : p.filter((k) => k !== key)));
  const full = panel.length >= PANEL_MAX;
  const last = panel.length <= PANEL_MIN;
  const onSave = (note: string) => saver.save({ default_panel: panel, editor: { ...data.current.editor, instructions: instructions.trim() } }, note);
  const ordered = [...reviewers].sort((a, b) => {
    const ia = panel.indexOf(a.key);
    const ib = panel.indexOf(b.key);
    return (ia < 0 ? 99 : ia) - (ib < 0 ? 99 : ib) || a.current.name.localeCompare(b.current.name);
  });
  return (
    <>
    <SettingsFrame
      id="reviewers" title="Reviewers" admin={admin} version={data.current.version} dirty={dirty} saving={saver.saving}
      intro="Every kept paper is peer-reviewed by a panel. Each reviewer reads the paper from one perspective and answers its checklist with exact quotes; code turns the answers into scores and red flags. An editor then weighs the reports."
      onSave={onSave} onReset={() => { setPanel(data.defaults.default_panel); setInstructions(data.defaults.editor.instructions); }} resetLabel="Reset panel and editor to default"
      stale={saver.stale} onReload={saver.reload} problem={saver.problem} message={saver.message}
      saveHint="Saving here stores the default panel and the editor instructions. Each reviewer's own checklist is saved from its page."
    >
      <div className="panel-summary">
        <p><strong>Default panel: {panel.length} of {PANEL_MAX} reviewers.</strong> A panel needs {PANEL_MIN} to {PANEL_MAX}; three with different perspectives is a good start.</p>
        {admin && <Link className="button-link" to="/settings/reviewers/new">New reviewer</Link>}
      </div>
      <ul className="reviewer-cards">
        {ordered.map((r) => {
          const on = panel.includes(r.key);
          const whyNot = on && last ? "The panel needs at least one reviewer." : !on && full ? `The panel is full (${PANEL_MAX}). Turn another reviewer off first.` : null;
          return <ReviewerCard key={r.key} reviewer={r} on={on} admin={admin} canToggle={!whyNot} whyNot={admin ? whyNot : null} onToggle={(value) => toggle(r.key, value)} />;
        })}
      </ul>
      <section className="editor-card" aria-labelledby="editor-heading">
        <h3 id="editor-heading">Editor</h3>
        <p className="hint">Always runs after the panel: reads the reports, lists where reviewers disagree and gives the final verdict with a reason. Its model is set under AI models.</p>
        <label className="block">Editor instructions
          <textarea rows={4} maxLength={2000} value={instructions} onChange={(e) => setInstructions(e.target.value)} />
        </label>
      </section>
    </SettingsFrame>
    {/* outside the settings form: its fieldset is disabled for non-admins, and everyone may read the archive */}
    <section aria-label="Archived reviewers" className="archived-box">
      <button type="button" className="linklike" aria-expanded={showArchived} onClick={() => setShowArchived((s) => !s)}>{showArchived ? "Hide archived reviewers" : "Show archived reviewers"}</button>
      {showArchived && <ArchivedList admin={admin} />}
    </section>
    </>
  );
}

export function ReviewersTab() {
  const { user } = useAuth();
  const saver = useSettingsSave();
  const reviewers = useReviewers();
  const { settings } = saver;
  if (settings.isLoading || reviewers.isLoading) return <p role="status">Loading…</p>;
  const error = settings.error ?? reviewers.error;
  if (error || !settings.data) return <p role="alert" className="form-error">{errorText(error)}</p>;
  return <PanelForm key={settings.data.current.version} data={settings.data} reviewers={reviewers.data ?? []} admin={hasRole(user, "admin")} saver={saver} />;
}
