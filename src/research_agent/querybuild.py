"""Per-source search queries from a field's keywords. Deterministic code, no model involved.

Keywords come in three groups: every `all` term must appear, at least one `any` term must appear, no `none`
term may appear. Each source gets the same boolean in its own syntax, restricted to title and abstract:

    Europe PMC  TITLE_ABS:t1 AND (TITLE_ABS:a1 OR TITLE_ABS:a2) NOT TITLE_ABS:n1
    OpenAlex    t1 AND (a1 OR a2) NOT n1          (sent as filter=title_and_abstract.search:<query>)
    arXiv       abs:t1 AND (abs:a1 OR abs:a2) AND (cat:...) ANDNOT abs:n1
    medRxiv     as Europe PMC (the connector appends the preprint-server filter); bioRxiv the same
    PubMed      t1[tiab] AND (a1[tiab] OR a2[tiab]) NOT n1[tiab]
    CORE        t1 AND (a1 OR a2) AND NOT n1       (all fields: CORE also matches full text)
    IEEE        t1 AND (a1 OR a2) NOT n1           (querytext: metadata incl. abstract and index terms)
    Springer    t1 AND (a1 OR a2) NOT n1
    Scopus      TITLE-ABS-KEY(t1) AND (TITLE-ABS-KEY(a1) OR TITLE-ABS-KEY(a2)) AND NOT TITLE-ABS-KEY(n1)
    Semantic Scholar, Crossref: no boolean search. The query is the plain `all` and `any` terms; the connector
                keeps only results that `matches()` the keywords, and reports the API's total with a note.

Years are not part of the query: the connectors add them. An override replaces the built query of one source.
"""

import re
import unicodedata

SOURCES = (
    "europepmc",
    "openalex",
    "arxiv",
    "semantic_scholar",
    "crossref",
    "pubmed",
    "medrxiv",
    "biorxiv",
    "core",
    "ieee",
    "springer",
    "scopus",
)
GROUPS = ("all", "any", "none")
ARXIV_CATEGORIES = ("cs.CV", "eess.IV", "physics.med-ph")
MAX_QUERY = 2000
SYNTAX = re.compile(r'["()\[\]{}:\\^~,;<>|&!?=+/]')
BARE = re.compile(r"^\w+\*?$")
OPERATORS = {"AND", "OR", "NOT", "ANDNOT", "TO"}
WILDCARDS = {"europepmc", "medrxiv", "biorxiv", "pubmed", "scopus"}  # a trailing * on a single word
TERM = {  # how one (cleaned, quoted when needed) term is written
    "europepmc": "TITLE_ABS:{}",
    "medrxiv": "TITLE_ABS:{}",
    "biorxiv": "TITLE_ABS:{}",
    "openalex": "{}",
    "arxiv": "abs:{}",
    "pubmed": "{}[tiab]",
    "core": "{}",
    "ieee": "{}",
    "springer": "{}",
    "scopus": "TITLE-ABS-KEY({})",
}
NOT = {"arxiv": " ANDNOT ", "core": " AND NOT ", "scopus": " AND NOT "}  # default " NOT "
PLAIN = {"semantic_scholar", "crossref"}  # no boolean search: plain terms, filtered locally with matches()
CONTROL = re.compile(r"[\x00-\x1f\x7f]")


class QueryError(ValueError):
    """The keywords (or an override) cannot make a query; the message is safe to show."""


def clean_term(term, wildcard=False):
    """Search syntax characters become spaces; whitespace collapses; `*` survives only at the end of a single
    word when the source supports wildcards."""
    text = SYNTAX.sub(" ", unicodedata.normalize("NFKC", str(term)))
    star = text.rstrip().endswith("*")
    text = " ".join(text.replace("*", " ").split())
    if text and wildcard and star and " " not in text:
        text += "*"
    return text


def _unique(terms, wildcard):
    seen, out = set(), []
    for term in terms or []:
        cleaned = clean_term(term, wildcard)
        if cleaned and cleaned.casefold() not in seen:
            seen.add(cleaned.casefold())
            out.append(cleaned)
    return out


