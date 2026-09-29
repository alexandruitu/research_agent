import { createContext, useCallback, useContext, useEffect, useMemo, useRef, type ReactNode } from "react";

export const LEAVE_QUESTION = "You have unsaved changes on this tab. Discard them?";

type Guard = { setDirty: (dirty: boolean) => void; confirmLeave: () => boolean };
const GuardContext = createContext<Guard>({ setDirty: () => undefined, confirmLeave: () => true });

/**
 * One flag for the visible settings tab. BrowserRouter has no navigation blocker, so the tab links ask
 * `confirmLeave()` and a beforeunload listener covers reloads and closing the window.
 */
export function DirtyGuardProvider({ children }: { children: ReactNode }) {
  const dirty = useRef(false);
  useEffect(() => {
    const warn = (event: BeforeUnloadEvent) => {
      if (!dirty.current) return;
      event.preventDefault();
      event.returnValue = "";
    };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, []);
  const setDirty = useCallback((value: boolean) => {
    dirty.current = value;
  }, []);
  const confirmLeave = useCallback(() => {
    if (!dirty.current || window.confirm(LEAVE_QUESTION)) {
      dirty.current = false;
      return true;
    }
    return false;
  }, []);
  const guard = useMemo(() => ({ setDirty, confirmLeave }), [setDirty, confirmLeave]);
  return <GuardContext.Provider value={guard}>{children}</GuardContext.Provider>;
}

export const useLeaveGuard = () => useContext(GuardContext);

/** A tab reports whether it has unsaved edits; unmounting clears the flag. */
export function useReportDirty(dirty: boolean) {
  const { setDirty } = useContext(GuardContext);
  useEffect(() => {
    setDirty(dirty);
  }, [dirty, setDirty]);
  useEffect(() => () => setDirty(false), [setDirty]);
}
