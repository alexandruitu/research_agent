import { createContext, useCallback, useContext, useEffect, useMemo, useRef, type ReactNode } from "react";

export const LEAVE_QUESTION = "You have unsaved changes on this page. Discard them?";

type Guard = { setDirty: (dirty: boolean) => void; confirmLeave: () => boolean; mounted: boolean };
const GuardContext = createContext<Guard>({ setDirty: () => undefined, confirmLeave: () => true, mounted: false });

/**
 * One app-wide flag for the page being edited (a settings tab, the field editor, a reviewer). BrowserRouter
 * has no navigation blocker, so the main navigation, the settings tabs and Sign out ask `confirmLeave()`,
 * and a beforeunload listener covers reloads and closing the window. A provider inside another one is
 * transparent: everything shares the outermost flag.
 */
export function DirtyGuardProvider({ children }: { children: ReactNode }) {
  const outer = useContext(GuardContext);
  return outer.mounted ? <>{children}</> : <RootGuard>{children}</RootGuard>;
}

function RootGuard({ children }: { children: ReactNode }) {
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
  const guard = useMemo(() => ({ setDirty, confirmLeave, mounted: true }), [setDirty, confirmLeave]);
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