def normalize_keywords(keywords):
    """Stored form: every group present, terms trimmed (syntax kept for the builder), case-insensitive
    duplicates dropped; None when there is no term at all."""
    if not keywords:
        return None
    out = {}
    for group in GROUPS:
        seen, terms = set(), []
        for term in keywords.get(group) or []:
            text = " ".join(unicodedata.normalize("NFKC", str(term)).split())
            if text and text.casefold() not in seen:
                seen.add(text.casefold())
                terms.append(text)
        out[group] = terms
    return out if any(out.values()) else None


def has_terms(keywords):
    """True when the keywords can make a query (at least one `all` or `any` term)."""
    return bool(keywords) and any(_unique(keywords.get(g), False) for g in ("all", "any"))


def _phrase(term):
    return term if BARE.match(term) and term.rstrip("*").upper() not in OPERATORS else f'"{term}"'


def _group(terms, form):
    parts = [form.format(_phrase(t)) for t in terms]
    return parts[0] if len(parts) == 1 else "(" + " OR ".join(parts) + ")"


def build(source, keywords):
    if source not in SOURCES:
        raise ValueError(f"unknown source {source!r}")
    keywords = keywords or {}
    wildcard = source in WILDCARDS
    groups = {g: _unique(keywords.get(g), wildcard) for g in GROUPS}
    if not (groups["all"] or groups["any"]):
        raise QueryError("Add at least one keyword to 'All of' or 'Any of'")
    if source in PLAIN:
        query = " ".join(groups["all"] + groups["any"])
    else:
        form = TERM[source]
        parts = [form.format(_phrase(t)) for t in groups["all"]]
        if groups["any"]:
            parts.append(_group(groups["any"], form))
        if source == "arxiv":
            parts.append("(" + " OR ".join(f"cat:{c}" for c in ARXIV_CATEGORIES) + ")")
        query = " AND ".join(parts)
        if groups["none"]:
            query += NOT.get(source, " NOT ") + _group(groups["none"], form)
    if len(query) > MAX_QUERY:
        raise QueryError(f"The {source} query is too long (over {MAX_QUERY} characters); use fewer keywords")
    return query


def check_override(source, text):
    """An override used verbatim: plain text, at most 2000 characters; no comma for OpenAlex (its filter
    separator). Returns the stripped text."""
    text = (text or "").strip()
    if CONTROL.search(text):
        raise QueryError(f"The {source} query must be a single line")
    if len(text) > MAX_QUERY:
        raise QueryError(f"The {source} query is too long (over {MAX_QUERY} characters)")
    if source == "openalex" and "," in text:
        raise QueryError("The OpenAlex query cannot contain a comma")
    return text


def build_queries(keywords, sources, overrides=None):
    """{source: query}. With keywords every source gets one (its override, else the built query); without,
    only overridden sources get one (the others are planned as before)."""
    overrides = overrides or {}
    usable = has_terms(keywords)
    queries = {}
    for source in sources:
        override = check_override(source, overrides.get(source))
        if override:
            queries[source] = override
        elif usable:
            queries[source] = build(source, keywords)
    return queries


def _pattern(term):
    """Words of the term in order, any non-word characters between them (U-Net matches "U Net" and "U-Net")."""
    words = re.findall(r"\w+\*?", unicodedata.normalize("NFKC", str(term)))
    if not words:
        return None
    parts = [re.escape(w[:-1]) + r"\w*" if w.endswith("*") else re.escape(w) for w in words]
    return re.compile(r"(?<!\w)" + r"[\W_]+".join(parts) + r"(?!\w)", re.IGNORECASE)


def matches(keywords, text):
    """True when `text` (title + abstract) has every `all` term, at least one `any` term (when there are any)
    and no `none` term: whole words, case-insensitive, a trailing * is a prefix. For sources without boolean
    search (PLAIN)."""
    keywords = keywords or {}

    def found(term):
        pattern = _pattern(term)
        return pattern is not None and bool(pattern.search(text or ""))

    anys = [t for t in keywords.get("any") or [] if _pattern(t)]
    return (
        all(found(t) for t in keywords.get("all") or [] if _pattern(t))
        and (not anys or any(found(t) for t in anys))
        and not any(found(t) for t in keywords.get("none") or [])
    )
