import { useQueryClient } from "@tanstack/react-query";
import { useState, type KeyboardEvent } from "react";
import { Link, useParams } from "react-router-dom";

import { ApiError } from "../api/client";
import { keys, useRatingNext, useRatingSample, useReveal, useSubmitRatings } from "../api/hooks";
import type { RatingAnswerIn, RatingNextOut, RevealOut } from "../api/types";
import { Skeleton } from "../components/ui/Skeleton";

type Answer = RatingAnswerIn["answer"];
const ANSWERS: { value: Answer; label: string; key: string }[] = [
  { value: "yes", label: "Yes", key: "1" }, { value: "no", label: "No", key: "2" },
  { value: "unclear", label: "Unclear", key: "3" }, { value: "not_reported", label: "Not reported", key: "4" },
];
const answerWord = (a: string) => ANSWERS.find((x) => x.value === a)?.label.toLowerCase() ?? a.replace(/_/g, " ");
const idOf = (reviewer: string, item: string) => `${reviewer}|${item}`;

function SampleProgress({ sampleId }: { sampleId: string }) {
  const sample = useRatingSample(sampleId);
  const s = sample.data;
  return (
    <section aria-label="Sample progress" className="rate-progress">
      {s ? (
        <>
          <p><strong>{s.complete_papers} of {s.papers.length} papers have {s.raters_needed} raters</strong> · you rated {s.my_rated} · {s.raters_needed} raters per paper recommended</p>
          <progress max={s.papers.length} value={s.complete_papers} aria-label="Papers with enough raters" />
        </>
      ) : <p>Loading the sample…</p>}
    </section>
  );
}

