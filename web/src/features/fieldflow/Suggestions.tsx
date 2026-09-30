import type { AssistResult, KeywordGroup } from "../../api/types";
import { addTerms, type FieldForm } from "../fields/fieldForm";

export const GROUP_LABEL: Record<KeywordGroup, string> = { all: "Must include", any: "At least one of", none: "Exclude" };
/** A synonym widens the search: synonyms of Must-include terms go to At least one of (Decision 3). */
export const synonymGroup = (group: KeywordGroup): KeywordGroup => (group === "all" ? "any" : group);

type Props = { result: AssistResult; form: FieldForm; onChange: (patch: Partial<FieldForm>) => void; onDismiss: () => void; disabled?: boolean };

const has = (list: string[], term: string) => list.some((t) => t.toLowerCase() === term.toLowerCase());
const toggled = (list: string[], term: string) => (has(list, term) ? list.filter((t) => t.toLowerCase() !== term.toLowerCase()) : addTerms(list, [term]));

/** Suggestions are never applied by themselves: each chip is a toggle, "Accept all" takes everything. */
export function Suggestions({ result, form, onChange, onDismiss, disabled = false }: Props) {
  const { suggestions } = result;
  const setGroup = (group: KeywordGroup, terms: string[]) => onChange({ keywords: { ...form.keywords, [group]: terms } });
  const acceptAll = () => {
    const keywords = { ...form.keywords };
    for (const group of ["all", "any", "none"] as const) {
      keywords[group] = addTerms(keywords[group], suggestions[group].map((s) => s.term));
    }
    onChange({ keywords, include: addTerms(form.include, suggestions.include), exclude: addTerms(form.exclude, suggestions.exclude) });
  };
  const total = suggestions.all.length + suggestions.any.length + suggestions.none.length + suggestions.include.length + suggestions.exclude.length;
  return (
    <section className="suggestions rise" aria-labelledby="suggestions-title">
      <div className="suggestions-head">
        <h3 id="suggestions-title">Suggestions <span className="sub">{result.mode === "demo" ? "demo stand-in" : (result.model ?? "model")}</span></h3>
        <div className="actions">
          <button type="button" className="primary" onClick={acceptAll} disabled={disabled || total === 0}>Accept all</button>
          <button type="button" onClick={onDismiss}>Dismiss</button>
        </div>
      </div>
      <p className="hint">Nothing changes until you accept. Click a suggestion to add it; click again to take it back.</p>
      {(["all", "any", "none"] as const).map((group) =>
        suggestions[group].length === 0 ? null : (
          <div key={group} className="suggestion-group">
            <p className="suggestion-label">{GROUP_LABEL[group]}</p>
            <ul className="chips">
              {suggestions[group].map((s) => {
                const on = has(form.keywords[group], s.term);
                const target = synonymGroup(group);
                return (
                  <li key={s.term} className="chip-row">
                    <button type="button" className="suggest-chip" aria-pressed={on} disabled={disabled} onClick={() => setGroup(group, toggled(form.keywords[group], s.term))}>
                      <span aria-hidden="true">{on ? "✓" : "+"}</span> {s.term}{" "}<span className="sr-only">({GROUP_LABEL[group]})</span>
                    </button>
                    {s.synonyms.map((syn) => {
                      const synOn = has(form.keywords[target], syn);
                      return (
                        <button key={syn} type="button" className="suggest-chip suggest-chip--syn" aria-pressed={synOn} disabled={disabled}
                          onClick={() => setGroup(target, toggled(form.keywords[target], syn))}>
                          <span aria-hidden="true">{synOn ? "✓" : "≈"}</span> {syn}{" "}
                          <span className="sr-only">(synonym of {s.term}, goes to {GROUP_LABEL[target]})</span>
                        </button>
                      );
                    })}
                  </li>
                );
              })}
            </ul>
          </div>
        ),
      )}
      {(["include", "exclude"] as const).map((kind) =>
        suggestions[kind].length === 0 ? null : (
          <div key={kind} className="suggestion-group">
            <p className="suggestion-label">{kind === "include" ? "Inclusion criteria" : "Exclusion criteria"}</p>
            <ul className="chips chips--sentences">
              {suggestions[kind].map((text) => {
                const on = form[kind].includes(text);
                return (
                  <li key={text}>
                    <button type="button" className="suggest-chip suggest-chip--sentence" aria-pressed={on} disabled={disabled}
                      onClick={() => onChange({ [kind]: on ? form[kind].filter((t) => t !== text) : [...form[kind], text] })}>
                      <span aria-hidden="true">{on ? "✓" : "+"}</span> {text}
                    </button>
                  </li>
                );
              })}
            </ul>
          </div>
        ),
      )}
    </section>
  );
}
