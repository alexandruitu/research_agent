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
  return (
    <span className="topic">
      <span>{criteriaText(screen)}</span>{badges}
      <CriteriaValues screen={screen} />
    </span>
  );
}

/** One line per criterion: its label, Jev's probability and the LLM's answer, never truncated; the
 * criterion that decided is marked with "◆ decided" (a word, not a colour). */
export function CriteriaValues({ screen }: { screen: Screen }) {
  const keys = screenKeys(screen);
  if (keys.length === 0) return null;
  return (
    <ul className="crit-values" aria-label="Criteria values">
      {keys.map((key) => {
        const cell = screen.cells?.[key];
        const p = cell?.jev_p ?? screen.criteria[key] ?? null;
        const decided = screen.decided_by === key;
        return (
          <li key={key} className={decided ? "is-decider" : undefined}>
            <span className="crit-key">{criterionLabel(key)}</span>
            {p !== null && <span className="crit-p">p {p.toFixed(2)}</span>}
            {cell?.llm && <span className="crit-llm">LLM {cell.llm}</span>}
            {p === null && !cell?.llm && <span className="na">not scored</span>}
            {decided && <span className="crit-decided">◆ decided</span>}
          </li>
        );
      })}
    </ul>
  );
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

const TEXT_SOURCE: Record<string, string> = {
  pmc_oa: "PMC", europepmc: "Europe PMC", core: "CORE", springer_oa: "Springer Nature OA", semantic_scholar_oa: "Semantic Scholar",
  unpaywall: "Unpaywall", ieee: "IEEE Xplore", sciencedirect: "ScienceDirect", upload: "uploaded PDF",
};
export const textSourceLabel = (source: string) => (source === "abstract" ? "abstract only" : `full text · ${TEXT_SOURCE[source] ?? source}`);

/** Coverage is the share of checklist items the reviewers could answer, in tenths ("8/10 answered"). */
export const coverageWords = (coverage: number) => `${Math.round(coverage * 10)}/10 answered`;

type PanelScoreProps = {
  score: number | null | undefined; coverage: number | null | undefined;
  /** Under half of the checklist answered (API `provisional`): the score may move once the full text is read. */
  provisional?: boolean | null; answered?: number | null; total?: number | null;
};

export const provisionalTitle = (answered: number | null | undefined, total: number | null | undefined) =>
  answered != null && total != null
    ? `Only ${answered} of ${total} checklist items could be answered (abstract only) — upload the full text to firm this up`
    : "Under half of the checklist items could be answered (abstract only) — upload the full text to firm this up";

export function PanelScoreCell({ score, coverage, provisional, answered, total }: PanelScoreProps) {
  if (score == null && coverage == null) return <NotApplicable />;
  return (
    <span className="panel-score">
      <strong>{score == null ? "no score" : Math.round(score)}</strong>
      {provisional && <span className="chip chip--warn provisional" title={provisionalTitle(answered, total)}>provisional</span>}
      {coverage != null && (
        <>
          <span className="sub"> · {coverageWords(coverage)}</span>
          <meter min={0} max={1} low={0.5} optimum={1} value={coverage} aria-label={`coverage ${Math.round(coverage * 100)}%`} />
        </>
      )}
    </span>
  );
}

export function RedFlagsCell({ count }: { count: number | null | undefined }) {
  if (count == null) return <NotApplicable />;
  if (count === 0) return <span className="sub">none</span>;
  return <span className="chip chip--bad">⚑ {count} red flag{count === 1 ? "" : "s"}</span>;
}

export function TextSourceCell({ source }: { source: string | null | undefined }) {
  if (!source) return <NotApplicable />;
  return <span className={source === "abstract" ? "chip chip--warn" : "chip chip--ok"}>{textSourceLabel(source)}</span>;
}

/** A run reviewed by the panel carries a score, coverage or text source on at least one row. */
export const isPanelRun = (rows: PaperRow[]) => rows.some((row) => row.text_source != null || row.score != null || row.coverage != null);
