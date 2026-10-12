"""Researcher topics: per-source author queries, the sources that cannot search by author, the default
screening criterion, and "Matched by". Deterministic code, no model (spec: docs/superpowers/specs/
2026-10-12-authors-design.md, step 3).

A topic's `authors` = {people, group, coauthors, institutions, min_shared}. The searched set is the people,
plus the checked co-authors (group "coauthors") or the institutions (group "institution", much broader):

    OpenAlex          authorships.author.id:A1|A2  (institution: authorships.institutions.lineage:I1|I2),
                      plus ,title_and_abstract.search:<keywords> when the topic is restricted
    PubMed            (0000-...[auid] OR "Name"[au]) AND (<keywords>)    (institution: "Name"[ad])
    Europe PMC        (AUTHORID:"0000-..." OR AUTH:"Name") AND (<keywords>)   (institution: AFF:"Name")
    Semantic Scholar  author:<s2 id>,<s2 id>   (the connector lists each author's papers; keywords filter
                      locally). Skipped with a warning when no Semantic Scholar id is known.
    Other sources     skipped: they cannot search by author.

A skipped source gets a placeholder query `skipped: <reason>`; its connector raises SourceNotApplicable, so
the run reports it with the other partial-search warnings and goes on."""

from .connectors import normalize_name
from .querybuild import QueryError, build, clean_term, has_terms

AUTHOR_SOURCES = ("openalex", "semantic_scholar", "pubmed", "europepmc")
SKIPPED = "skipped: "
MAX_QUERY = 2000
# The screening of a researcher topic without a topic restriction: only "is this a research article".
DEFAULT_CRITERION = (
    "The record is a research article (an original study, a review or a similar scholarly paper), not an "
    "erratum, correction, editorial, retraction notice, comment or letter."
)
MATCH_KINDS = ("person", "coauthor", "institution", "name_match")
LABELS = {
    "europepmc": "Europe PMC",
    "openalex": "OpenAlex",
    "arxiv": "arXiv",
    "semantic_scholar": "Semantic Scholar",
    "crossref": "Crossref",
    "pubmed": "PubMed",
    "medrxiv": "medRxiv",
    "biorxiv": "bioRxiv",
    "core": "CORE",
    "ieee": "IEEE Xplore",
    "springer": "Springer",
    "scopus": "Scopus",
}


def as_dict(spec):
    if spec is None:
        return None
    return spec.model_dump() if hasattr(spec, "model_dump") else dict(spec)


def members(spec):
    """The people searched by identifier or name: the person(s), plus the co-authors of a co-author group."""
    spec = as_dict(spec)
    found = list(spec.get("people") or [])
    if spec.get("group", "coauthors") == "coauthors":
        found += list(spec.get("coauthors") or [])
    return found


def skip_reason(spec, source):
    """Why `source` cannot search this author topic (safe to show), or None when it can."""
    spec = as_dict(spec)
    label = LABELS.get(source, source)
    institution = spec.get("group") == "institution"
    if source not in AUTHOR_SOURCES:
        return f"{label} cannot search by author"
    if source == "semantic_scholar":
        if institution:
            return "Semantic Scholar cannot search by institution"
        if not any(m.get("s2_id") for m in members(spec)):
            return "no Semantic Scholar author id is known for these people (no ORCID mapping found)"
    if source == "openalex" and not institution and not any(m.get("openalex_id") for m in members(spec)):
        return "no OpenAlex author id is known for these people"
    return None


def name_match(spec, source):
    """True when the source is searched by name for at least one person (no ORCID): results are name matches."""
    spec = as_dict(spec)
    if source not in ("pubmed", "europepmc"):
        return False
    if spec.get("group") == "institution":
        return True
    return any(not m.get("orcid") for m in members(spec))


def _name(text):
    return clean_term(text) or "unknown"


def _people_terms(spec, orcid_form, name_form, inst_form):
    if spec.get("group") == "institution":
        terms = [inst_form.format(_name(i["name"])) for i in spec.get("institutions") or []]
    else:
        terms = [
            orcid_form.format(m["orcid"]) if m.get("orcid") else name_form.format(_name(m["name"]))
            for m in members(spec)
        ]
    terms = list(dict.fromkeys(terms))
    return terms[0] if len(terms) == 1 else "(" + " OR ".join(terms) + ")"


