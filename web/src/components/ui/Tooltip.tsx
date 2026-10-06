import { useCallback, useEffect, useId, useLayoutEffect, useRef, useState, type ReactNode } from "react";

/**
 * An accessible tooltip on a button trigger: it opens on hover, on keyboard focus and on click or tap (which
 * pins it open), closes on Escape, blur or a click elsewhere. The tip is referenced by aria-describedby, so
 * screen readers read it with the trigger. It is positioned with `position: fixed` (set through the CSSOM,
 * which the CSP allows) so a scrolling table never clips it.
 */
export function Tooltip({ trigger, triggerLabel, tip, className = "" }: {
  trigger: ReactNode;
  /** The trigger's accessible name when its visible text is not enough (e.g. "?"). */
  triggerLabel?: string;
  tip: ReactNode;
  className?: string;
}) {
  const id = useId();
  const [hover, setHover] = useState(false);
  const [focus, setFocus] = useState(false);
  const [pinned, setPinned] = useState(false);
  const button = useRef<HTMLButtonElement>(null);
  const box = useRef<HTMLSpanElement>(null);
  const open = hover || focus || pinned;
  const close = useCallback(() => {
    setHover(false);
    setFocus(false);
    setPinned(false);
  }, []);

  const place = useCallback(() => {
    const anchor = button.current?.getBoundingClientRect();
    const node = box.current;
    if (!anchor || !node) return;
    const width = node.offsetWidth || 280;
    const left = Math.max(8, Math.min(anchor.left, window.innerWidth - width - 8));
    const below = anchor.bottom + 6;
    const top = below + node.offsetHeight > window.innerHeight - 8 && anchor.top > node.offsetHeight + 12 ? anchor.top - node.offsetHeight - 6 : below;
    node.style.left = `${left}px`;
    node.style.top = `${top}px`;
  }, []);
  useLayoutEffect(() => {
    if (open) place();
  }, [open, place]);
  useEffect(() => {
    if (!open) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.stopPropagation();
        close();
      }
    };
    const onDown = (event: PointerEvent) => {
      if (!button.current?.contains(event.target as Node) && !box.current?.contains(event.target as Node)) close();
    };
    document.addEventListener("keydown", onKey, true);
    document.addEventListener("pointerdown", onDown);
    window.addEventListener("scroll", place, true);
    window.addEventListener("resize", place);
    return () => {
      document.removeEventListener("keydown", onKey, true);
      document.removeEventListener("pointerdown", onDown);
      window.removeEventListener("scroll", place, true);
      window.removeEventListener("resize", place);
    };
  }, [open, close, place]);

  return (
    <span className={`tip-wrap ${className}`} onMouseEnter={() => setHover(true)} onMouseLeave={() => setHover(false)}>
      <button
        ref={button} type="button" className="tip-trigger" aria-describedby={id} aria-expanded={open} aria-label={triggerLabel}
        onFocus={() => setFocus(true)} onBlur={() => setFocus(false)}
        onClick={(event) => { event.stopPropagation(); setPinned((p) => !p); }}
      >
        {trigger}
      </button>
      <span ref={box} id={id} role="tooltip" className="tip" hidden={!open}>{tip}</span>
    </span>
  );
}
