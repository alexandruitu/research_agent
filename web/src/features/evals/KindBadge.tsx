import { KIND_ICON, KIND_LABEL, kindOf } from "./words";

/** Kind as an icon and a word (never colour alone). */
export function KindBadge({ kind }: { kind: string | undefined }) {
  const k = kindOf(kind);
  return <span className={`kind-badge kind-badge--${k}`}><span aria-hidden="true">{KIND_ICON[k]}</span> {KIND_LABEL[k]}</span>;
}

export function Chips({ chips, label = "Configuration" }: { chips: string[] | undefined; label?: string }) {
  if (!chips?.length) return null;
  return <ul className="config-chips" aria-label={label}>{chips.map((c) => <li key={c}>{c}</li>)}</ul>;
}
