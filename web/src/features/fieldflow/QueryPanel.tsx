import { sourceLabel } from "../fields/labels";
import type { FieldForm } from "../fields/fieldForm";
import { draftQueries, QUERY_SOURCES } from "./querybuild";

type Props = { form: FieldForm; onChange: (patch: Partial<FieldForm>) => void; disabled?: boolean };

/** The query each chosen source will search, built in code from the keywords; overrides folded away. */
export function QueryPanel({ form, onChange, disabled = false }: Props) {
  const rows = draftQueries(form.keywords, form.sources, form.overrides);
  const overridden = QUERY_SOURCES.filter((s) => form.overrides[s].trim()).length;
  return (
    <section className="query-panel" aria-labelledby="queries-title">
      <h3 id="queries-title">The search, per source</h3>
      <p className="hint">Built by code from your keywords, restricted to title and abstract. Years are added by each source.</p>
      {rows.length === 0 ? (
        <p className="sub">Choose a source to see its query.</p>
      ) : (
        <dl className="queries">
          {rows.map((row) => (
            <div key={row.source}>
              <dt>{sourceLabel(row.source)}{row.overridden && <span className="pill">your override</span>}</dt>
              <dd>
                {row.error ? (
                  <span className="form-error-inline">{row.error}</span>
                ) : row.query ? (
                  <output className="query-text" aria-label={`Query for ${sourceLabel(row.source)}`}>{row.query}</output>
                ) : (
                  <span className="sub">No keywords yet: at run time a model plans this query from the topic.</span>
                )}
              </dd>
            </div>
          ))}
        </dl>
      )}
      <details className="disclosure" open={overridden > 0 || undefined}>
        <summary>Advanced: override query{overridden ? ` (${overridden} set)` : ""}</summary>
        <p className="hint">An override replaces the built query for that source, word for word. Leave empty to use the built one.</p>
        {QUERY_SOURCES.map((source) => (
          <label key={source} className="block">Override for {sourceLabel(source)}
            <textarea rows={2} value={form.overrides[source]} disabled={disabled} spellCheck={false} className="mono"
              onChange={(e) => onChange({ overrides: { ...form.overrides, [source]: e.target.value } })} />
          </label>
        ))}
      </details>
    </section>
  );
}
