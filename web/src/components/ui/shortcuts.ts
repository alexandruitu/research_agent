import { useEffect, useRef } from "react";

/** True while the user is typing: shortcuts must never steal keys from a field. */
export const isTypingTarget = (target: EventTarget | null): boolean =>
  target instanceof HTMLElement &&
  (target.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName) || !!target.closest("[role=dialog]"));

export type ShortcutMap = Record<string, (event: KeyboardEvent) => void>;

/**
 * Single-key shortcuts on the document (keys as `event.key`: "j", "?", "Escape"…). Ignored while typing,
 * inside a dialog, or with Ctrl, Meta or Alt held, so browser and screen-reader keys keep working.
 */
export function useShortcuts(map: ShortcutMap, enabled = true) {
  const current = useRef(map);
  useEffect(() => {
    current.current = map;
  });
  useEffect(() => {
    if (!enabled) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.defaultPrevented || event.ctrlKey || event.metaKey || event.altKey) return;
      if (isTypingTarget(event.target)) return;
      const handler = current.current[event.key];
      if (!handler) return;
      event.preventDefault();
      handler(event);
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [enabled]);
}
