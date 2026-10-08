import { useState, type FormEvent } from "react";
import { Link } from "react-router-dom";

import { ApiError } from "../../api/client";
import { useAlert, useFollowAlert, useRunAlertNow, useSaveAlert } from "../../api/hooks";
import { hasRole, type AlertIn, type AlertOut } from "../../api/types";
import { useAuth } from "../../auth/AuthProvider";
import { TermHint } from "../../components/ui/Term";
import { Tooltip } from "../../components/ui/Tooltip";
import { useToast } from "../../components/ui/Toast";

export const WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];
const errorText = (error: unknown) => (error instanceof ApiError ? error.message : "Could not reach the server.");
const hourText = (hour: number) => `${String(hour).padStart(2, "0")}:00`;

/** "Every Monday at 07:00 (CEST)" / "Every day at 07:00 (CEST)". */
export function scheduleText(alert: Pick<AlertOut, "cadence" | "weekday" | "hour" | "timezone">) {
  const when = alert.cadence === "daily" ? "Every day" : `Every ${WEEKDAYS[alert.weekday] ?? "week"}`;
  return `${when} at ${hourText(alert.hour)} (${alert.timezone})`;
}

const toForm = (alert: AlertOut): AlertIn => ({
  enabled: alert.exists ? alert.enabled : true,
  cadence: alert.cadence === "daily" ? "daily" : "weekly",
  weekday: alert.weekday, hour: alert.hour, max_new: alert.max_new,
  min_group: alert.min_group === "read_first" ? "read_first" : "worth_a_look",
  years_back: alert.years_back,
});

/** The field page's alert: a schedule that re-runs the field and puts what is new in the Alerts inbox. */
export function AlertCard({ fieldId, archived, demo }: { fieldId: string; archived: boolean; demo: boolean }) {
  const alert = useAlert(fieldId);
  if (alert.isLoading) return <aside className="side-panel alert-card" aria-label="Alert"><h2>Alert</h2><p className="sub">Loading…</p></aside>;
  if (alert.isError || !alert.data) return <aside className="side-panel alert-card" aria-label="Alert"><h2>Alert</h2><p role="alert" className="form-error">{errorText(alert.error)}</p></aside>;
  return <AlertForm key={`${alert.data.id ?? "new"}:${alert.data.enabled}`} alert={alert.data} fieldId={fieldId} archived={archived} demo={demo} />;
}

