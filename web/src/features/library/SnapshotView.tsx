import { Link } from "react-router-dom";

import { verdictWord } from "../papers/panel";
import { FlagLine } from "../papers/RedFlag";
import { criterionLabel } from "../fields/labels";
import { textSourceLabel } from "../papers/cells";

type Row = { key: string; text?: string; kind?: string; decided?: boolean; jev_p?: number | null; llm?: string | null; quote?: string | null };
type Snapshot = {
  taken_at?: string;
  run?: { id?: string; kind?: string; created_at?: string };
  field?: { name?: string; version?: number | null };
  screening?: { decision?: string; tier?: string; reason?: string; decided_by?: string | null; criteria_table?: Row[] | null };
  rank?: { score?: number; position?: number } | null;
  panel?: {
    score?: number | null; coverage?: number | null; red_flag_count?: number; text_source?: string;
    editor?: { verdict?: string | null; reason?: string | null };
    red_flags?: { text: string; item_text?: string | null; source?: string | null; quote?: string; section?: string }[];
    reviewers?: { key: string; name: string; version?: number; verdict?: string | null; score?: number | null; summary?: string | null }[];
  } | null;
};

const DECISION: Record<string, string> = { include: "kept", exclude: "dropped", uncertain: "unsure" };
const when = (iso?: string) => (iso ? new Date(iso).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" }) : "unknown time");

/** The evidence frozen when the paper was saved: what screening and the panel said then. */
export function SnapshotView({ snapshot }: { snapshot: Record<string, unknown> }) {
  const s = snapshot as Snapshot;
  const rows = s.screening?.criteria_table ?? [];
  const panel = s.panel;
  return (
    <div className="snapshot">
      <p className="hint">
        Frozen {when(s.taken_at)} from {s.field?.name ?? "a run"}{s.field?.version ? ` v${s.field.version}` : ""}
        {s.run?.id && <> · <Link to={`/?run=${s.run.id}`}>open that run</Link></>}
      </p>
      <section className="snap-block">
        <h3>Screening</h3>
        <p><strong>{DECISION[s.screening?.decision ?? ""] ?? s.screening?.decision ?? "no decision"}</strong>{s.screening?.decided_by ? ` · decided by ${criterionLabel(s.screening.decided_by)}` : ""}{s.screening?.tier ? ` · ${s.screening.tier === "llm" ? "LLM" : s.screening.tier === "jev" ? "Jev" : s.screening.tier}` : ""}</p>
        {rows.length > 0 && (
          <ul className="snap-criteria">
            {rows.map((r) => <li key={r.key}><span className="item-key">{criterionLabel(r.key)}:</span> {r.text}{r.decided && <strong> (decided)</strong>}{r.quote ? <blockquote className="quote">“{r.quote}”</blockquote> : null}</li>)}
          </ul>
        )}
        {rows.length === 0 && s.screening?.reason && <p className="sub">{s.screening.reason}</p>}
      </section>
      {panel ? (
        <section className="snap-block">
          <h3>Peer review</h3>
          <p className="editor-line">
            <span className="sub">Editor</span>{" "}
            <span className={`verdict-badge verdict-badge--${panel.editor?.verdict ?? "none"}`}>{verdictWord(panel.editor?.verdict)}</span>{" "}
            <span className="panel-total">{panel.score == null ? "no score" : `score ${Math.round(panel.score)}`}</span>
            {panel.text_source && <span className="sub"> · {textSourceLabel(panel.text_source)}</span>}
          </p>
          {panel.editor?.reason && <p>{panel.editor.reason}</p>}
          {(panel.red_flags ?? []).length > 0 ? (
            <div className="red-flags">
              <p><strong><span aria-hidden="true">⚑</span> {panel.red_flags!.length} red flag{panel.red_flags!.length === 1 ? "" : "s"}</strong></p>
              <ul>{panel.red_flags!.map((f, i) => <li key={i}><FlagLine flag={f} /></li>)}</ul>
            </div>
          ) : <p className="sub">No red flags.</p>}
          <ul className="snap-reviewers">
            {(panel.reviewers ?? []).map((r) => (
              <li key={r.key}><strong>{r.name}</strong> <span className="sub">v{r.version}</span> · {verdictWord(r.verdict)}{r.score != null ? ` · ${Math.round(r.score)}` : ""}{r.summary && <p>{r.summary}</p>}</li>
            ))}
          </ul>
        </section>
      ) : (
        <section className="snap-block">
          <h3>Ranking</h3>
          <p>{s.rank ? `Rank ${s.rank.position} · score ${Math.round(s.rank.score ?? 0)}` : "Not ranked in that run."}</p>
        </section>
      )}
    </div>
  );
}
