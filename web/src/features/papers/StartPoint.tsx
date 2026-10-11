import { Link } from "react-router-dom";

export const PURPOSE = "Find, screen and appraise papers for your topic — every decision explained.";

/** Where a new literature search starts: the Runs start form preselecting the last used field, else a new field. */
export const startSearchHref = (lastFieldId: string | null | undefined) => (lastFieldId ? `/screening?field=${encodeURIComponent(lastFieldId)}` : "/topics/new");

/** The purpose line and, for members, the primary action. */
export function StartPoint({ member, lastFieldId }: { member: boolean; lastFieldId: string | null | undefined }) {
  return (
    <div className="start-point">
      <p className="purpose">{PURPOSE}</p>
      {member && <Link className="button-link" to={startSearchHref(lastFieldId)}>Start a literature search</Link>}
    </div>
  );
}
