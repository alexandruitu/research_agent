import { useState, type FormEvent, type ReactNode } from "react";

type Props = {
  id: string; title: string; intro: ReactNode; admin: boolean; version: number | null; dirty: boolean; saving: boolean;
  onSave: (note: string) => Promise<boolean> | void; onReset?: () => void; resetLabel?: string;
  stale: string | null; onReload: () => void; problem: string | null; message: string | null;
  saveHint?: ReactNode; errors?: string[]; children: ReactNode;
};

/**
 * The chrome every versioned settings tab shares: what the tab is for, which version the next run uses,
 * the read-only explanation, then one Save that creates a new version with a note.
 */
export function SettingsFrame({ id, title, intro, admin, version, dirty, saving, onSave, onReset, resetLabel = "Reset to default", stale, onReload, problem, message, saveHint, errors = [], children }: Props) {
  const [note, setNote] = useState("");
  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if ((await onSave(note)) !== false) setNote("");
  };
  return (
    <section aria-labelledby={`${id}-heading`} className="settings-tab">
      <div className="tab-head">
        <h2 id={`${id}-heading`}>{title}</h2>
        {version !== null && <span className="pill pill--measured">Used by next run · v{version}</span>}
      </div>
      <p className="intro">{intro}</p>
      <form onSubmit={submit} aria-label={title} noValidate>
        <fieldset className="plain" disabled={!admin}>{children}</fieldset>
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
        {message && !dirty && <p role="status" className="banner banner--ok">{message}</p>}
        {admin && (
          <div className="save-bar">
            <label className="note">Change note <input value={note} onChange={(e) => setNote(e.target.value)} placeholder="What changed and why" /></label>
            <button type="submit" className="primary" disabled={saving || !dirty}>{version === null ? "Save" : `Save as v${version + 1}`}</button>
            {onReset && <button type="button" onClick={onReset}>{resetLabel}</button>}
            <span className="sub" aria-live="polite">{dirty ? "Unsaved changes." : "No changes."}</span>
            {saveHint && <p className="sub save-hint">{saveHint}</p>}
          </div>
        )}
      </form>
    </section>
  );
}