function Reveal({ reveal }: { reveal: RevealOut }) {
  return (
    <section aria-label="You and the model" className="reveal">
      <h2>You and the model agree on {reveal.agreed} of {reveal.compared} items</h2>
      <p className="lede-sm">Your ratings are saved. Disagreement is not your mistake by default: the human consensus is the reference, the model is what is being checked.</p>
      <table className="data-table">
        <caption className="sr-only">Your answers and the model's, per item</caption>
        <thead><tr><th scope="col">Item</th><th scope="col">You</th><th scope="col">Model</th><th scope="col">Result</th></tr></thead>
        <tbody>
          {reveal.items.map((i) => (
            <tr key={idOf(i.reviewer, i.item)} className={i.agree === false ? "is-disagree" : undefined}>
              <th scope="row" className="item-text">{i.text}<span className="sub">{i.reviewer}</span></th>
              <td>{answerWord(i.mine.answer)}{i.mine.quote && <q className="quote">{i.mine.quote}</q>}</td>
              <td>{i.model ? <>{answerWord(i.model.answer)}{i.model.quote && <q className="quote">{i.model.quote}</q>}</> : "no answer"}</td>
              <td>{i.agree === null ? "not compared" : i.agree ? <span className="agree"><span aria-hidden="true">✓ </span>agree</span> : <strong className="disagree"><span aria-hidden="true">≠ </span>disagree</strong>}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}

function RateForm({ sampleId, next, onSubmitted }: { sampleId: string; next: RatingNextOut; onSubmitted: (paperId: string) => void }) {
  const [answers, setAnswers] = useState<Record<string, Answer>>({});
  const [quotes, setQuotes] = useState<Record<string, string>>({});
  const [problem, setProblem] = useState<string | null>(null);
  const submit = useSubmitRatings(sampleId);
  const paper = next.paper!;
  const all = next.reviewers.flatMap((r) => r.items.map((i) => ({ reviewer: r.key, item: i.key, text: i.text })));
  const answered = all.filter((i) => answers[idOf(i.reviewer, i.item)]).length;

  const onKey = (id: string) => (event: KeyboardEvent) => {
    const choice = ANSWERS.find((a) => a.key === event.key);
    if (!choice || (event.target as HTMLElement).tagName === "TEXTAREA" || (event.target as HTMLInputElement).type === "text") return;
    event.preventDefault();
    setAnswers((a) => ({ ...a, [id]: choice.value }));
  };
  const send = async () => {
    setProblem(null);
    try {
      await submit.mutateAsync({
        paper_id: paper.paper_id,
        answers: all.map((i) => ({ reviewer: i.reviewer, item: i.item, answer: answers[idOf(i.reviewer, i.item)]!, quote: (quotes[idOf(i.reviewer, i.item)] ?? "").trim() })),
      });
      onSubmitted(paper.paper_id);
    } catch (error) {
      setProblem(error instanceof ApiError ? (error.status === 409 ? "You already rated this paper. Go to the next one." : error.message) : "Could not reach the server.");
    }
  };

  return (
    <div className="rate-layout">
      <article className="rate-paper">
        <p className="kicker">Paper {next.position} of {next.total}</p>
        <h1>{paper.title}</h1>
        <p className="report-meta">{paper.paper_id}{paper.year ? ` · ${paper.year}` : ""} · <span className="source-tag">{paper.text.source === "abstract" ? "Abstract only" : "Full text"}</span> · {paper.text.chars.toLocaleString("en-US")} characters</p>
        <section aria-label="Paper text" className="reading-text rate-text" tabIndex={0}>{paper.text.content}</section>
      </article>
      <div className="rate-checklist">
        <p className="hint">Answer from the text only. Keys: <kbd>1</kbd> yes · <kbd>2</kbd> no · <kbd>3</kbd> unclear · <kbd>4</kbd> not reported, on the focused item; arrows move between answers. The models' answers stay hidden until you submit.</p>
        {next.reviewers.map((r) => (
          <section key={r.key} aria-label={`${r.name} checklist`} className="rate-reviewer">
            <h2>{r.name} <span className="sub-inline">version {r.version}</span></h2>
            {r.items.map((i) => {
              const id = idOf(r.key, i.key);
              return (
                <div key={id} className={`rate-item${answers[id] ? " is-answered" : ""}`}>
                  <div role="radiogroup" aria-label={i.text} onKeyDown={onKey(id)} className="answer-group">
                    <p className="rate-item-text" aria-hidden="true">{i.text}</p>
                    {ANSWERS.map((a) => (
                      <label key={a.value} className={`answer-option${answers[id] === a.value ? " is-checked" : ""}`}>
                        <input type="radio" name={id} value={a.value} checked={answers[id] === a.value} onChange={() => setAnswers((x) => ({ ...x, [id]: a.value }))} />
                        <kbd aria-hidden="true">{a.key}</kbd> {a.label}
                      </label>
                    ))}
                  </div>
                  <label className="quote-input"><span className="sr-only">Quote for: {i.text}</span><span className="hint" aria-hidden="true">Supporting quote (optional)</span>
                    <input type="text" value={quotes[id] ?? ""} onChange={(e) => setQuotes((q) => ({ ...q, [id]: e.target.value }))} placeholder="Paste the sentence that answers it" />
                  </label>
                </div>
              );
            })}
          </section>
        ))}
        <div className="rate-submit">
          <span aria-live="polite">{answered} of {all.length} items answered</span>
          <button type="button" className="primary" disabled={answered < all.length || submit.isPending} onClick={send}>Submit ratings and reveal</button>
        </div>
        {problem && <p role="alert" className="form-error">{problem}</p>}
      </div>
    </div>
  );
}

export function RatePage() {
  const { sampleId = "" } = useParams();
  const next = useRatingNext(sampleId);
  const sample = useRatingSample(sampleId);
  const client = useQueryClient();
  const [revealed, setRevealed] = useState<string | null>(null);
  const reveal = useReveal(sampleId, revealed);
  const goNext = () => {
    setRevealed(null);
    void client.invalidateQueries({ queryKey: keys.ratingNext(sampleId) });
  };
  const back = <nav aria-label="Breadcrumb" className="crumbs"><Link to={sample.data ? `/evals/${sample.data.eval_id}` : "/evals"}>← Panel report</Link></nav>;

  let body;
  if (next.isLoading) body = <Skeleton label="the next paper" rows={6} />;
  else if (next.isError || !next.data) body = <p role="alert" className="form-error">{next.error instanceof ApiError ? next.error.message : "Could not load the next paper."}</p>;
  else if (revealed) {
    body = (
      <>
        {reveal.data ? <Reveal reveal={reveal.data} /> : reveal.isError ? <p role="alert" className="form-error">Saved, but the comparison could not be loaded.</p> : <Skeleton label="the comparison" rows={3} />}
        <button type="button" className="primary" onClick={goNext} autoFocus>Next paper</button>
      </>
    );
  } else if (next.data.done || !next.data.paper) {
    body = (
      <div className="empty-state">
        <p className="empty-title">You have rated every paper in this sample. Thank you.</p>
        {sample.data?.latest_human_eval_id && <p><Link to={`/evals/${sample.data.latest_human_eval_id}`}>Open the latest human reference report</Link></p>}
      </div>
    );
  } else {
    body = <RateForm key={next.data.paper.paper_id} sampleId={sampleId} next={next.data} onSubmitted={setRevealed} />;
  }
  return (
    <section className="rate-page">
      {back}
      <SampleProgress sampleId={sampleId} />
      {body}
    </section>
  );
}
