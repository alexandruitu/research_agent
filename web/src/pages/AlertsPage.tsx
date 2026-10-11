import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";

import { ApiError } from "../api/client";
import { useDigests, useMarkDigestRead } from "../api/hooks";
import { hasRole, type DigestCounts, type DigestOut } from "../api/types";
import { useAuth } from "../auth/AuthProvider";
import { EmptyState } from "../components/ui/EmptyState";
import { Skeleton } from "../components/ui/Skeleton";
import { QualityCell } from "../features/papers/cells";
import { useSaveFlow } from "../features/library/saveFlow";

const errorText = (error: unknown) => (error instanceof ApiError ? error.message : "Could not reach the server.");
const MAX_ITEMS = 10;

/** "14 found · 9 already seen · 5 new · 2 worth reading" (+ over the cap, deferred). */
export function countsSentence(counts: DigestCounts, worth: number): string[] {
  const parts = [`${counts.found ?? 0} found`, `${counts.already_seen ?? 0} already seen`, `${counts.new ?? 0} new`, `${worth} worth reading`];
  const lines = [parts.join(" · ")];
  if (counts.over_cap) lines.push(`${counts.over_cap} more not reviewed — run the topic to see them.`);
  if (counts.deferred) lines.push("This run was deferred: the daily limit of alert runs was reached.");
  return lines;
}

function DigestCard({ digest, member }: { digest: DigestOut; member: boolean }) {
  const mark = useMarkDigestRead();
  const { save, pending } = useSaveFlow();
  const ref = useRef<HTMLElement>(null);
  const [marked, setMarked] = useState(digest.read);
  const counts = digest.counts as DigestCounts;
  // Read once it has been on screen (or opened): one POST per digest.
  useEffect(() => {
    if (marked) return;
    const node = ref.current;
    const markRead = () => {
      setMarked(true);
      mark.mutate(digest.id);
    };
    if (!node || typeof IntersectionObserver === "undefined") return markRead();
    const observer = new IntersectionObserver((entries) => {
      if (entries.some((e) => e.isIntersecting)) {
        observer.disconnect();
        markRead();
      }
    });
    observer.observe(node);
    return () => observer.disconnect();
  }, [marked, digest.id, mark]);
  const date = new Date(digest.created_at);
  const items = digest.items.slice(0, MAX_ITEMS);
  return (
    <article ref={ref} className="digest-card" aria-labelledby={`digest-${digest.id}`}>
      <header className="digest-head">
        <h2 id={`digest-${digest.id}`}><Link to={`/topics/${digest.field_id}`}>{digest.field_name}</Link></h2>
        <time dateTime={digest.created_at}>{date.toLocaleString()}</time>
        {!digest.read && <span className="chip chip--warn">New<span className="sr-only"> (unread)</span></span>}
      </header>
      {digest.status === "failed" ? (
        <p className="banner banner--bad">The alert run failed{digest.reason ? `: ${digest.reason}` : "."}</p>
      ) : (
        countsSentence(counts, counts.in_digest ?? digest.items.length).map((line) => <p key={line} className="digest-counts">{line}</p>)
      )}
      {digest.status !== "failed" && items.length === 0 && <p className="sub">Nothing new worth reading this time.</p>}
      {items.length > 0 && (
        <ul className="digest-items">
          {items.map((item) => (
            <li key={item.paper_id}>
              <div className="digest-item-head">
                <QualityCell group={item.group} />
                <strong>{item.title}</strong>{item.year ? <span className="sub"> ({item.year})</span> : null}
              </div>
              {item.why && <p className="digest-why">{item.why}</p>}
              {digest.run_id && (
                <div className="actions">
                  <Link to={`/results?run=${digest.run_id}&paper=${item.paper_id}`} aria-label={`Open ${item.title}`}>Open</Link>
                  <Link to={`/read/${digest.run_id}/${item.paper_id}`} aria-label={`Read ${item.title}`}>Read</Link>
                  {member && <button type="button" disabled={pending} aria-label={`Save to library: ${item.title}`} onClick={() => void save(digest.run_id!, [item.paper_id], { status: "to_read", note: "" })}>Save to library</button>}
                </div>
              )}
            </li>
          ))}
        </ul>
      )}
      {digest.items.length > MAX_ITEMS && digest.run_id && <p className="sub"><Link to={`/results?run=${digest.run_id}`}>See all {digest.items.length} in the run</Link></p>}
    </article>
  );
}

export function AlertsPage() {
  const { user } = useAuth();
  const admin = hasRole(user, "admin");
  const member = hasRole(user, "member");
  const [scope, setScope] = useState<"following" | "all">("following");
  const digests = useDigests(scope);
  return (
    <section className="alerts-page">
      <div className="page-head">
        <h1>Alerts</h1>
        {admin && (
          <label>Show{" "}
            <select value={scope} onChange={(e) => setScope(e.target.value === "all" ? "all" : "following")}>
              <option value="following">Alerts I follow</option>
              <option value="all">Every alert</option>
            </select>
          </label>
        )}
      </div>
      <p className="sub">What the alerts you follow found since their last run, newest first.</p>
      {digests.isLoading ? <Skeleton label="the alerts" rows={4} />
        : digests.isError ? <p role="alert" className="form-error">{errorText(digests.error)}</p>
        : (digests.data?.digests ?? []).length === 0 ? (
          <EmptyState title="No alert digests yet">
            Turn on an alert on a field page, or follow someone else’s; each alert run leaves a digest here.
          </EmptyState>
        ) : (
          <div className="digest-list">
            {digests.data!.digests.map((d) => <DigestCard key={d.id} digest={d} member={member} />)}
          </div>
        )}
    </section>
  );
}
