import type { ReactNode } from "react";

export type FlagLike = { text: string; item_text?: string | null; source?: string | null; quote?: string; section?: string };

/**
 * One red flag: the problem first ("No external validation"), then the supporting quote and the checklist item
 * that raised it. The item is phrased positively, so it is never shown as the flag on its own.
 */
export function FlagLine({ flag, evidence }: { flag: FlagLike; evidence?: ReactNode }) {
  return (
    <>
      <strong className="flag-problem">{flag.text}</strong>
      {flag.source && <span className="sub"> ({flag.source})</span>}
      {evidence ?? (flag.quote ? (
        <blockquote className="quote"><span className="sub">Evidence: </span>“{flag.quote}”{flag.section && <footer>{flag.section}</footer>}</blockquote>
      ) : null)}
      {flag.item_text && flag.item_text !== flag.text && <span className="sub flag-item">Checklist item: {flag.item_text}</span>}
    </>
  );
}
