import { createContext, useContext, useEffect, useRef, useState, type ReactNode } from "react";

import { GLOSSARY, GLOSSARY_KEYS } from "./terms";

/** The glossary dialog: every term the app uses, in plain language. Escape or Close returns focus. */
export function GlossaryDialog({ onClose }: { onClose: () => void }) {
  const dialog = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const opener = document.activeElement as HTMLElement | null;
    const node = dialog.current;
    if (node && !node.open) {
      if (typeof node.showModal === "function") node.showModal();
      else node.setAttribute("open", "");
    }
    node?.querySelector<HTMLElement>("button")?.focus();
    return () => opener?.focus?.();
  }, []);
  return (
    <dialog ref={dialog} className="sheet sheet--glossary" aria-labelledby="glossary-title" onCancel={(event) => { event.preventDefault(); onClose(); }} onKeyDown={(event) => event.key === "Escape" && onClose()}>
      <div className="sheet-head">
        <h2 id="glossary-title">Glossary</h2>
        <button type="button" onClick={onClose}>Close</button>
      </div>
      <dl className="glossary-list">
        {GLOSSARY_KEYS.map((key) => (
          <div key={key}>
            <dt>{GLOSSARY[key].label}</dt>
            <dd>{GLOSSARY[key].text}</dd>
          </div>
        ))}
      </dl>
    </dialog>
  );
}

const Open = createContext<() => void>(() => {});

/** Lets any page (the "?" sheets, the footer) open the one glossary dialog. */
export function GlossaryProvider({ children }: { children: ReactNode }) {
  const [open, setOpen] = useState(false);
  return (
    <Open.Provider value={() => setOpen(true)}>
      {children}
      {open && <GlossaryDialog onClose={() => setOpen(false)} />}
    </Open.Provider>
  );
}

export const useOpenGlossary = () => useContext(Open);

/** A link-styled button that opens the glossary. */
export function GlossaryLink({ children = "Glossary", onBeforeOpen }: { children?: ReactNode; onBeforeOpen?: () => void }) {
  const open = useOpenGlossary();
  return <button type="button" className="linklike" onClick={() => { onBeforeOpen?.(); open(); }}>{children}</button>;
}
