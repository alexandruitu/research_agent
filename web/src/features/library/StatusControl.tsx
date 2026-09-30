import { useId } from "react";

import { LIBRARY_STATUSES, STATUS_META } from "../../components/ui/StatusMark";

/** The team status as a radio group: icon, word and number key (1–4) for each choice. */
export function StatusControl({ value, onChange, disabled = false, label = "Status" }: { value: string; onChange: (status: string) => void; disabled?: boolean; label?: string }) {
  const name = useId();
  return (
    <fieldset className="status-control" disabled={disabled}>
      <legend>{label}</legend>
      {LIBRARY_STATUSES.map((status, i) => {
        const { icon, word } = STATUS_META[status];
        return (
          <label key={status} className={`status-option status-option--${status} ${value === status ? "is-checked" : ""}`}>
            <input type="radio" name={name} value={status} checked={value === status} onChange={() => onChange(status)} />
            <span aria-hidden="true" className="status-icon">{icon}</span> {word}
            <kbd aria-hidden="true">{i + 1}</kbd>
          </label>
        );
      })}
    </fieldset>
  );
}
