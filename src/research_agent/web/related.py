"""Reader step 3: find related and earlier work for a passage of a paper (worker job `reader_related`).

The query is built by code from the selection (key terms: stopwords out, multi-word technical phrases and
acronyms kept, at most MAX_TERMS), never by a model. It is sent to every enabled search source (at most
PER_SOURCE results each) with the field preview's partial-failure rule: a failing source becomes a visible
warning, and the job fails only when every source fails. The team library and the papers seen in runs are
searched too (title/abstract match). Results are deduplicated with the pipeline's own `deduplicate`, the paper
being read is left out, and each result carries "in library" / "seen in run" badges.

"Earlier work" is the same search sorted by year ascending with the paper's own year marked. It is a list of
papers, never a novelty verdict."""

import re
import unicodedata

from sqlalchemy import exists, or_, select

from ..connectors import SourceUnavailable, deduplicate, normalize_doi, search_warning
from ..querybuild import SOURCES, QueryError, build_queries
from ..schemas import Paper as SearchPaper
from ..schemas import Source, Years
from .db.models import LibraryItem, Paper, Run, Screening
from .runner import sanitize_error

MAX_TERMS = 5
MAX_PHRASE = 3  # words in one phrase
PER_SOURCE = 10
LOCAL_LIMIT = 10  # library / seen-in-run matches added to the results
MAX_RESULTS = 50
MAX_INPUT = 4000
TEAM = "team_library"  # pseudo-source of the local matches; shown as badges, not as a source
MODES = ("related", "earlier")

_STOP_TEXT = """a about above after again against all also although am among an and any are as at be because been
    before being below between both but by can could did do does doing done down during each either et etc
    few for from further had has have having he her here hers him his how however i if in into is it its
    itself just la less many may me might more most much must my no nor not now of off on once one only or
    other our ours out over own per same she should since so some such than that the their theirs them then
    there these they this those though through thus to too two under until up upon us very via was we were
    what when where whether which while who whom whose why will with within without would yet you your
    al approach approaches based compared conclusion conclusions data different et findings first further
    furthermore given good high however including introduce introduced large low method methods new novel
    obtained overall paper performed present presented propose proposed provide provides recent report
    reported respectively result results several show showed shown significant significantly similar study
    studies use used uses using various well work achieve achieved achieves allow allowed applied apply assess
    assessed demonstrate demonstrated describe described develop developed evaluate evaluated evaluates
    examine examined found improve improved improves increase increased investigate investigated obtain
    perform performs reached reduce reduced suggest suggests train trained"""
STOPWORDS = frozenset(_STOP_TEXT.split())
TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9\-]*")
BREAK = re.compile(r"[.,;:!?()\[\]{}\"'“”‘’/|]+")


class RelatedFailed(ValueError):
    """Shown to the user as the job's error: clear, no internals."""


def _acronym(word):
    letters = [c for c in word if c.isalpha()]
    upper = sum(c.isupper() for c in letters)
    return 2 <= len(word) <= 12 and upper >= 2 and upper >= len(letters) - 2 and not word.isdigit()


def _keep_word(word):
    lower = word.casefold()
    if lower in STOPWORDS or word.replace("-", "").isdigit():
        return False
    return _acronym(word) or len(word) >= 3


def key_terms(text, max_terms=MAX_TERMS):
    """Ordered key terms of a passage: multi-word phrases first (runs of 2-3 content words), then acronyms,
    then single words by frequency. Deterministic; case-insensitive duplicates and words already inside a
    chosen phrase are dropped."""
    text = unicodedata.normalize("NFKC", str(text or ""))[:MAX_INPUT]
    phrases, acronyms, words, order = [], [], {}, {}
    for segment in BREAK.split(text):
        run = []
        for token in [*TOKEN.findall(segment), None]:
            if token is not None and _keep_word(token.strip("-")):
                if not run or run[-1].casefold() != token.strip("-").casefold():  # "x x y" → "x y"
                    run.append(token.strip("-"))
                continue
            for i in range(0, len(run), MAX_PHRASE):
                chunk = run[i : i + MAX_PHRASE]
                if len(chunk) >= 2:
                    phrases.append(" ".join(chunk))
            for word in run:
                if _acronym(word):
                    acronyms.append(word)
                elif len(word) >= 4:
                    key = word.casefold()
                    words[key] = words.get(key, 0) + 1
                    order.setdefault(key, (len(order), word))
            run = []
    singles = [order[k][1] for k in sorted(words, key=lambda k: (-words[k], order[k][0]))]
    out, seen = [], set()
    for term in [*phrases, *acronyms, *singles]:
        key = term.casefold()
        if key in seen or any(re.search(rf"(?<!\w){re.escape(key)}(?!\w)", s) for s in seen if " " in s):
            continue
        seen.add(key)
        out.append(term)
        if len(out) >= max_terms:
            break
    return out


