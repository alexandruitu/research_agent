import type { PapersView } from "./papersState";

type Change = Partial<{ decision: string | null; tier: string | null; escalated: boolean | null; in_sr: boolean | null; pmin: number | null; pmax: number | null }>;

const CHIPS: { label: string; sr?: boolean; active: (v: PapersView) => boolean; toggle: (v: PapersView) => Change }[] = [
  { label: "Included", active: (v) => v.params.decision === "include", toggle: (v) => ({ decision: v.params.decision === "include" ? null : "include" }) },
  { label: "Dropped", active: (v) => v.params.decision === "exclude", toggle: (v) => ({ decision: v.params.decision === "exclude" ? null : "exclude" }) },
  { label: "Unsure", active: (v) => v.params.decision === "uncertain", toggle: (v) => ({ decision: v.params.decision === "uncertain" ? null : "uncertain" }) },
  { label: "Decided by Jev", active: (v) => v.params.tier === "jev", toggle: (v) => ({ tier: v.params.tier === "jev" ? null : "jev" }) },
  { label: "Decided by the LLM", active: (v) => v.params.tier === "llm", toggle: (v) => ({ tier: v.params.tier === "llm" ? null : "llm" }) },
  { label: "Only escalated", active: (v) => v.params.escalated === true, toggle: (v) => ({ escalated: v.params.escalated === true ? null : true }) },
  { label: "In the SR", sr: true, active: (v) => v.params.in_sr === true, toggle: (v) => ({ in_sr: v.params.in_sr === true ? null : true }) },
  { label: "Not in the SR", sr: true, active: (v) => v.params.in_sr === false, toggle: (v) => ({ in_sr: v.params.in_sr === false ? null : false }) },
];

/** `showSr` is false for runs without a gold set: the API refuses the in_sr filter there. */
export function FilterBar({ view, showSr, onChange }: { view: PapersView; showSr: boolean; onChange: (change: Change) => void }) {
  const number = (text: string) => (text === "" ? null : Number(text));
  return (
    <div className="filters" role="group" aria-label="Filters">
      {CHIPS.filter((chip) => showSr || !chip.sr).map((chip) => (
        <button key={chip.label} type="button" aria-pressed={chip.active(view)} onClick={() => onChange(chip.toggle(view))}>{chip.label}</button>
      ))}
      <label>Topic match from <input type="number" min={0} max={1} step={0.05} value={view.params.p_min ?? ""} onChange={(e) => onChange({ pmin: number(e.target.value) })} /></label>
      <label>to <input type="number" min={0} max={1} step={0.05} value={view.params.p_max ?? ""} onChange={(e) => onChange({ pmax: number(e.target.value) })} /></label>
    </div>
  );
}
