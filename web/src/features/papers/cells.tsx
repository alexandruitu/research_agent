import type { PaperRow } from "../../api/types";
import { criterionLabel, isFieldCriterion, sourceLabel } from "../fields/labels";

const VERDICT: Record<string, string> = { include: "inc", exclude: "exc", uncertain: "unc" };
const verdict = (value: string | null) => (value ? (VERDICT[value] ?? value) : "–");

export const NotApplicable = () => <span className="na" aria-label="not applicable">–</span>;
export const Missing = () => <span className="missing" title="Expected data is missing">missing</span>;

export function ExtractCellView({ cell }: { cell: PaperRow["extract"] }) {
  if (cell === null) return <NotApplicable />;
  if ("missing" in cell) return <Missing />;
  return <span>{cell.claims} {cell.quotes_verified ? "verified" : "unverified"}</span>;
}

export function ReviewsCellView({ cell }: { cell: PaperRow["reviews"] }) {
  if (cell === null) return <NotApplicable />;
  if ("missing" in cell) return <Missing />;
  return (
    <span>
      {verdict(cell.a)} / {verdict(cell.b)}
      {cell.adjudicated && <span className="adj"> adj: {verdict(cell.adjudicator)}</span>}
    </span>
  );
}

type Screen = PaperRow["screen"];

/** The keys of every criterion a screen row carries (Jev probabilities and per-criterion cells). */
export const screenKeys = (screen: Screen) => [...new Set([...Object.keys(screen.criteria), ...Object.keys(screen.cells ?? {})])];

/** "dropped by incl 1 (0.01)", "dropped by excl 1 (LLM: yes)", "all met", … */
export function criteriaText(screen: Screen): string {
  const decider = screen.decided_by ?? null;
  if (decider) {
    const cell = screen.cells?.[decider];
    const p = cell?.jev_p ?? screen.criteria[decider];
    const detail = screen.tier === "llm" && cell?.llm ? `LLM: ${cell.llm}` : p != null ? p.toFixed(2) : null;
    const verb = screen.decision === "exclude" ? "dropped by" : "decided by";
    return `${verb} ${criterionLabel(decider)}${detail ? ` (${detail})` : ""}`;
  }
  if (screen.decision === "include") return "all met";
  if (screen.tier === "rule") return "not screened";
  return "no single criterion decided";
}

/** Legacy runs (only topic_match) show the probability as before; field runs name the criterion that decided. */
export function CriteriaCell({ screen }: { screen: Screen }) {
  const keys = screenKeys(screen);
  if (keys.length === 0) return <NotApplicable />;
  const badges = (
    <>
      {screen.tier === "jev" && <span className="chip chip--ok">Jev</span>}
      {screen.jev_decision === "escalate" && <span className="chip chip--warn">escalated</span>}
    </>
  );
  if (!keys.some(isFieldCriterion)) {
    return (
      <span className="topic">
        {keys.map((key) => {
          const p = screen.criteria[key] ?? screen.cells?.[key]?.jev_p ?? null;
          const text = p === null ? "–" : p.toFixed(2);
          return <strong key={key}>{keys.length > 1 ? `${key} ${text}` : text}</strong>;
        })}
        {badges}
      </span>
    );
  }
  return <span className="topic"><span>{criteriaText(screen)}</span>{badges}</span>;
}

const DECISION: Record<string, string> = { include: "keep", exclude: "drop", uncertain: "unsure" };
const TIER: Record<string, string> = { jev: "Jev", llm: "LLM", rule: "no abstract" };

export function DecisionCell({ screen }: { screen: Screen }) {
  return (
    <span>
      <span className={`decision decision--${screen.decision}`}>{DECISION[screen.decision] ?? screen.decision}</span>{" "}
      <span className="chip">{TIER[screen.tier] ?? screen.tier}</span>
    </span>
  );
}

export const InSrCell = ({ value }: { value: boolean | null }) => (value === null ? <NotApplicable /> : <span>{value ? "yes" : "no"}</span>);
export const ScoreCell = ({ rank }: { rank: PaperRow["rank"] }) => (rank ? <span>{rank.score.toFixed(0)}</span> : <NotApplicable />);

export function FoundByCell({ foundBy, sources = [] }: { foundBy: string; sources?: string[] }) {
  if (sources.length === 0) return <span>{foundBy}</span>;
  return <span>{sources.map(sourceLabel).join(", ")}{foundBy === "lookup" && <span className="sub">lookup</span>}</span>;
}
