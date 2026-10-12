"""Authors in the web app: storing them (importer, backfill), showing them, filtering papers by them, and the
typeahead. Identity is by identifier only (ORCID, then OpenAlex author id); a name-only author is one row per
normalized name and is never merged into an identified author (spec: docs/superpowers/specs/
2026-10-12-authors-design.md)."""

import logging
from collections import defaultdict

from sqlalchemy import and_, delete, exists, func, or_, select
from sqlalchemy.exc import IntegrityError

from ..connectors import (
    SourceUnavailable,
    fetch,
    make_authors,
    normalize_doi,
    normalize_name,
)
from .db.models import Author, LibraryItem, Paper, PaperAuthor, Screening

log = logging.getLogger(__name__)

SHOWN = 3  # authors on a row before "et al."
OPENALEX_WORK = "https://api.openalex.org/works/https://doi.org/{doi}"
BACKFILL_SELECT = "id,doi,authorships"


def _like(word):
    return "%" + word.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


def _find(db, author):
    """The existing row for a pipeline author dict, by ORCID, then OpenAlex id, then (name-only authors only)
    by normalized name among rows without identifiers."""
    if author.get("orcid"):
        row = db.scalar(select(Author).where(Author.orcid == author["orcid"]))
        if row is not None:
            return row
    if author.get("openalex_id"):
        row = db.scalar(select(Author).where(Author.openalex_id == author["openalex_id"]))
        if row is not None:
            return row
    if author.get("orcid") or author.get("openalex_id"):
        return None  # an identified author is never matched to a name-only row
    return db.scalar(
        select(Author)
        .where(
            Author.normalized_name == normalize_name(author["name"]),
            Author.orcid.is_(None),
            Author.openalex_id.is_(None),
        )
        .order_by(Author.created_at, Author.id)
        .limit(1)
    )


def _complete(db, row, author):
    """Add an identifier the row lacks, unless another row already holds it (that would merge two people)."""
    for key in ("orcid", "openalex_id"):
        value = author.get(key)
        taken = value and db.scalar(select(Author.id).where(getattr(Author, key) == value)) is not None
        if value and not getattr(row, key) and not taken:
            setattr(row, key, value)


def resolve_author(db, author):
    """The `authors` row for a pipeline author dict ({name, orcid?, openalex_id?}), created when new."""
    row = _find(db, author)
    if row is None:
        try:
            with db.begin_nested():
                row = Author(
                    name=author["name"][:300],
                    normalized_name=normalize_name(author["name"])[:300],
                    orcid=author.get("orcid") or None,
                    openalex_id=author.get("openalex_id") or None,
                )
                db.add(row)
                db.flush()
        except IntegrityError:  # a concurrent import created it: use that row
            row = _find(db, author)
            if row is None:
                raise
    else:
        _complete(db, row, author)
    return row


def store_paper_authors(db, paper, authors):
    """Replace the paper's authors with `authors` (pipeline dicts, in order). An empty list changes nothing:
    an old run without authors must not erase authors stored since (by another run or the backfill)."""
    authors = [a for a in authors or [] if (a.get("name") or "").strip()]
    if not authors:
        return 0
    db.execute(delete(PaperAuthor).where(PaperAuthor.paper_id == paper.id))
    db.flush()
    for position, author in enumerate(authors, start=1):
        row = resolve_author(db, author)
        db.add(
            PaperAuthor(
                paper_id=paper.id,
                position=position,
                author_id=row.id,
                affiliations=list(author.get("affiliations") or []),
            )
        )
    db.flush()
    return len(authors)


def author_out(row, position=None, affiliations=None):
    return {
        "id": row.id,
        "name": row.name,
        "orcid": row.orcid,
        "openalex_id": row.openalex_id,
        "position": position,
        "affiliations": affiliations or [],
    }


def authors_of(db, paper_ids, limit=None):
    """{paper_id: {"authors": [AuthorOut], "count": n}} in author order; `limit` keeps the first n authors
    (rows show 3, then "et al.")."""
    out = defaultdict(lambda: {"authors": [], "count": 0})
    if not paper_ids:
        return out
    rows = db.execute(
        select(PaperAuthor, Author)
        .join(Author, Author.id == PaperAuthor.author_id)
        .where(PaperAuthor.paper_id.in_(list(paper_ids)))
        .order_by(PaperAuthor.paper_id, PaperAuthor.position)
    ).all()
    for link, author in rows:
        entry = out[link.paper_id]
        entry["count"] += 1
        if limit is None or len(entry["authors"]) < limit:
            entry["authors"].append(author_out(author, link.position, link.affiliations))
    return out


