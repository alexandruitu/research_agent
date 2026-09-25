"""Match SR-included studies to Europe PMC records and build a frozen gold set."""

import re
from datetime import UTC, datetime

from ..connectors import deduplicate, normalize_doi
from .gold import GoldCandidate, GoldSet, UnmatchedStudy


class GoldBuildError(RuntimeError):
    """Nothing measurable: no included study could be resolved."""


def norm_title(title):
    return re.sub(r"\W+", " ", title.casefold()).strip()


def matches(ref, paper):
    """DOI equality when both sides have a DOI (conflicting DOIs never match); else title (+ year)."""
    if ref.doi and paper.doi:
        return normalize_doi(ref.doi) == normalize_doi(paper.doi)
    if ref.title and norm_title(ref.title) == norm_title(paper.title):
        return not ref.year or ref.year == paper.year
    return False


def lookup_query(ref):
    if ref.doi:
        return f'DOI:"{normalize_doi(ref.doi)}"'
    return f'TITLE:"{ref.title.replace(chr(34), " ")}"'


def resolve_study(ref, pool, connector):
    """Return (paper, via, status, match_ids); status is resolved | not_found | ambiguous."""
    found, via = [p for p in pool if matches(ref, p)], "query"
    if not found:
        via = "lookup"
        found = [p for p in connector.search(lookup_query(ref), 5) if matches(ref, p)]
    unique = deduplicate(found)
    if not unique:
        return None, via, "not_found", []
    if len(unique) > 1:
        return None, via, "ambiguous", [p.id for p in unique]
    return unique[0], via, "resolved", []


def _candidate(paper, label, via):
    return GoldCandidate(
        id=paper.id,
        doi=paper.doi,
        title=paper.title,
        abstract=paper.abstract,
        year=paper.year,
        label=label,
        via=via,
        flags=[] if paper.abstract else ["no_abstract"],
    )


def build_gold(spec, connector, max_candidates=200, built_at=None):
    pool = deduplicate(connector.search(spec.query, max_candidates))
    positives, unresolved, ambiguous = {}, [], []
    for ref in spec.included:
        paper, via, status, ids = resolve_study(ref, pool, connector)
        if status == "resolved":
            positives.setdefault(paper.id, (paper, via))
        elif status == "ambiguous":
            ambiguous.append(UnmatchedStudy(reference=ref, matches=ids))
        else:
            unresolved.append(UnmatchedStudy(reference=ref))
    if not positives:
        raise GoldBuildError("no included study could be resolved; nothing to measure")
    candidates = {
        p.id: _candidate(p, "include" if p.id in positives else "not_included", "query") for p in pool
    }
    for paper_id, (paper, via) in positives.items():
        candidates[paper_id] = _candidate(paper, "include", via)
    return GoldSet(
        name=spec.name,
        citation=spec.citation,
        topic=spec.topic,
        query=spec.query,
        built_at=built_at or datetime.now(UTC).isoformat(),
        candidates=[candidates[i] for i in sorted(candidates)],
        unresolved=unresolved,
        ambiguous=ambiguous,
    )
