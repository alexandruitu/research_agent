"""Per-source search queries from a field's keywords. Deterministic code, no model involved.

Keywords come in three groups: every `all` term must appear, at least one `any` term must appear, no `none`
term may appear. Each source gets the same boolean in its own syntax, restricted to title and abstract:

    Europe PMC  TITLE_ABS:t1 AND (TITLE_ABS:a1 OR TITLE_ABS:a2) NOT TITLE_ABS:n1
    OpenAlex    t1 AND (a1 OR a2) NOT n1          (sent as filter=title_and_abstract.search:<query>)
    arXiv       abs:t1 AND (abs:a1 OR abs:a2) AND (cat:...) ANDNOT abs:n1

Years are not part of the query: the connectors add them. An override replaces the built query of one source.
"""

import re
import unicodedata

SOURCES = ("europepmc", "openalex", "arxiv")
GROUPS = ("all", "any", "none")
ARXIV_CATEGORIES = ("cs.CV", "eess.IV", "physics.med-ph")
MAX_QUERY = 2000
SYNTAX = re.compile(r'["()\[\]{}:\\^~,;<>|&!?=+/]')
BARE = re.compile(r"^\w+\*?$")
OPERATORS = {"AND", "OR", "NOT", "ANDNOT", "TO"}
WILDCARDS = {"europepmc"}  # the only source that supports a trailing * on a word
PREFIX = {"europepmc": "TITLE_ABS:", "openalex": "", "arxiv": "abs:"}
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


def _group(terms, prefix):
    parts = [f"{prefix}{_phrase(t)}" for t in terms]
    return parts[0] if len(parts) == 1 else "(" + " OR ".join(parts) + ")"


def build(source, keywords):
    if source not in SOURCES:
        raise ValueError(f"unknown source {source!r}")
    keywords = keywords or {}
    wildcard, prefix = source in WILDCARDS, PREFIX[source]
    groups = {g: _unique(keywords.get(g), wildcard) for g in GROUPS}
    if not (groups["all"] or groups["any"]):
        raise QueryError("Add at least one keyword to 'All of' or 'Any of'")
    parts = [f"{prefix}{_phrase(t)}" for t in groups["all"]]
    if groups["any"]:
        parts.append(_group(groups["any"], prefix))
    if source == "arxiv":
        parts.append("(" + " OR ".join(f"cat:{c}" for c in ARXIV_CATEGORIES) + ")")
    query = " AND ".join(parts)
    if groups["none"]:
        query += (" ANDNOT " if source == "arxiv" else " NOT ") + _group(groups["none"], prefix)
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