def build_author_query(source, spec, keywords=None):
    """The query `source` is sent for this author topic (see the module docstring), or `skipped: <reason>`."""
    spec = as_dict(spec)
    reason = skip_reason(spec, source)
    if reason:
        return SKIPPED + reason
    restricted = has_terms(keywords)
    if source == "openalex":
        if spec.get("group") == "institution":
            ids = [i["openalex_id"] for i in spec.get("institutions") or []]
            query = "authorships.institutions.lineage:" + "|".join(dict.fromkeys(ids))
        else:
            ids = [m["openalex_id"] for m in members(spec) if m.get("openalex_id")]
            query = "authorships.author.id:" + "|".join(dict.fromkeys(ids))
        if restricted:
            query += ",title_and_abstract.search:" + build("openalex", keywords)
    elif source == "semantic_scholar":
        ids = [m["s2_id"] for m in members(spec) if m.get("s2_id")]
        query = "author:" + ",".join(dict.fromkeys(ids))
    elif source == "pubmed":
        query = _people_terms(spec, "{}[auid]", '"{}"[au]', '"{}"[ad]')
        if restricted:
            query += f" AND ({build('pubmed', keywords)})"
    else:  # europepmc
        query = _people_terms(spec, 'AUTHORID:"{}"', 'AUTH:"{}"', 'AFF:"{}"')
        if restricted:
            query += f" AND ({build('europepmc', keywords)})"
    if len(query) > MAX_QUERY:
        raise QueryError(
            f"The {LABELS[source]} author query is too long (over {MAX_QUERY} characters); uncheck some co-authors"
        )
    return query


def build_author_queries(spec, sources, keywords=None):
    """{source: query} for every source of an author topic; skipped sources get `skipped: <reason>`."""
    return {source: build_author_query(source, spec, keywords) for source in sources}


def skipped(query):
    """The reason of a placeholder query, or None for a real one."""
    return query[len(SKIPPED) :] if query and query.startswith(SKIPPED) else None


# ---------- "Matched by" ----------


def _norm_orcid(value):
    return (value or "").strip().upper()


def _norm_oa(value):
    return (value or "").strip().upper()


def matched_by(authors, spec):
    """How a paper matches the topic's authors spec, by code from its stored authors
    ([{name, orcid?, openalex_id?, affiliations}]): [{kind, name}] best first, each (kind, name) once.
    person / coauthor: the same ORCID or OpenAlex id; institution: an affiliation naming one of the topic's
    institutions; name_match: only the normalized name agrees (it may be another person)."""
    spec = as_dict(spec)
    if not spec:
        return []
    people = spec.get("people") or []
    coauthors = (spec.get("coauthors") or []) if spec.get("group", "coauthors") == "coauthors" else []
    institutions = (spec.get("institutions") or []) if spec.get("group") == "institution" else []
    found = []

    def add(kind, name):
        entry = {"kind": kind, "name": name}
        if entry not in found:
            found.append(entry)

    def same(author, ref):
        return bool(
            (ref.get("orcid") and _norm_orcid(author.get("orcid")) == _norm_orcid(ref["orcid"]))
            or (
                ref.get("openalex_id") and _norm_oa(author.get("openalex_id")) == _norm_oa(ref["openalex_id"])
            )
        )

    names = []
    for kind, refs in (("person", people), ("coauthor", coauthors)):
        for ref in refs:
            if any(same(a, ref) for a in authors):
                add(kind, ref["name"])
            else:
                names.append(ref)
    for inst in institutions:
        wanted = normalize_name(inst["name"])
        if wanted and any(
            wanted in normalize_name(text) for a in authors for text in a.get("affiliations") or []
        ):
            add("institution", inst["name"])
    if spec.get("group") == "institution":
        names = [r for r in people if not any(same(a, r) for a in authors)]
    for ref in names:
        wanted = normalize_name(ref["name"])
        if wanted and any(normalize_name(a.get("name")) == wanted for a in authors):
            add("name_match", ref["name"])
    order = {k: n for n, k in enumerate(MATCH_KINDS)}
    return sorted(found, key=lambda e: order[e["kind"]])


__all__ = [
    "AUTHOR_SOURCES",
    "DEFAULT_CRITERION",
    "MATCH_KINDS",
    "QueryError",
    "build_author_queries",
    "matched_by",
    "skip_reason",
    "skipped",
]
