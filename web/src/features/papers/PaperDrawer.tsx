import { useEffect, useRef, useState, type ReactNode } from "react";

import { ApiError } from "../../api/client";
import { usePaper } from "../../api/hooks";
import { hasRole, type DrawerOut, type ReviewOut } from "../../api/types";
import { useAuth } from "../../auth/AuthProvider";
import { RawCalls } from "./RawCalls";

const ROLE_LABEL: Record<string, string> = { a: "Reviewer A", b: "Reviewer B", adjudicator: "Adjudicator" };
const JEV_MEANING: Record<string, string> = {
  include: "Jev was confident the paper matches.",
  exclude: "Jev was confident the paper does not match, so it was dropped without asking the LLM.",
  escalate: "Jev was not confident, so the LLM decided.",
};
const detailText = (review: ReviewOut, key: string) => (typeof review.detail[key] === "string" ? (review.detail[key] as string) : null);
const detailList = (review: ReviewOut, key: string) => (Array.isArray(review.detail[key]) ? (review.detail[key] as string[]) : []);

function Step({ title, tone, children }: { title: string; tone: "ok" | "warn" | "neutral"; children: ReactNode }) {
  return (
    <section className={`step step--${tone}`}>
      <h3>{title}</h3>
      {children}
    </section>
  );
}

function Timeline({ drawer }: { drawer: DrawerOut }) {
  const { screening } = drawer;
  return (
    <div className="timeline">
      <Step title="Search" tone="ok">
        <p>{drawer.found_by === "lookup" ? "Found by direct lookup of the systematic review's reference, not by the search query." : "Found by the search query."}</p>
      </Step>
      <Step title="Screen" tone={screening.jev_decision === "escalate" ? "warn" : "ok"}>
        {screening.criteria.map((c) => (
          <p key={c.key}>{c.key}: <strong>{c.probability.toFixed(2)}</strong> <span className="sub">{c.jev_version}</span></p>
        ))}
        {screening.jev_decision && <p>{JEV_MEANING[screening.jev_decision]}</p>}
        {screening.jev_decision && <p className="sub">Auto-drop needs p ≤ 0.05 at the shipped default thresholds.</p>}
        {screening.llm_decision && <p>LLM screen: <strong>{screening.llm_decision}</strong></p>}
        <p className="sub">{screening.reason}</p>
      </Step>
      <Step title="Extract" tone="ok">
        {drawer.claims.length === 0 ? <p>No extraction for this paper in this run.</p> : drawer.claims.map((claim, index) => (
          <blockquote key={index}>“{claim.quote}”<footer>{claim.statement}</footer></blockquote>
        ))}
      </Step>
      <Step title="Reviewers" tone="warn">
        {drawer.reviews.length === 0 ? <p>No reviews for this paper in this run.</p> : drawer.reviews.map((review) => (
          <div key={review.role} className="review">
            <p><strong>{ROLE_LABEL[review.role] ?? review.role}</strong> <span className={`chip verdict--${review.verdict}`}>{review.verdict}</span> <span className="sub">relevance {review.relevance} · methods {review.methods} · support {review.support}</span></p>
            {detailText(review, "assessment") && <p>{detailText(review, "assessment")}</p>}
            {detailText(review, "reason") && <p>{detailText(review, "reason")}</p>}
            {(detailList(review, "strengths").length > 0 || detailList(review, "weaknesses").length > 0) && (
              <details><summary>Strengths and weaknesses</summary>
                <ul>{detailList(review, "strengths").map((s) => <li key={s}>+ {s}</li>)}{detailList(review, "weaknesses").map((w) => <li key={w}>− {w}</li>)}</ul>
              </details>
            )}
          </div>
        ))}
      </Step>
      <Step title="Rank" tone="neutral"><p>{drawer.rank ? `Rank ${drawer.rank.position} · score ${drawer.rank.score.toFixed(0)}` : "Not ranked."}</p></Step>
      {drawer.in_sr !== null && (
        <Step title="SR label" tone="ok">
          <p>{drawer.in_sr ? "Included by the systematic review" : "Not in the systematic review"}{drawer.label_source ? ` (${drawer.label_source})` : ""}.</p>
        </Step>
      )}
    </div>
  );
}

export function PaperDrawer({ runId, paperId, onClose }: { runId: string; paperId: string; onClose: () => void }) {
  const { user } = useAuth();
  const paper = usePaper(runId, paperId);
  const [section, setSection] = useState<"overview" | "abstract" | "calls">("overview");
  const heading = useRef<HTMLHeadingElement>(null);
  useEffect(() => {
    heading.current?.focus();
  }, [paper.data?.paper.id]);

  return (
    <aside aria-label="Paper details" className="side-panel" onKeyDown={(event) => event.key === "Escape" && onClose()}>
      <div className="panel-head">
        {paper.data ? <h2 ref={heading} tabIndex={-1}>{paper.data.paper.title}</h2> : <h2 ref={heading} tabIndex={-1}>Loading…</h2>}
        <button type="button" onClick={onClose} aria-label="Close paper details">×</button>
      </div>
      {paper.isError && <p role="alert" className="form-error">{paper.error instanceof ApiError ? `${paper.error.message} (request ${paper.error.requestId})` : "Could not load this paper."}</p>}
      {paper.data && (
        <>
          <p className="sub">{paper.data.paper.year ?? ""} · {paper.data.paper.source_id}{paper.data.paper.doi ? ` · ${paper.data.paper.doi}` : ""}</p>
          <div role="group" aria-label="Drawer sections" className="sections">
            <button type="button" aria-pressed={section === "overview"} onClick={() => setSection("overview")}>Overview</button>
            <button type="button" aria-pressed={section === "abstract"} onClick={() => setSection("abstract")}>Abstract</button>
            {hasRole(user, "member") && <button type="button" aria-pressed={section === "calls"} onClick={() => setSection("calls")}>Raw calls</button>}
          </div>
          {section === "overview" && <Timeline drawer={paper.data} />}
          {section === "abstract" && <p className="abstract">{paper.data.paper.abstract || "No abstract available."}</p>}
          {section === "calls" && <RawCalls runId={runId} drawer={paper.data} />}
        </>
      )}
    </aside>
  );
}
