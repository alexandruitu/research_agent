import { useState } from "react";
import { Link } from "react-router-dom";

import type { RunOut } from "../../api/types";
import { sourceLabel } from "../fields/labels";
import { Term } from "../../components/ui/Term";

export type SearchWarning = NonNullable<RunOut["search_warnings"]>[number];

/** "Semantic Scholar (rate limited)": the source and the reason's words, without the HTTP code. */
export function skippedLabel(warning: SearchWarning): string {
  const reason = warning.reason.replace(/\s*\(HTTP \d+\)\s*$/, "");
  return `${sourceLabel(warning.source)} (${reason})`;
}

export const skippedList = (warnings: SearchWarning[]) => warnings.map(skippedLabel).join(", ");

/** One sentence naming the skipped sources, for banners and caveats. */
export function partialSearchSentence(warnings: SearchWarning[]): string {
  const names = warnings.map((w) => sourceLabel(w.source));
  const what = warnings.map(skippedLabel).join(", ");
  const these = names.length === 1 ? "this source" : "these sources";
  return `Partial search: ${what} skipped. Results may be missing papers from ${these}.`;
}

/** Runs list: a marker in words and icon; the tooltip (and screen readers) list what was skipped. */
export function PartialSearchMarker({ warnings }: { warnings: RunOut["search_warnings"] }) {
  if (!warnings?.length) return null;
  const list = skippedList(warnings);
  return (
    <span className="runs__partial" title={`Skipped: ${list}`}>
      <span aria-hidden="true">⚠</span> Partial search<span className="sr-only">: skipped {list}</span>
    </span>
  );
}

/** Run detail: every skipped source with the reason and how to fix it. */
export function SearchWarningPanel({ warnings, failed = false }: { warnings: RunOut["search_warnings"]; failed?: boolean }) {
  if (!warnings?.length) return null;
  const one = warnings.length === 1;
  return (
    <section className="search-warnings" role="status" aria-labelledby="search-warnings-title">
      <h2 id="search-warnings-title"><span aria-hidden="true">⚠</span> {failed ? "No search source answered" : <Term k="partial_search">Partial search</Term>}</h2>
      {failed ? (
        <p>Every source failed, so the run stopped at the search. Fix one of them and resume the run.</p>
      ) : (
        <p>
          {one ? "One source" : `${warnings.length} sources`} did not answer and {one ? "was" : "were"} skipped;
          the run went on with the others. Results may be missing papers from {one ? "this source" : "these sources"}.
        </p>
      )}
      <ul>
        {warnings.map((w) => (
          <li key={w.source}>
            <strong>{sourceLabel(w.source)}</strong>: {w.reason}. {w.detail}
          </li>
        ))}
      </ul>
      <p className="hint">
        Check the sources in <Link to="/settings/sources">Settings → Sources</Link>; mark a source Required in the field to stop the run when it fails.
      </p>
    </section>
  );
}

const dismissKey = (runId: string) => `partial-search-dismissed:${runId}`;

function wasDismissed(runId: string): boolean {
  try {
    return sessionStorage.getItem(dismissKey(runId)) === "1";
  } catch {
    return false;
  }
}

/** Papers page: a dismissible banner (dismissed per run, for this browser session). */
export function PartialSearchBanner({ runId, warnings }: { runId: string; warnings: RunOut["search_warnings"] }) {
  const [dismissed, setDismissed] = useState(() => wasDismissed(runId));
  if (!warnings?.length || dismissed) return null;
  const dismiss = () => {
    try {
      sessionStorage.setItem(dismissKey(runId), "1");
    } catch {
      /* storage blocked: dismiss for this view only */
    }
    setDismissed(true);
  };
  return (
    <div className="partial-search-banner" role="status">
      <span aria-hidden="true">⚠</span>
      <span>{partialSearchSentence(warnings)}</span>
      <button type="button" className="link-button" onClick={dismiss}>Dismiss<span className="sr-only"> the partial search notice</span></button>
    </div>
  );
}
