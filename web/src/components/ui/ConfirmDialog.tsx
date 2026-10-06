import { useEffect, useId, useRef, type ReactNode } from "react";

/**
 * Asks before a destructive action. Focus starts on Cancel (the safe choice), Tab stays between the two
 * buttons, Escape cancels, and focus returns to where it was when the dialog closes.
 */
export function ConfirmDialog({ title, children, confirmLabel, onConfirm, onCancel, busy = false }: {
  title: string; children: ReactNode; confirmLabel: string; onConfirm: () => void; onCancel: () => void; busy?: boolean;
}) {
  const cancel = useRef<HTMLButtonElement>(null);
  const confirm = useRef<HTMLButtonElement>(null);
  const titleId = useId();
  const bodyId = useId();
  useEffect(() => {
    const before = document.activeElement as HTMLElement | null;
    cancel.current?.focus();
    return () => before?.focus?.();
  }, []);
  const onKey = (event: React.KeyboardEvent) => {
    if (event.key === "Escape") { event.preventDefault(); onCancel(); }
    if (event.key === "Tab") {
      event.preventDefault();
      (document.activeElement === cancel.current ? confirm.current : cancel.current)?.focus();
    }
  };
  return (
    <div className="confirm-backdrop">
      <div role="alertdialog" aria-modal="true" aria-labelledby={titleId} aria-describedby={bodyId} className="confirm" onKeyDown={onKey}>
        <h2 id={titleId}>{title}</h2>
        <div id={bodyId} className="confirm__body">{children}</div>
        <div className="confirm__actions">
          <button ref={cancel} type="button" onClick={onCancel}>Cancel</button>
          <button ref={confirm} type="button" className="danger" onClick={onConfirm} disabled={busy}>{confirmLabel}</button>
        </div>
      </div>
    </div>
  );
}
