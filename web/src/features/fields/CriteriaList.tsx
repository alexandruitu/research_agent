import { moveItem } from "./fieldForm";

type Props = { kind: "include" | "exclude"; items: string[]; onChange: (items: string[]) => void };

const TEXT = {
  include: { legend: "Inclusion criteria: a paper must meet all of them", prefix: "incl", noun: "inclusion" },
  exclude: { legend: "Exclusion criteria: any one of them drops the paper", prefix: "excl", noun: "exclusion" },
};

/** One ordered list of criteria. Keys follow the position (i1, i2… on save), so the labels do too. */
export function CriteriaList({ kind, items, onChange }: Props) {
  const { legend, prefix, noun } = TEXT[kind];
  const set = (index: number, text: string) => onChange(items.map((item, i) => (i === index ? text : item)));
  return (
    <fieldset className="criteria">
      <legend>{legend}</legend>
      {items.length === 0 && <p className="sub">None yet.</p>}
      <ol>
        {items.map((text, index) => {
          const name = `${prefix} ${index + 1}`;
          return (
            <li key={index}>
              <label>{name}<input value={text} onChange={(e) => set(index, e.target.value)} /></label>
              <button type="button" aria-label={`Move ${name} up`} disabled={index === 0} onClick={() => onChange(moveItem(items, index, -1))}>↑</button>
              <button type="button" aria-label={`Move ${name} down`} disabled={index === items.length - 1} onClick={() => onChange(moveItem(items, index, 1))}>↓</button>
              <button type="button" aria-label={`Remove ${name}`} onClick={() => onChange(items.filter((_, i) => i !== index))}>Remove</button>
            </li>
          );
        })}
      </ol>
      <button type="button" onClick={() => onChange([...items, ""])}>Add {noun} criterion</button>
    </fieldset>
  );
}
