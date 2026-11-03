import type { ReactNode } from "react";

import { GLOSSARY, type GlossaryKey } from "./terms";
import { Tooltip } from "./Tooltip";

/**
 * A technical word with its plain-language definition: the word as written, then a small "?" button that
 * shows the glossary entry (hover, focus, click or tap). `children` overrides the visible text
 * ("Kappa" in a header); the definition always comes from the glossary.
 */
/** Only the "?" button, for a word that sits inside another control (a sort button, a select). */
export function TermHint({ k }: { k: GlossaryKey }) {
  const entry = GLOSSARY[k];
  return (
    <Tooltip trigger={<span className="term-q" aria-hidden="true" />} triggerLabel={`What is “${entry.label}”?`} className="term-tip"
      tip={<><strong>{entry.label[0]!.toUpperCase() + entry.label.slice(1)}</strong>: {entry.text}</>} />
  );
}

export function Term({ k, children }: { k: GlossaryKey; children?: ReactNode }) {
  const entry = GLOSSARY[k];
  return (
    <span className="term">
      {children ?? entry.label}
      <Tooltip trigger={<span className="term-q" aria-hidden="true" />} triggerLabel={`What is “${entry.label}”?`} className="term-tip"
        tip={<><strong>{entry.label[0]!.toUpperCase() + entry.label.slice(1)}</strong>: {entry.text}</>} />
    </span>
  );
}

/** "Words used here: screening? · red flag? · …": the page's jargon, each with its glossary tip. */
export function TermsLine({ keys }: { keys: GlossaryKey[] }) {
  return (
    <p className="sub terms-line">
      Words used here:{" "}
      {keys.map((k, i) => <span key={k}>{i > 0 && " · "}<Term k={k} /></span>)}
    </p>
  );
}
