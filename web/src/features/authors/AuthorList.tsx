import type { AuthorOut } from "../../api/types";
import { authorLine, isIdentified, openalexUrl, orcidUrl } from "./authors";

/** The first three authors and "et al." on one line (rows and cards). Nothing when none are stored. */
export function AuthorLine({ authors, count }: { authors: AuthorOut[] | undefined; count?: number | null }) {
  const line = authorLine(authors ?? [], count ?? undefined);
  if (!line) return null;
  return <span className="author-line" title={line}><span className="sr-only">Authors: </span>{line}</span>;
}

function External({ href, children, label }: { href: string; children: string; label: string }) {
  return (
    <a href={href} target="_blank" rel="noopener noreferrer" className="author-id" aria-label={`${label} (opens in a new tab)`}>
      {children}<span aria-hidden="true"> ↗</span>
    </a>
  );
}

/** Every author with affiliations and identifier links (drawer, Reader, library pane). Missing ≠ none. */
export function AuthorDetails({ authors }: { authors: AuthorOut[] | undefined }) {
  if (!authors || authors.length === 0) {
    return <p className="sub authors-missing">Authors not stored yet. An admin can look them up in Settings → Sources.</p>;
  }
  return (
    <ul className="author-details" aria-label="Authors">
      {authors.map((author) => (
        <li key={`${author.position ?? ""}-${author.id}`}>
          <span className="author-name">{author.name}</span>
          {author.orcid && <> <External href={orcidUrl(author.orcid)} label={`ORCID ${author.orcid} of ${author.name}`}>ORCID</External></>}
          {author.openalex_id && <> <External href={openalexUrl(author.openalex_id)} label={`OpenAlex profile of ${author.name}`}>OpenAlex</External></>}
          {!isIdentified(author) && <span className="sub"> (name only)</span>}
          {(author.affiliations ?? []).length > 0 && <span className="sub author-affiliations"> · {(author.affiliations ?? []).join("; ")}</span>}
        </li>
      ))}
    </ul>
  );
}
