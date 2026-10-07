import { useReviewerVersion } from "../../api/hooks";
import type { PanelOut, PanelReportOut } from "../../api/types";
import { coverageWords } from "./cells";
import { answerJudgement, answerParts, disagreementSentence, listWords, reviewerNames, textSentence, verdictWord } from "./panel";
import { Term } from "../../components/ui/Term";
import { FlagLine } from "./RedFlag";

/** A score from under half of the checklist is provisional: said in words before the (tentative) number. */
const scoreText = (score: number | null, coverage: number | null) => {
  const provisional = coverage != null && coverage < 0.5;
  const value = score == null ? "no score" : provisional ? `provisional (tentative score ${Math.round(score)})` : `score ${Math.round(score)}`;
  return `${value}${coverage == null ? "" : ` · ${coverageWords(coverage)}`}`;
};

const JUDGEMENT = { meets: { icon: "●", word: "meets" }, concern: { icon: "▲", word: "concern" } } as const;

function Checklist({ report }: { report: PanelReportOut }) {
  // the exact version the reviewer used says which answer passes each item
  const version = useReviewerVersion(report.key, report.version);
  const passIf = Object.fromEntries((version.data?.items ?? []).map((item) => [item.key, item.pass_if]));
  return (
    <table className="criteria-table checklist-table">
      <caption>{report.name}'s checklist</caption>
      <thead><tr><th scope="col">Item</th><th scope="col">Answer<span className="sub">meets or concern for the paper</span></th><th scope="col">Evidence</th></tr></thead>
      <tbody>
        {report.answers.map((a) => {
          const { icon, word } = answerParts(a.answer);
          const judgement = answerJudgement(a.answer, passIf[a.key]);
          return (
            <tr key={a.key} className={a.red_flag ? "is-red-flag" : undefined}>
              <th scope="row">
                <span className="item-key">{a.key}</span> {a.text ?? ""}
                {(a.source || a.weight) && <span className="sub">{[a.source, a.weight ? `weight ${a.weight}` : null].filter(Boolean).join(" · ")}</span>}
              </th>
              <td className={`answer answer--${a.answer}`}>
                <span aria-hidden="true">{icon}</span> {word}
                {judgement && <span className={`judgement judgement--${judgement}`}> · <span aria-hidden="true">{JUDGEMENT[judgement].icon}</span> {JUDGEMENT[judgement].word}</span>}
                {a.red_flag && <strong className="red-flag-word"> ⚑ red flag{a.flag ? `: ${a.flag}` : ""}</strong>}
              </td>
              <td>{a.quote ? <blockquote className="quote">“{a.quote}”{a.section && <footer>{a.section}</footer>}</blockquote> : <span className="na">no quote</span>}</td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

function ReviewerReport({ report }: { report: PanelReportOut }) {
  return (
    <details className="reviewer-report">
      <summary>
        <strong>{report.name}</strong> <span className="sub">v{report.version}</span>{" "}
        <span className={`chip verdict--${report.verdict}`}>{verdictWord(report.verdict)}</span>{" "}
        <span className="sub">{scoreText(report.score, report.coverage)}</span>
      </summary>
      {report.summary && <p>{report.summary}</p>}
      {(report.strengths.length > 0 || report.weaknesses.length > 0) && (
        <ul className="plus-minus">
          {report.strengths.map((s) => <li key={`+${s}`}><span aria-hidden="true">+</span> <span className="sr-only">Strength:</span> {s}</li>)}
          {report.weaknesses.map((w) => <li key={`-${w}`}><span aria-hidden="true">−</span> <span className="sr-only">Weakness:</span> {w}</li>)}
        </ul>
      )}
      <Checklist report={report} />
    </details>
  );
}

/** The Peer review step: the editor's decision first, then each reviewer's report, then the red flags. */
export function PeerReview({ panel }: { panel: PanelOut }) {
  const names = reviewerNames(panel);
  const { editor } = panel;
  return (
    <div className="peer-review">
      <p className="sub">{textSentence(panel)}</p>
      <div className="editor-verdict">
        <p className="editor-line">
          <span className="sub"><Term k="editor_verdict">Editor's decision</Term></span>{" "}
          <span className={`verdict-badge verdict-badge--${editor.verdict ?? "none"}`}>{verdictWord(editor.verdict)}</span>{" "}
          <span className="panel-total">{scoreText(panel.score, panel.coverage)}</span>
        </p>
        {editor.reason && <p>{editor.reason}</p>}
        {editor.disagreements.length > 0 ? (
          <div className="disagreements">
            <p><strong>Where the reviewers disagree</strong></p>
            <ul>{editor.disagreements.map((d, i) => <li key={`${d.item}-${i}`}>{disagreementSentence(panel, d)}</li>)}</ul>
          </div>
        ) : panel.reviews.length > 1 && <p className="sub">The reviewers agree.</p>}
      </div>
      {panel.red_flags.length > 0 && (
        <div className="red-flags">
          <p><strong>⚑ {panel.red_flags.length} red flag{panel.red_flags.length === 1 ? "" : "s"}</strong></p>
          <ul>
            {panel.red_flags.map((flag, i) => (
              <li key={`${flag.text}-${i}`}>
                <FlagLine flag={flag} evidence={<>
                  <span className="sub"> raised by {listWords(flag.raised_by.map((r) => names[r.reviewer] ?? r.reviewer))}</span>
                  {flag.raised_by.filter((r) => r.quote).map((r, j) => (
                    <blockquote key={j} className="quote"><span className="sub">Evidence: </span>“{r.quote}”<footer>{names[r.reviewer] ?? r.reviewer}{r.section ? ` · ${r.section}` : ""}</footer></blockquote>
                  ))}
                </>} />
              </li>
            ))}
          </ul>
        </div>
      )}
      <p className="sub reviewers-label">Reports ({panel.reviews.length}) — open one to read its checklist</p>
      {panel.reviews.map((report) => <ReviewerReport key={report.key} report={report} />)}
      <p className="sub">Scores and red flags are computed by code from the answers; quotes are checked against the text.</p>
    </div>
  );
}
