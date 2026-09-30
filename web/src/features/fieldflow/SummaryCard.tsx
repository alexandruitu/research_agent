import { sourceLabel } from "../fields/labels";
import { effectiveTopic, type FieldForm } from "../fields/fieldForm";
import { QUERY_SOURCES } from "./querybuild";

const plural = (n: number, word: string) => `${n} ${word}${n === 1 ? "" : "s"}`;

/** The index card beside the editor: the field as it would be saved now. */
export function SummaryCard({ form, dirty, version }: { form: FieldForm; dirty: boolean; version: number | null }) {
  const years = form.yearFrom || form.yearTo ? `${form.yearFrom || "any"}–${form.yearTo || "now"}` : "any year";
  const overrides = QUERY_SOURCES.filter((s) => form.overrides[s].trim()).length;
  const topic = effectiveTopic(form);
  return (
    <aside aria-label="Field summary" className="summary-card">
      <p className="summary-kicker">{version ? `Field · next save v${version + 1}` : "New field"}</p>
      <h2 className="summary-name">{form.name.trim() || <span className="sub">Untitled field</span>}</h2>
      {topic && <p className="summary-topic">{topic}</p>}
      <dl className="summary-facts">
        <div><dt>Must include</dt><dd>{form.keywords.all.length ? form.keywords.all.join(" · ") : "–"}</dd></div>
        <div><dt>At least one of</dt><dd>{form.keywords.any.length ? form.keywords.any.join(" · ") : "–"}</dd></div>
        <div><dt>Exclude</dt><dd>{form.keywords.none.length ? form.keywords.none.join(" · ") : "–"}</dd></div>
        <div><dt>Criteria</dt><dd>{plural(form.include.length, "inclusion")}, {plural(form.exclude.length, "exclusion")}</dd></div>
        <div><dt>Sources</dt><dd>{form.sources.map(sourceLabel).join(", ") || "none chosen"}{overrides ? ` · ${plural(overrides, "override")}` : ""}</dd></div>
        <div><dt>Years</dt><dd>{years}</dd></div>
      </dl>
      <p className="summary-state" aria-live="polite">{dirty ? <><span aria-hidden="true">●</span> Unsaved changes</> : <><span aria-hidden="true">✓</span> Saved</>}</p>
    </aside>
  );
}