def author_condition(paper_id_column, author_id=None, author_name=None):
    """The condition "the paper has this author": by id (an identified person, or one name-only row), or by
    normalized name (every author with that name, identified or not: a name match)."""
    conditions = []
    if author_id is not None:
        conditions.append(
            exists().where(PaperAuthor.paper_id == paper_id_column, PaperAuthor.author_id == author_id)
        )
    if author_name:
        conditions.append(
            exists().where(
                PaperAuthor.paper_id == paper_id_column,
                PaperAuthor.author_id == Author.id,
                Author.normalized_name == normalize_name(author_name),
            )
        )
    return and_(*conditions) if conditions else None


def suggest(db, q, run_id=None, library=False, limit=10):
    """Typeahead: stored authors whose normalized name contains every typed word, with their paper count
    (within the run, or the library, when given). Identified authors first, then by paper count."""
    words = normalize_name(q).split()
    if not words:
        return []
    count = func.count(func.distinct(PaperAuthor.paper_id)).label("paper_count")
    stmt = select(Author, count).join(PaperAuthor, PaperAuthor.author_id == Author.id)
    for word in words:
        stmt = stmt.where(Author.normalized_name.like(_like(word), escape="\\"))
    if run_id is not None:
        stmt = stmt.where(
            exists().where(Screening.run_id == run_id, Screening.paper_id == PaperAuthor.paper_id)
        )
    if library:
        stmt = stmt.where(exists().where(LibraryItem.paper_id == PaperAuthor.paper_id))
    identified = or_(Author.orcid.is_not(None), Author.openalex_id.is_not(None))
    stmt = (
        stmt.group_by(Author.id)
        .order_by(identified.desc(), count.desc(), func.lower(Author.name), Author.id)
        .limit(limit)
    )
    return [author_out(author) | {"paper_count": n} for author, n in db.execute(stmt).all()]


def author_detail(db, author_id):
    row = db.get(Author, author_id)
    if row is None:
        return None
    papers = db.scalar(select(func.count()).where(PaperAuthor.author_id == row.id))
    return author_out(row) | {"paper_count": papers}


# ---------- backfill (worker job `authors_backfill`) ----------


def backfill_candidates(db):
    """Ids of papers that have a DOI and no stored authors, oldest first."""
    has = exists().where(PaperAuthor.paper_id == Paper.id)
    return list(
        db.scalars(select(Paper.id).where(Paper.doi != "", ~has).order_by(Paper.created_at, Paper.id))
    )


def openalex_authors_by_doi(doi, contact=None, client=None):
    """Pipeline author dicts for a DOI from OpenAlex ([] when OpenAlex has no authors for it), None when it
    does not know the DOI. Rate-limited by the shared OpenAlex bucket; the contact address joins the polite
    pool (never stored). Network failures raise SourceUnavailable."""
    from ..connectors import openalex_authors

    params = {"select": BACKFILL_SELECT}
    if contact:
        params["mailto"] = contact

    def decode(response):
        return response.json()

    try:
        work = fetch(
            client, OPENALEX_WORK.format(doi=normalize_doi(doi)), params, "openalex", decode, contact=contact
        )
    except SourceUnavailable as exc:
        if (exc.reason or "").endswith("(HTTP 404)"):
            return None
        raise
    return [a.model_dump() for a in openalex_authors(work if isinstance(work, dict) else {})]


def backfill(db, *, contact=None, client=None, progress=None, limit=None, lookup=None):
    """Look up the authors of papers with a DOI and none stored, in OpenAlex, one paper at a time. Returns
    the summary {total, done, updated, not_found, no_authors, failed}; `progress(summary)` after each paper.
    One paper's failure is counted and the job goes on; stored authors are committed per paper by the
    caller's session (flushed here)."""
    lookup = lookup or (lambda doi: openalex_authors_by_doi(doi, contact=contact, client=client))
    ids = backfill_candidates(db)
    if limit is not None:
        ids = ids[:limit]
    summary = {"total": len(ids), "done": 0, "updated": 0, "not_found": 0, "no_authors": 0, "failed": 0}
    for paper_id in ids:
        paper = db.get(Paper, paper_id)
        try:
            found = lookup(paper.doi)
        except SourceUnavailable as exc:
            log.info("authors backfill: %s failed (%s)", paper.doi, exc.reason)
            found = False
        if found is False:
            summary["failed"] += 1
        elif found is None:
            summary["not_found"] += 1
        elif not found:
            summary["no_authors"] += 1
        else:
            store_paper_authors(db, paper, [a.model_dump() for a in make_authors(found)])
            summary["updated"] += 1
        summary["done"] += 1
        if progress is not None:
            progress(dict(summary))
    return summary
