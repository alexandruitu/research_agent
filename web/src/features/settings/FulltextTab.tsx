import { useState } from "react";

import { hasRole, type FulltextIO, type ReviewSettingsOut } from "../../api/types";
import { useAuth } from "../../auth/AuthProvider";
import { useReportDirty } from "./dirtyGuard";
import { useSources } from "../../api/hooks";
import { enabledOrder, moveResolver, resolverInfo, resolverList, validateFulltext, type ResolverEntry } from "./fulltext";
import { keyStatusWords } from "./sources";
import { SettingsFrame } from "./SettingsFrame";
import { errorText, useSettingsSave } from "./useSettingsSave";

const pages = (chars: number) => Math.max(1, Math.round(chars / 3000));

function FulltextForm({ data, admin, saver }: { data: ReviewSettingsOut; admin: boolean; saver: ReturnType<typeof useSettingsSave> }) {
  const saved = data.current.fulltext;
  const [values, setValues] = useState<FulltextIO>(saved);
  const [list, setList] = useState<ResolverEntry[]>(() => resolverList(saved.sources));
  const sourceRows = useSources().data ?? [];
  const [errors, setErrors] = useState<string[]>([]);
  const dirty = JSON.stringify(values) !== JSON.stringify(saved);
  useReportDirty(dirty);
  const set = (patch: Partial<FulltextIO>) => setValues((v) => ({ ...v, ...patch }));
  const update = (next: ResolverEntry[]) => {
    setList(next);
    set({ sources: enabledOrder(next) });
  };
  const toggle = (index: number, on: boolean) => update(list.map((e, i) => (i === index ? { ...e, on } : e)));
  const reset = () => {
    setValues(data.defaults.fulltext);
    setList(resolverList(data.defaults.fulltext.sources));
  };
  const onSave = async (note: string) => {
    const clean = { ...values, contact: (values.contact ?? "").trim() || null };
    const found = validateFulltext(clean);
    setErrors(found);
    return found.length === 0 && saver.save({ fulltext: clean }, note);
  };
  const number = (text: string) => (text === "" ? Number.NaN : Number(text));
  return (
    <SettingsFrame
      id="fulltext" title="Full text" admin={admin} version={data.current.version} dirty={dirty} saving={saver.saving}
      intro="Reviewers read the full paper when one of these sources has it, in this order; otherwise they read the abstract, and items the abstract cannot answer count as “not reported”, never as “no”."
      onSave={onSave} onReset={reset} stale={saver.stale} onReload={saver.reload} problem={saver.problem} message={saver.message} errors={errors}
    >
      <fieldset>
        <legend>Where full text comes from (tried top to bottom; the first that has the paper wins)</legend>
        <ol className="resolver-list">
          {list.map((entry, index) => {
            const info = resolverInfo(entry.key);
            const row = info.source ? sourceRows.find((r) => r.name === info.source) : undefined;
            const key = row ? keyStatusWords(row) : null;
            const position = entry.on ? `${enabledOrder(list.slice(0, index + 1)).length}.` : "–";
            return (
              <li key={entry.key} className={entry.on ? "resolver resolver--on" : "resolver"}>
                <span className="resolver-rank" aria-hidden="true">{position}</span>
                <div className="resolver-body">
                  <label className="switch">
                    <input type="checkbox" role="switch" checked={entry.on} disabled={!admin} aria-describedby={`ft-${entry.key}`} onChange={(e) => toggle(index, e.target.checked)} />
                    <span className="switch-label">{info.label}</span>{" "}
                    <span className="switch-state">{entry.on ? "on" : "off"}</span>
                  </label>
                  <p id={`ft-${entry.key}`} className="hint">{info.explain} <span className="resolver-licence">Licence: {info.licence}</span>{key ? ` ${key}.` : ""}</p>
                </div>
                {admin && (
                  <span className="resolver-move">
                    <button type="button" disabled={index === 0} onClick={() => update(moveResolver(list, index, -1))}><span aria-hidden="true">↑</span><span className="sr-only">Move {info.label} up</span></button>
                    <button type="button" disabled={index === list.length - 1} onClick={() => update(moveResolver(list, index, 1))}><span aria-hidden="true">↓</span><span className="sr-only">Move {info.label} down</span></button>
                  </span>
                )}
              </li>
            );
          })}
        </ol>
        {values.sources.length === 0 && <p className="banner banner--warn">No full-text source: every paper is reviewed on its abstract only.</p>}
      </fieldset>
      <label className="block">Contact email for Unpaywall
        <input type="email" value={values.contact ?? ""} aria-describedby="ft-contact" onChange={(e) => set({ contact: e.target.value })} />
        <span id="ft-contact" className="hint">{values.sources.includes("unpaywall") ? "Required while Unpaywall is on." : "Only used by Unpaywall."}</span>
      </label>
      <div className="two-up">
        <label className="block">Maximum text length (characters)
          <input type="number" min={2000} max={200000} step={1000} value={Number.isFinite(values.max_chars) ? values.max_chars : ""} aria-describedby="ft-max" onChange={(e) => set({ max_chars: number(e.target.value) })} />
          <span id="ft-max" className="hint">
            About {Number.isFinite(values.max_chars) ? pages(values.max_chars) : "?"} pages. Longer papers are cut, keeping Methods and Results first. 2 000 to 200 000.
          </span>
        </label>
        <label className="block">Upload limit (MB)
          <input type="number" min={1} max={30} value={Number.isFinite(values.upload_max_mb) ? values.upload_max_mb : ""} aria-describedby="ft-upload" onChange={(e) => set({ upload_max_mb: number(e.target.value) })} />
          <span id="ft-upload" className="hint">Largest PDF a member can upload, 1 to 30 MB. Only PDFs are accepted.</span>
        </label>
      </div>
      <p className="hint">Open-access, uploaded or institution-entitled text is sent to the AI providers for review only. Text under a publisher licence is never exported. Uploaded PDFs are stored by content hash and shown only to members.</p>
    </SettingsFrame>
  );
}

export function FulltextTab() {
  const { user } = useAuth();
  const saver = useSettingsSave();
  const { settings } = saver;
  if (settings.isLoading) return <p role="status">Loading…</p>;
  if (settings.isError || !settings.data) return <p role="alert" className="form-error">{errorText(settings.error)}</p>;
  return <FulltextForm key={settings.data.current.version} data={settings.data} admin={hasRole(user, "admin")} saver={saver} />;
}
