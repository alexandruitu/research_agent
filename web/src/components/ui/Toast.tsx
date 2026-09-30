import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";

export type ToastInput = { text: string; tone?: "ok" | "bad" | "info"; action?: { label: string; run: () => void }; ms?: number };
type Toast = ToastInput & { id: number };
type ToastApi = { show: (toast: ToastInput) => void };

const ToastContext = createContext<ToastApi>({ show: () => undefined });
const TONE_ICON = { ok: "✓", bad: "!", info: "i" } as const;
const TONE_WORD = { ok: "Done", bad: "Problem", info: "Note" } as const;

function ToastItem({ toast, onClose }: { toast: Toast; onClose: () => void }) {
  const tone = toast.tone ?? "ok";
  useEffect(() => {
    const timer = window.setTimeout(onClose, toast.ms ?? (toast.action ? 8000 : 5000));
    return () => window.clearTimeout(timer);
  }, [toast, onClose]);
  return (
    <li className={`toast toast--${tone}`} onKeyDown={(event) => event.key === "Escape" && onClose()}>
      <span className="toast-icon" aria-hidden="true">{TONE_ICON[tone]}</span>
      <span className="sr-only">{TONE_WORD[tone]}: </span>
      <span className="toast-text">{toast.text}</span>
      {toast.action && (
        <button type="button" className="toast-action" onClick={() => { toast.action?.run(); onClose(); }}>{toast.action.label}</button>
      )}
      <button type="button" className="toast-close" aria-label="Dismiss" onClick={onClose}>×</button>
    </li>
  );
}

/** Feedback that does not move focus: a polite live region at the bottom of the screen, optional Undo. */
export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const next = useRef(1);
  const show = useCallback((toast: ToastInput) => {
    const id = next.current++;
    setToasts((list) => [...list.slice(-3), { ...toast, id }]);
  }, []);
  const close = useCallback((id: number) => setToasts((list) => list.filter((t) => t.id !== id)), []);
  const api = useMemo(() => ({ show }), [show]);
  return (
    <ToastContext.Provider value={api}>
      {children}
      <section aria-live="polite" aria-label="Notifications" className="toasts">
        <ul>
          {toasts.map((toast) => <ToastItem key={toast.id} toast={toast} onClose={() => close(toast.id)} />)}
        </ul>
      </section>
    </ToastContext.Provider>
  );
}

export const useToast = () => useContext(ToastContext);
