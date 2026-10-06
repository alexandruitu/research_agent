import { useEffect, useId, useRef, useState, type KeyboardEvent } from "react";

export type MenuItem = { label: string; onSelect: () => void; danger?: boolean; disabled?: boolean };

/**
 * A button that opens a menu (WAI-ARIA menu button): Enter, Space or ArrowDown open it on the first item,
 * ArrowUp on the last; ArrowUp/ArrowDown/Home/End move; Enter or Space choose; Escape or Tab close and focus
 * returns to the button. Disabled items are skipped.
 */
export function MenuButton({ label, items, className = "", text }: { label: string; items: MenuItem[]; className?: string; text?: string }) {
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const button = useRef<HTMLButtonElement>(null);
  const refs = useRef<(HTMLButtonElement | null)[]>([]);
  const wrapper = useRef<HTMLDivElement>(null);
  const id = useId();
  const enabled = items.map((item, i) => (item.disabled ? -1 : i)).filter((i) => i >= 0);

  useEffect(() => {
    if (open) refs.current[active]?.focus();
  }, [open, active]);
  useEffect(() => {
    if (!open) return;
    const close = (event: MouseEvent) => {
      if (!wrapper.current?.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, [open]);

  const openAt = (index: number) => {
    if (enabled.length === 0) return;
    setActive(index);
    setOpen(true);
  };
  const close = (focus = true) => {
    setOpen(false);
    if (focus) button.current?.focus();
  };
  const move = (step: number) => {
    const at = enabled.indexOf(active);
    setActive(enabled[(at + step + enabled.length) % enabled.length]);
  };
  const onButtonKey = (event: KeyboardEvent) => {
    if (event.key === "ArrowDown") { event.preventDefault(); openAt(enabled[0]); }
    if (event.key === "ArrowUp") { event.preventDefault(); openAt(enabled[enabled.length - 1]); }
  };
  const onMenuKey = (event: KeyboardEvent) => {
    const keys: Record<string, () => void> = {
      ArrowDown: () => move(1),
      ArrowUp: () => move(-1),
      Home: () => setActive(enabled[0]),
      End: () => setActive(enabled[enabled.length - 1]),
      Escape: () => close(),
      Tab: () => close(false),
    };
    const action = keys[event.key];
    if (!action) return;
    if (event.key !== "Tab") event.preventDefault();
    action();
  };
  const choose = (item: MenuItem) => {
    close();
    item.onSelect();
  };

  return (
    <div className={`menu-button ${className}`} ref={wrapper}>
      <button
        ref={button}
        type="button"
        className="menu-button__trigger"
        aria-haspopup="menu"
        aria-expanded={open}
        aria-controls={open ? id : undefined}
        onClick={() => (open ? close() : openAt(enabled[0]))}
        onKeyDown={onButtonKey}
        aria-label={text ? label : undefined}
      >
        {text ? <>{text} <span aria-hidden="true">▾</span></> : label}
      </button>
      {open && (
        <ul id={id} role="menu" aria-label={label} className="menu" onKeyDown={onMenuKey}>
          {items.map((item, i) => (
            <li key={item.label} role="none">
              <button
                ref={(el) => { refs.current[i] = el; }}
                type="button"
                role="menuitem"
                tabIndex={i === active ? 0 : -1}
                aria-disabled={item.disabled || undefined}
                className={item.danger ? "menu__item menu__item--danger" : "menu__item"}
                onClick={() => !item.disabled && choose(item)}
              >
                {item.label}
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
