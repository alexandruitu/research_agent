"""Match SR-included studies to Europe PMC records and build a frozen gold set."""

import re
import unicodedata
from datetime import UTC, datetime

from ..connectors import deduplicate, normalize_doi
from .gold import GoldCandidate, GoldSet, UnmatchedStudy


class GoldBuildError(RuntimeError):
    """Nothing measurable: no included study could be resolved."""


def norm_title(title):
    return re.sub(r"\W+", " ", unicodedata.normalize("NFKC", title).casefold()).strip()


def matches(ref, paper):
    """DOI equality when both sides have a DOI (conflicting DOIs never match); else title (+ year)."""
    if ref.doi and paper.doi:
        return normalize_doi(ref.doi) == normalize_doi(paper.doi)
    title = norm_title(ref.title)
    if title and title == norm_title(paper.title):
        return not ref.year or ref.year == paper.year
    return False


def lookup_query(ref):
    if ref.doi:
        return f'DOI:"{normalize_doi(ref.doi)}"'
    title = re.sub(r'["\\]', " ", ref.title)
    return f'TITLE:"{title}"'


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


def _record_ids(paper):
    return {paper.id, *(source.record_id for source in paper.provenance)}


def build_gold(spec, connector, max_candidates=200, built_at=None):
    pool = deduplicate(connector.search(spec.query, max_candidates))
    pool_records = set().union(*(_record_ids(p) for p in pool)) if pool else set()
    resolved, lookups, unresolved, ambiguous = [], [], [], []
    for ref in spec.included:
        paper, via, status, ids = resolve_study(ref, pool, connector)
        if status == "resolved":
            resolved.append(paper)
            if via == "lookup":
                lookups.append(paper)
        elif status == "ambiguous":
            ambiguous.append(UnmatchedStudy(reference=ref, matches=ids))
        else:
            unresolved.append(UnmatchedStudy(reference=ref))
    if not resolved:
        raise GoldBuildError("no included study could be resolved; nothing to measure")
    # A lookup hit can be the same paper as a pool record (or as another lookup hit): merge them all.
    merged = deduplicate(pool + lookups)
    merged_id = {record: m.id for m in merged for record in _record_ids(m)}
    positives = {merged_id[p.id] for p in resolved}
    candidates = [
        _candidate(
            m,
            "include" if m.id in positives else "not_included",
            "query" if _record_ids(m) & pool_records else "lookup",
        )
        for m in merged
    ]
    return GoldSet(
        name=spec.name,
        citation=spec.citation,
        topic=spec.topic,
        query=spec.query,
        built_at=built_at or datetime.now(UTC).isoformat(),
        candidates=candidates,
        unresolved=unresolved,
        ambiguous=ambiguous,
    )
