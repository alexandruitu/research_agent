import type { SourceOut } from "../../api/types";
import { groupSources } from "../settings/sources";
import { isSourceName } from "./labels";

type Props = {
  sources: SourceOut[]; chosen: string[]; disabled?: boolean; onToggle: (name: string, on: boolean) => void;
  required?: string[]; onRequire?: (name: string, on: boolean) => void;
};

/** Search sources grouped as in Settings → Sources. Only enabled sources can be picked; a disabled one that the
 * saved version still lists can be unticked but not ticked again. */
export function SourcePicker({ sources, chosen, disabled = false, onToggle, required = [], onRequire }: Props) {
  const groups = groupSources(sources.filter((s) => isSourceName(s.name) && s.capabilities.includes("search")));
  return (
    <fieldset className="source-picker">
      <legend>Sources</legend>
      <p className="hint">Only sources an admin enabled in Settings → Sources can be chosen.</p>
      {onRequire && (
        <p className="hint">
          A source that fails during a run is skipped with a warning (partial search). Mark it <strong>Required</strong> to stop the run instead; Europe PMC is a good candidate.
        </p>
      )}
      {groups.map((group) => (
        <div key={group.key} role="group" aria-labelledby={`pick-${group.key}`} className="source-picker-group">
          <span id={`pick-${group.key}`} className="source-picker-title">{group.title}</span>
          {group.sources.map((source) => {
            const checked = chosen.includes(source.name);
            const why = source.enabled ? null : source.auth === "required" && !source.key_present ? "needs a key" : "disabled in Settings";
            return (
              <span key={source.name} className="source-choice-row">
                <label className="check source-choice" title={source.covers}>
                  <input type="checkbox" checked={checked} disabled={disabled || (!source.enabled && !checked)} onChange={(e) => onToggle(source.name, e.target.checked)} />
                  {source.label}{why ? ` (${why})` : ""}
                </label>
                {onRequire && checked && (
                  <label className="check source-required" title="Stop the run when this source fails, instead of skipping it with a warning">
                    <input type="checkbox" checked={required.includes(source.name)} disabled={disabled} onChange={(e) => onRequire(source.name, e.target.checked)} aria-label={`${source.label} required`} />
                    Required
                  </label>
                )}
              </span>
            );
          })}
        </div>
      ))}
    </fieldset>
  );
}