function AlertForm({ alert, fieldId, archived, demo }: { alert: AlertOut; fieldId: string; archived: boolean; demo: boolean }) {
  const save = useSaveAlert(fieldId);
  const runNow = useRunAlertNow(fieldId);
  const follow = useFollowAlert(fieldId);
  const toast = useToast();
  const { user } = useAuth();
  const member = hasRole(user, "member");
  const [form, setForm] = useState<AlertIn>(() => toForm(alert));
  const [problem, setProblem] = useState<string | null>(null);
  const [startedRun, setStartedRun] = useState<string | null>(null);
  const editable = alert.can_edit && !archived;
  const update = (changes: Partial<AlertIn>) => setForm((prev) => ({ ...prev, ...changes }));
  const act = async (work: () => Promise<unknown>) => {
    setProblem(null);
    try {
      await work();
    } catch (error) {
      setProblem(errorText(error));
    }
  };
  const submit = (event: FormEvent) => {
    event.preventDefault();
    void act(async () => {
      await save.mutateAsync(form);
      toast.show({ text: form.enabled ? "Alert saved" : "Alert saved (off)" });
    });
  };
  const toggle = (enabled: boolean) => {
    update({ enabled });
    // the switch saves at once when an alert exists; a new alert is created with "Save alert"
    if (alert.exists) void act(() => save.mutateAsync({ ...form, enabled }));
  };
  const start = () => void act(async () => {
    const out = await runNow.mutateAsync(demo ? "demo" : "live");
    setStartedRun(out.run_id);
    toast.show({ text: demo ? "Alert run started (demo)" : "Alert run started" });
  });
  const people = alert.subscriber_count === 1 ? "1 person follows" : `${alert.subscriber_count} people follow`;
  const capped = alert.effective_max_new < alert.max_new;
  const lastRun = startedRun ?? alert.last_run_id;

  return (
    <aside className="side-panel alert-card" aria-label="Alert">
      <h2>Alert <Tooltip trigger="?" triggerLabel="About alerts" tip="On a schedule, the alert re-runs this field, skips papers seen in earlier runs, reviews only what is new and puts the best of it in the Alerts inbox of everyone who follows it." /></h2>
      {alert.paused_reason && <p className="banner banner--bad" role="status"><strong>Paused:</strong> {alert.paused_reason}</p>}
      {!alert.paused_reason && alert.failures > 0 && <p className="banner banner--warn" role="status">The last {alert.failures === 1 ? "run" : `${alert.failures} runs`} failed; it pauses after repeated failures.</p>}
      {alert.deferred_at && <p className="banner banner--warn" role="status">Deferred: the daily limit of alert runs was reached; it runs at the next slot.</p>}
      <form className="alert-form" onSubmit={submit} aria-label="Alert settings">
        <label className="check alert-switch">
          <input type="checkbox" role="switch" checked={form.enabled} disabled={!editable || save.isPending} onChange={(e) => toggle(e.target.checked)} />
          {" "}Alert {form.enabled ? "on" : "off"}
        </label>
        <fieldset disabled={!editable}>
          <legend>Schedule</legend>
          <label>Repeat{" "}
            <select value={form.cadence} onChange={(e) => update({ cadence: e.target.value === "daily" ? "daily" : "weekly" })}>
              <option value="weekly">Weekly</option>
              <option value="daily">Daily</option>
            </select>
          </label>
          {form.cadence === "weekly" && (
            <label>On{" "}
              <select value={form.weekday} onChange={(e) => update({ weekday: Number(e.target.value) })}>
                {WEEKDAYS.map((day, i) => <option key={day} value={i}>{day}</option>)}
              </select>
            </label>
          )}
          <label>At{" "}
            <select value={form.hour} onChange={(e) => update({ hour: Number(e.target.value) })}>
              {Array.from({ length: 24 }, (_, h) => <option key={h} value={h}>{hourText(h)}</option>)}
            </select>
          </label>
          <span className="sub">Times are the server’s time zone ({alert.timezone}).</span>
        </fieldset>
        <label>Notify me about{" "}
          <select value={form.min_group} disabled={!editable} onChange={(e) => update({ min_group: e.target.value === "read_first" ? "read_first" : "worth_a_look" })}>
            <option value="read_first">Read first</option>
            <option value="worth_a_look">Read first + Worth a look</option>
          </select>
        </label>
        <label>Max new papers per run{" "}
          <input type="number" min={1} max={200} value={form.max_new} disabled={!editable} onChange={(e) => update({ max_new: Number(e.target.value) })} />
          <Tooltip trigger="?" triggerLabel="About max new papers" tip="Only new papers are reviewed, and each review costs model calls. Papers over the limit are counted in the digest but not reviewed." />
        </label>
        {capped && <p className="sub" role="note">This deployment reviews at most {alert.effective_max_new} papers per run, so each alert run reviews up to {alert.effective_max_new}.</p>}
        <label>Years back{" "}
          <input type="number" min={0} max={10} value={form.years_back} disabled={!editable} onChange={(e) => update({ years_back: Number(e.target.value) })} />
          <Tooltip trigger="?" triggerLabel="About years back" tip="How many years before this one the search covers; 0 means this year only." />
        </label>
        {editable && <button type="submit" className="primary" disabled={save.isPending}>Save alert</button>}
        {!alert.can_edit && <p className="sub">Read-only: only the alert’s creator or an admin can change it.</p>}
      </form>
      {alert.exists && (
        <dl className="alert-facts">
          <dt>Schedule</dt><dd>{scheduleText(alert)}</dd>
          <dt>Next run</dt><dd>{alert.next_run_at ? <time dateTime={alert.next_run_at}>{new Date(alert.next_run_at).toLocaleString()}</time> : "none (alert off)"}</dd>
          <dt>Last run</dt><dd>{lastRun ? <Link to={`/runs/${lastRun}`}>{startedRun ? "started just now" : (alert.last_run_status ?? "open")}</Link> : "not run yet"}</dd>
        </dl>
      )}
      {alert.exists && alert.id && (
        <div className="actions">
          {alert.can_edit && !archived && (
            <span className="check-with-term">
              <button type="button" onClick={start} disabled={runNow.isPending}>{demo ? "Run now (demo)" : "Run now"}</button>
              {demo && <TermHint k="demo_mode" />}
            </span>
          )}
          {member && <button type="button" aria-pressed={alert.subscribed} disabled={follow.isPending} onClick={() => void act(() => follow.mutateAsync({ alertId: alert.id!, follow: !alert.subscribed }))}>
            {alert.subscribed ? "Unfollow" : "Follow"}
          </button>}
          <span className="sub">{people}{alert.subscribed ? " (including you)" : ""}.</span>
        </div>
      )}
      {problem && <p role="alert" className="form-error">{problem}</p>}
    </aside>
  );
}
