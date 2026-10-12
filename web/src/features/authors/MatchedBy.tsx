import type { MatchKind, MatchOut } from "../../api/types";
import { MATCH_FILTER_WORDS, MATCH_KINDS, matchWords } from "./researcher";

/** Researcher topics: how the paper matches the topic's people, in words (null: not a researcher topic). */
export function MatchedBy({ matches }: { matches: MatchOut[] | null | undefined }) {
  if (matches == null) return null;
  if (matches.length === 0) return <span className="matched-by sub">Matched by: no stored author matches</span>;
  return (
    <span className="matched-by">
      <span className="sub">Matched by: </span>
      {matches.map((m) => (
        <span key={`${m.kind}:${m.name}`} className={`chip match-chip match-chip--${m.kind}${m.kind === "name_match" ? " chip--warn" : ""}`}>{matchWords(m)}</span>
      ))}
    </span>
  );
}

/** The "Matched by" filter of a researcher topic's Results. */
export function MatchFilter({ value, onChange }: { value: MatchKind | undefined; onChange: (next: MatchKind | null) => void }) {
  return (
    <label>Matched by
      <select value={value ?? ""} onChange={(e) => onChange((e.target.value || null) as MatchKind | null)}>
        <option value="">any</option>
        {MATCH_KINDS.map((k) => <option key={k} value={k}>{MATCH_FILTER_WORDS[k]}</option>)}
      </select>
    </label>
  );
}