def keywords_for(terms):
    """The field-style keywords of the search: the first (most specific) term must appear, plus any other."""
    if not terms:
        return None
    return {"all": terms[:1], "any": terms[1:], "none": []}


def _norm_title(title):
    return re.sub(r"\W+", " ", (title or "").casefold()).strip()


def _link(paper):
    if paper.doi:
        return f"https://doi.org/{paper.doi}"
    for source in paper.provenance:
        if source.url.startswith(("https://", "http://")):
            return source.url
    return None


def _local_paper(row, query):
    return SearchPaper(
        id=row.source_id,
        title=row.title,
        abstract=row.abstract or "",
        year=str(row.year or ""),
        doi=row.doi or "",
        sources=[TEAM],
        provenance=[
            Source(
                connector=TEAM, record_id=row.source_id, url="", query=query, retrieved_at="", raw_sha256=""
            )
        ],
    )


def _score(paper, terms):
    text = f"{paper.title} {paper.abstract}".casefold()
    return sum(1 for t in terms if t.casefold() in text)


def search_local(db, terms, exclude_id, limit=LOCAL_LIMIT):
    """Papers of the team library or seen in a run whose title or abstract contains the terms (at least two,
    or the only one)."""
    if not terms:
        return []
    known = or_(
        exists().where(Screening.paper_id == Paper.id), exists().where(LibraryItem.paper_id == Paper.id)
    )
    match = or_(*[c.ilike(f"%{t}%") for t in terms for c in (Paper.title, Paper.abstract)])
    rows = db.scalars(select(Paper).where(known, match, Paper.id != exclude_id).limit(500)).all()
    need = min(2, len(terms))
    hits = [(r, s) for r in rows if (s := _score(r, terms)) >= need]
    hits.sort(key=lambda h: (-h[1], -(h[0].year or 0), h[0].title, h[0].source_id))
    return [r for r, _ in hits[:limit]]


def search_sources(names, keywords, make, *, per_source=PER_SOURCE):
    """{queries, papers, warnings, answered}: each enabled source searched once (field preview semantics)."""
    queries = build_queries(keywords, list(names))
    papers, warnings, answered = [], [], []
    for name in names:
        query = queries.get(name)
        if not query:
            continue
        try:
            found = make(name).search(query, per_source)
        except SourceUnavailable as exc:
            warnings.append(search_warning(exc))
            continue
        except Exception as exc:  # noqa: BLE001 -- one source must not sink the search; reported, sanitized
            warnings.append(
                {
                    "source": name,
                    "error_type": type(exc).__name__,
                    "reason": sanitize_error(exc),
                    "detail": "The source did not answer; check Settings → Sources and retry later.",
                }
            )
            continue
        answered.append(name)
        papers.extend(found[:per_source])
    return {"queries": queries, "papers": papers, "warnings": warnings, "answered": answered}


def _run_label(run):
    contract = (run.manifest or {}).get("contract") or {}
    return run.name or contract.get("topic") or f"run {str(run.id)[:8]}"


def _known(db, papers):
    """DB papers matching the results by source id, DOI or normalized title: {key: Paper row}."""
    ids = {p.id for p in papers}
    dois = {p.doi for p in papers if p.doi}
    rows = db.scalars(
        select(Paper).where(or_(Paper.source_id.in_(ids or {""}), Paper.doi.in_(dois or {""})))
    ).all()
    return rows


