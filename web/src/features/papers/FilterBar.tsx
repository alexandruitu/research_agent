import { criterionLabel, sourceLabel } from "../fields/labels";
import { PAPER_SOURCES, type PapersView } from "./papersState";

type Change = Partial<{ flags: boolean | null; decision: string | null; tier: string | null; escalated: boolean | null; in_sr: boolean | null; pmin: number | null; pmax: number | null; by: string | null; src: string | null }>;
export type CriterionOption = { key: string; text: string };

const CHIPS: { label: string; sr?: boolean; panel?: boolean; active: (v: PapersView) => boolean; toggle: (v: PapersView) => Change }[] = [
  { label: "Included", active: (v) => v.params.decision === "include", toggle: (v) => ({ decision: v.params.decision === "include" ? null : "include" }) },
  { label: "Dropped", active: (v) => v.params.decision === "exclude", toggle: (v) => ({ decision: v.params.decision === "exclude" ? null : "exclude" }) },
  { label: "Unsure", active: (v) => v.params.decision === "uncertain", toggle: (v) => ({ decision: v.params.decision === "uncertain" ? null : "uncertain" }) },
  { label: "Decided by Jev", active: (v) => v.params.tier === "jev", toggle: (v) => ({ tier: v.params.tier === "jev" ? null : "jev" }) },
  { label: "Decided by the LLM", active: (v) => v.params.tier === "llm", toggle: (v) => ({ tier: v.params.tier === "llm" ? null : "llm" }) },
  { label: "Only escalated", active: (v) => v.params.escalated === true, toggle: (v) => ({ escalated: v.params.escalated === true ? null : true }) },
  { label: "Has red flags", panel: true, active: (v) => v.params.has_red_flags === true, toggle: (v) => ({ flags: v.params.has_red_flags ? null : true }) },
  { label: "In the SR", sr: true, active: (v) => v.params.in_sr === true, toggle: (v) => ({ in_sr: v.params.in_sr === true ? null : true }) },
  { label: "Not in the SR", sr: true, active: (v) => v.params.in_sr === false, toggle: (v) => ({ in_sr: v.params.in_sr === false ? null : false }) },
];

type Props = { view: PapersView; showSr: boolean; showPanel?: boolean; legacy: boolean; criteria: CriterionOption[]; onChange: (change: Change) => void };

/** `showSr` is false for runs without a gold set (the API refuses in_sr there); the topic-match range only applies to legacy runs. */
export function FilterBar({ view, showSr, showPanel = false, legacy, criteria, onChange }: Props) {
  const number = (text: string) => (text === "" ? null : Number(text));
  const selectedBy = view.params.decided_by;
  const options = selectedBy && !criteria.some((c) => c.key === selectedBy) ? [...criteria, { key: selectedBy, text: "" }] : criteria;
  return (
    <div className="filters" role="group" aria-label="Filters">
      {CHIPS.filter((chip) => (showSr || !chip.sr) && (showPanel || !chip.panel || chip.active(view))).map((chip) => (
        <button key={chip.label} type="button" aria-pressed={chip.active(view)} onClick={() => onChange(chip.toggle(view))}>{chip.label}</button>
      ))}
      <label>Dropped by criterion
        <select value={selectedBy ?? ""} onChange={(e) => onChange({ by: e.target.value || null })}>
          <option value="">any</option>
          {options.map((c) => <option key={c.key} value={c.key}>{criterionLabel(c.key)}{c.text ? `: ${c.text}` : ""}</option>)}
        </select>
      </label>
      <label>Source
        <select value={view.params.source ?? ""} onChange={(e) => onChange({ src: e.target.value || null })}>
          <option value="">any</option>
          {PAPER_SOURCES.map((name) => <option key={name} value={name}>{sourceLabel(name)}</option>)}
        </select>
      </label>
      {legacy && (
        <>
          <label>Topic match from <input type="number" min={0} max={1} step={0.05} value={view.params.p_min ?? ""} onChange={(e) => onChange({ pmin: number(e.target.value) })} /></label>
          <label>to <input type="number" min={0} max={1} step={0.05} value={view.params.p_max ?? ""} onChange={(e) => onChange({ pmax: number(e.target.value) })} /></label>
        </>
      )}
    </div>
  );
}
