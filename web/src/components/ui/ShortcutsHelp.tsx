import { useEffect, useRef } from "react";

import { GlossaryLink } from "./GlossaryDialog";

export type ShortcutHelpItem = { keys: string[]; what: string };

/** The "?" sheet: a modal dialog listing the shortcuts of the page. Escape or Close returns focus. */
export function ShortcutsHelp({ title, items, onClose }: { title: string; items: ShortcutHelpItem[]; onClose: () => void }) {
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
    <dialog ref={dialog} className="sheet" aria-labelledby="shortcuts-title" onCancel={(event) => { event.preventDefault(); onClose(); }} onKeyDown={(event) => event.key === "Escape" && onClose()}>
      <div className="sheet-head">
        <h2 id="shortcuts-title">{title}</h2>
        <button type="button" onClick={onClose}>Close</button>
      </div>
      <dl className="shortcut-list">
        {items.map((item) => (
          <div key={item.what}>
            <dt>{item.keys.map((key, i) => <span key={key}>{i > 0 && " or "}<kbd>{key}</kbd></span>)}</dt>
            <dd>{item.what}</dd>
          </div>
        ))}
      </dl>
      <p className="hint">Shortcuts are off while you type in a field. Unfamiliar word? <GlossaryLink onBeforeOpen={onClose}>Open the glossary</GlossaryLink>.</p>
    </dialog>
  );
}