def _badges(db, rows):
    """{paper uuid: {library_item_id, runs: [{id, name}]}} for the matched DB papers."""
    if not rows:
        return {}
    ids = [r.id for r in rows]
    out = {r.id: {"library_item_id": None, "runs": []} for r in rows}
    for item in db.scalars(select(LibraryItem).where(LibraryItem.paper_id.in_(ids))):
        out[item.paper_id]["library_item_id"] = str(item.id)
    pairs = db.execute(
        select(Screening.paper_id, Run)
        .join(Run, Run.id == Screening.run_id)
        .where(Screening.paper_id.in_(ids))
        .order_by(Run.created_at.desc(), Run.id)
    ).all()
    for paper_id, run in pairs:
        out[paper_id]["runs"].append({"id": str(run.id), "name": _run_label(run)})
    return out


def _is_self(paper, me):
    if paper.id == me.source_id:
        return True
    doi = normalize_doi(me.doi or "")
    if doi and paper.doi == doi:
        return True
    title = _norm_title(me.title)
    return bool(title) and _norm_title(paper.title) == title


def year_of(paper):
    match = re.match(r"\d{4}", paper.get("year") or "")
    return int(match.group()) if match else None


def search_keywords(selection, me):
    """The keywords searched for: from the selection, else from the paper's title."""
    return keywords_for(key_terms(selection if (selection or "").strip() else me.title))


def find_related(db, me, selection, mode, *, names, make, search_mode="live"):
    """The job result. `me` is the paper being read (a DB row); `names` the enabled search sources; `make(name)`
    their connector. Raises RelatedFailed when there is nothing to search or every source failed."""
    if mode not in MODES:
        raise RelatedFailed("Unknown search")
    basis = "selection" if (selection or "").strip() else "title"
    terms = key_terms(selection if basis == "selection" else me.title)
    keywords = keywords_for(terms)
    if not keywords:
        raise RelatedFailed("The selection has no key terms to search for; select a longer passage")
    names = [n for n in SOURCES if n in set(names)] + sorted(set(names) - set(SOURCES))
    try:
        found = search_sources(names, keywords, make)
    except QueryError as exc:
        raise RelatedFailed(str(exc)) from None
    if names and not found["answered"]:
        listed = "; ".join(f"{w['source']}: {w['reason']}" for w in found["warnings"])
        raise RelatedFailed(f"No search source answered ({listed}). Nothing was searched; retry later.")
    query_text = " ".join(terms)
    local = [_local_paper(r, query_text) for r in search_local(db, terms, me.id)]
    merged = [p for p in deduplicate(found["papers"] + local) if not _is_self(p, me)]
    rows = _known(db, merged)
    by_source = {r.source_id: r for r in rows}
    by_doi = {normalize_doi(r.doi): r for r in rows if r.doi}
    badges = _badges(db, rows)
    results = []
    for paper in merged:
        row = by_source.get(paper.id) or (by_doi.get(paper.doi) if paper.doi else None)
        if row is not None and row.id == me.id:
            continue
        badge = badges.get(row.id) if row is not None else None
        results.append(
            {
                "title": paper.title,
                "year": paper.year or None,
                "sources": [s for s in paper.sources if s != TEAM],
                "doi": paper.doi or None,
                "url": _link(paper),
                "paper_id": str(row.id) if row is not None else None,
                "in_library": bool(badge and badge["library_item_id"]),
                "library_item_id": badge["library_item_id"] if badge else None,
                "seen_in_runs": badge["runs"] if badge else [],
                "matched_terms": _score(paper, terms),
            }
        )
    if mode == "earlier":
        results.sort(key=lambda r: (year_of(r) is None, year_of(r) or 0, r["title"].casefold()))
    else:
        results.sort(key=lambda r: (-r["matched_terms"], -(year_of(r) or 0), r["title"].casefold()))
    results = results[:MAX_RESULTS]
    return {
        "mode": mode,
        "search_mode": search_mode,
        "basis": basis,
        "selection": (selection or "")[:MAX_INPUT],
        "terms": terms,
        "keywords": keywords,
        "queries": found["queries"],
        "sources": names,
        "answered": found["answered"],
        "warnings": found["warnings"],
        "paper_year": me.year,
        "results": results,
    }


def default_years():
    return Years.model_validate({})
