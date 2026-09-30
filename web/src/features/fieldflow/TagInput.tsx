import { useId, useState, type KeyboardEvent } from "react";

import { addTerms, MAX_TERMS } from "../fields/fieldForm";

type Props = {
  label: string; hint?: string; tags: string[]; onChange: (tags: string[]) => void; disabled?: boolean; placeholder?: string; tone?: "all" | "any" | "none" | "plain";
};

/**
 * Free-text tags: Enter or comma adds, Backspace in an empty box removes the last one, each tag has its own
 * remove button. Pasting "a, b, c" adds three.
 */
export function TagInput({ label, hint, tags, onChange, disabled = false, placeholder, tone = "plain" }: Props) {
  const [text, setText] = useState("");
  const id = useId();
  const commit = (value = text) => {
    const parts = value.split(",");
    if (parts.every((p) => !p.trim())) return;
    onChange(addTerms(tags, parts));
    setText("");
  };
  const onKeyDown = (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key === "Enter" || event.key === ",") {
      event.preventDefault();
      commit();
    } else if (event.key === "Backspace" && text === "" && tags.length > 0) {
      onChange(tags.slice(0, -1));
    }
  };
  return (
    <div className={`tag-input tag-input--${tone}`}>
      <div className="tag-input-head">
        <label id={`${id}-label`} htmlFor={`${id}-input`} className="tag-input-label">{label}</label>
        <span className="tag-count tnum">{tags.length}/{MAX_TERMS}</span>
      </div>
      {hint && <p className="hint" id={`${id}-hint`}>{hint}</p>}
      <div className="tag-box">
        <ul className="tags" aria-label={`${label} keywords`}>
          {tags.map((tag) => (
            <li key={tag} className="tag">
              <span>{tag}</span>
              {!disabled && (
                <button type="button" className="tag-remove" aria-label={`Remove ${tag} from ${label}`} onClick={() => onChange(tags.filter((t) => t !== tag))}>×</button>
              )}
            </li>
          ))}
        </ul>
        <input
          id={`${id}-input`} value={text} disabled={disabled || tags.length >= MAX_TERMS} placeholder={placeholder}
          aria-describedby={hint ? `${id}-hint` : undefined}
          onChange={(e) => (e.target.value.endsWith(",") ? commit(e.target.value) : setText(e.target.value))}
          onKeyDown={onKeyDown} onBlur={() => commit()}
        />
      </div>
    </div>
  );
}
