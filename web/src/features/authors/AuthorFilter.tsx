import { useEffect, useId, useState, type KeyboardEvent } from "react";

import { useAuthorSuggestions, type AuthorScope } from "../../api/hooks";
import type { AuthorSuggestionOut } from "../../api/types";
import { identityWords, NAME_MATCH_NOTE } from "./authors";

export type AuthorChange = { author: string | null; aname: string | null };
type Props = { authorId?: string; authorName?: string; scope: AuthorScope; onChange: (change: AuthorChange) => void; debounceMs?: number };

/** Author filter with typeahead over stored authors. Picking a suggestion filters by that author (by id);
 * Enter on free text filters by name (a name match, labelled as such). */
export function AuthorFilter({ authorId, authorName, scope, onChange, debounceMs = 200 }: Props) {
  const id = useId();
  const [text, setText] = useState("");
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(-1);
  useEffect(() => {
    const timer = setTimeout(() => setQuery(text), debounceMs);
    return () => clearTimeout(timer);
  }, [text, debounceMs]);
  const suggestions = useAuthorSuggestions(query, scope);
  const options: AuthorSuggestionOut[] = query.trim().length >= 2 ? (suggestions.data ?? []) : [];
  const shown = open && text.trim().length >= 2;
  const pick = (option: AuthorSuggestionOut) => {
    onChange({ author: option.id, aname: null });
    setText("");
    setOpen(false);
    setActive(-1);
  };
  const byName = () => {
    const name = text.trim();
    if (!name) return;
    onChange({ author: null, aname: name.slice(0, 200) });
    setText("");
    setOpen(false);
  };
  const onKey = (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key === "ArrowDown") {
      event.preventDefault();
      setOpen(true);
      setActive((i) => Math.min(options.length - 1, i + 1));
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      setActive((i) => Math.max(-1, i - 1));
    } else if (event.key === "Enter") {
      event.preventDefault();
      const option = active >= 0 ? options[active] : undefined;
      if (option) pick(option);
      else byName();
    } else if (event.key === "Escape" && open) {
      event.stopPropagation();
      setOpen(false);
      setActive(-1);
    }
  };
  const listId = `${id}-authors`;
  return (
    <div className="author-filter">
      <label htmlFor={`${id}-input`}>Author</label>
      <input
        id={`${id}-input`} type="search" role="combobox" autoComplete="off" maxLength={200}
        aria-expanded={shown} aria-controls={shown ? listId : undefined} aria-autocomplete="list" aria-describedby={`${id}-help`}
        aria-activedescendant={shown && active >= 0 ? `${listId}-${active}` : undefined}
        placeholder={authorId || authorName ? "Change author…" : "Name…"}
        value={text}
        onChange={(e) => { setText(e.target.value); setOpen(true); setActive(-1); }}
        onKeyDown={onKey}
        onBlur={() => setTimeout(() => setOpen(false), 150)}
      />
      <span id={`${id}-help`} className="sr-only">Pick a suggestion to filter by that person, or press Enter to filter by the name ({NAME_MATCH_NOTE}).</span>
      {shown && (
        <ul id={listId} role="listbox" className="author-suggestions" aria-label="Authors">
          {options.map((option, index) => (
            <li
              key={option.id} id={`${listId}-${index}`} role="option" aria-selected={index === active}
              className={index === active ? "is-active" : undefined}
              onMouseDown={(e) => { e.preventDefault(); pick(option); }}
            >
              <span className="author-name">{option.name}</span>{" "}
              <span className={`author-badge author-badge--${option.orcid || option.openalex_id ? "id" : "name"}`}>{identityWords(option)}</span>{" "}
              <span className="sub tnum">{option.paper_count} paper{option.paper_count === 1 ? "" : "s"}</span>
            </li>
          ))}
          <li
            id={`${listId}-${options.length}`} role="option" aria-selected={false} className="author-by-name"
            onMouseDown={(e) => { e.preventDefault(); byName(); }}
          >
            Any author named “{text.trim()}” <span className="sub">({NAME_MATCH_NOTE})</span>
          </li>
        </ul>
      )}
      {authorName && <p className="hint author-note" role="note">Author “{authorName}”: {NAME_MATCH_NOTE}.</p>}
    </div>
  );
}
