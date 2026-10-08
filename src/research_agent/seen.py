"""Skip seen: the deterministic step of an alert run that drops papers the field has already seen.

The web app writes seen.json ({schema, max_new, papers: [{doi, source_id, title, year}]}) into the run folder;
after Deduplicate the pipeline drops every paper that matches a seen one, keeps at most `max_new` of the rest
(newest by year, then source order) and records {found, already_seen, new, over_cap}. No model is called.

A paper matches a seen one by normalised DOI, else by source id (its own id or any record id that found it),
else by normalised title + year when their DOIs do not conflict (the same rules as dedup)."""

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from .connectors import normalize_doi

SEEN_FILE = "seen.json"
SEEN_SCHEMA = 1


def title_key(title, year):
    """Normalised title + year, as dedup compares them (connectors._title); None without a title."""
    title = re.sub(r"\W+", " ", (title or "").casefold()).strip()
    return (title, str(year or "").strip()) if title else None


@dataclass
class SeenSet:
    dois: set = field(default_factory=set)
    ids: set = field(default_factory=set)
    titles: dict = field(default_factory=dict)  # (title, year) -> {doi or ""}

    @classmethod
    def from_records(cls, records):
        seen = cls()
        for record in records:
            doi = normalize_doi(record.get("doi") or "")
            if doi:
                seen.dois.add(doi)
            if record.get("source_id"):
                seen.ids.add(str(record["source_id"]).strip().casefold())
            if key := title_key(record.get("title"), record.get("year")):
                seen.titles.setdefault(key, set()).add(doi)
        return seen

    def __len__(self):
        return len(self.ids | self.dois)

    def contains(self, paper):
        """`paper`: a research_agent.schemas.Paper (or anything with id, doi, title, year, provenance)."""
        doi = normalize_doi(getattr(paper, "doi", "") or "")
        if doi and doi in self.dois:
            return True
        ids = {paper.id} | {source.record_id for source in getattr(paper, "provenance", []) or []}
        if {i.strip().casefold() for i in ids if i} & self.ids:
            return True
        key = title_key(paper.title, paper.year)
        if key is None or key not in self.titles:
            return False
        known = self.titles[key]
        return not doi or "" in known or doi in known  # a different DOI is a different work


def _year(paper):
    try:
        return int(str(paper.year).strip()[:4])
    except ValueError:
        return -1


def skip_seen(papers, seen, max_new):
    """papers in source order -> (the new papers to review, newest first, at most max_new; counts)."""
    new = [p for p in papers if not seen.contains(p)]
    order = {id(p): i for i, p in enumerate(new)}
    kept = sorted(new, key=lambda p: (-_year(p), order[id(p)]))[: max(0, max_new)]
    counts = {
        "found": len(papers),
        "already_seen": len(papers) - len(new),
        "new": len(new),
        "over_cap": len(new) - len(kept),
    }
    return kept, counts


def write_seen(path, records, max_new):
    path = Path(path)
    path.write_text(
        json.dumps(
            {"schema": SEEN_SCHEMA, "max_new": int(max_new), "papers": list(records)}, ensure_ascii=False
        )
    )
    return path


def read_seen(path):
    """(SeenSet, max_new). Fails closed: an unreadable or malformed file raises ValueError."""
    try:
        data = json.loads(Path(path).read_text())
    except (OSError, ValueError) as exc:
        raise ValueError(f"cannot read the seen set: {type(exc).__name__}") from None
    if (
        not isinstance(data, dict)
        or data.get("schema") != SEEN_SCHEMA
        or not isinstance(data.get("papers"), list)
    ):
        raise ValueError("the seen set is not a schema 1 seen.json")
    max_new = data.get("max_new")
    if not isinstance(max_new, int) or max_new < 1:
        raise ValueError("the seen set needs max_new >= 1")
    return SeenSet.from_records(data["papers"]), max_new
