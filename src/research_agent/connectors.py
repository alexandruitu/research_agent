"""Network retrieval and identity resolution contain no LLM calls."""

import hashlib
import html
import json
import os
import re
import time
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import NamedTuple, Protocol

import httpx

from . import ratelimit
from .schemas import Paper, Source


def canonical_json(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def digest(value):
    return hashlib.sha256(canonical_json(value).encode()).hexdigest()


def plain(value):
    return html.unescape(re.sub(r"<[^>]+>", " ", value or "")).strip()


def normalize_doi(value):
    return re.sub(r"^(?:https?://(?:dx\.)?doi\.org/|doi:\s*)", "", value.strip(), flags=re.IGNORECASE).lower()


RETRYABLE = (429, 500, 502, 503, 504)
MAX_RETRY_AFTER = 60  # seconds; a source asking for a longer pause fails closed at once
VERSION = "0.1"


class SourceUnavailable(RuntimeError):
    """A source failed after retries or answered with something unreadable. Fail closed: the run stops
    (checkpoint kept). The message is only the source name, so it is safe to show and to log."""

    def __init__(self, source, message=None):
        super().__init__(message or source)
        self.source = source
        self.message = message or source


class SourceKeyMissing(SourceUnavailable):
    """A source that needs a key has none in the environment; raised before any request. The message names the
    variable (never a value)."""

    def __init__(self, source, env_var):
        super().__init__(source, f"{source}: set {env_var} in the worker environment")
        self.env_var = env_var


def env_key(name):
    """A credential from the environment (None when unset or blank). Never logged, cached or stored."""
    value = os.environ.get(name, "").strip()
    return value or None


def user_agent(contact=None):
    contact = contact or env_key("RESEARCH_AGENT_CONTACT")
    return f"research-agent/{VERSION} (+mailto:{contact})" if contact else f"research-agent/{VERSION}"


def retry_after(response):
    """Seconds asked by a Retry-After header (seconds or HTTP date), None when absent or unreadable."""
    value = (response.headers.get("Retry-After") or "").strip()
    if not value:
        return None
    if value.isdigit():
        return float(value)
    try:
        when = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=UTC)
    return max(0.0, (when - datetime.now(UTC)).total_seconds())


def fetch(client, url, params, source, decode, headers=None, secret=False, contact=None, keyed=False):
    """One GET: 3 attempts, 30 s timeout; transport errors and 429/5xx wait for Retry-After (at most 60 s) or
    1 s then 2 s. Every attempt first takes a token from the source's shared rate bucket. Any failure,
    including an undecodable body, raises SourceUnavailable; with `secret` (a key in the headers or params)
    the httpx error is not chained, so no URL or header with a key travels with the exception."""
    bucket = ratelimit.limiter(source, keyed)
    sent = {"User-Agent": user_agent(contact), **(headers or {})}

    def fail(exc):
        if secret:
            raise SourceUnavailable(source) from None
        raise SourceUnavailable(source) from exc

    def attempts(http):
        for attempt in range(3):
            if bucket is not None:
                bucket.acquire()
            try:
                response = http.get(url, params=params, headers=sent)
                response.raise_for_status()
                return decode(response)
            except (httpx.TransportError, httpx.HTTPStatusError) as exc:
                status = exc.response.status_code if isinstance(exc, httpx.HTTPStatusError) else None
                if (status is not None and status not in RETRYABLE) or attempt == 2:
                    fail(exc)
                wait = retry_after(exc.response) if status is not None else None
                if wait is not None and wait > MAX_RETRY_AFTER:
                    fail(exc)
                time.sleep(2**attempt if wait is None else wait)
            except ValueError as exc:
                fail(exc)

    if client is not None:
        return attempts(client)
    with httpx.Client(timeout=30, follow_redirects=True) as http:
        return attempts(http)


class SearchResult(NamedTuple):
    papers: list  # [Paper]
    total: int | None  # hits the source reports for the query (None: it did not say)
    query: str  # the query the source received (years included)
    note: str | None = None  # how to read `total` when it differs from what `papers` were drawn from


class Connector(Protocol):
    def search(self, query: str, limit: int) -> list[Paper]: ...


def _total(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


class EuropePMC:
    name = "europepmc"
    endpoint = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"

    def __init__(self, store, client=None, years=None):
        self.store = store
        self.client = client
        self.years = years

    def full_query(self, query):
        if self.years is None or (self.years.start is None and self.years.end is None):
            return query
        return f"({query}) AND (PUB_YEAR:[{self.years.start or 1900} TO {self.years.end or 9999}])"

    def search(self, query, limit, raw=False):
        return self.search_with_total(query, limit, raw).papers

    def search_with_total(self, query, limit, raw=False):
        """`raw` changes nothing here: a planned query and a built one are both Europe PMC syntax."""
        query = self.full_query(query)
        params = {"query": query, "format": "json", "resultType": "core", "pageSize": limit}
        # A single bounded page per query; raw payload retained before parsing.
        payload = fetch(self.client, self.endpoint, params, self.name, lambda response: response.json())
        raw_hash = self.store.raw(payload)
        retrieved = datetime.now(UTC).isoformat()
        try:
            papers = [self._paper(row, query, retrieved, raw_hash) for row in payload["resultList"]["result"]]
        except (KeyError, TypeError, ValueError) as exc:
            raise SourceUnavailable(self.name) from exc
        return SearchResult(papers, _total(payload.get("hitCount")), query)

    def _paper(self, row, query, retrieved, raw_hash):
        source, rid = row["source"], row["id"]
        return Paper(
            id=f"{source}:{rid}",
            title=plain(row.get("title")),
            abstract=plain(row.get("abstractText")),
            year=str(row.get("pubYear", "")),
            doi=normalize_doi(row.get("doi", "")),
            pmcid=row.get("pmcid") or (rid if source == "PMC" else ""),
            sources=[self.name],
            provenance=[
                Source(
                    connector="europe_pmc",
                    record_id=f"{source}:{rid}",
                    url=f"https://europepmc.org/article/{source}/{rid}",
                    query=query,
                    retrieved_at=retrieved,
                    raw_sha256=raw_hash,
                )
            ],
        )


def rebuild_abstract(index):
    """OpenAlex ships abstracts as {word: [positions]}; put every word back at its position."""
    if not index:
        return ""
    return " ".join(
        word for _position, word in sorted((p, w) for w, positions in index.items() for p in positions)
    )


class OpenAlex:
    name = "openalex"
    endpoint = "https://api.openalex.org/works"
    select = "id,doi,title,publication_year,abstract_inverted_index"

    def __init__(self, store, client=None, years=None, contact=None):
        self.store = store
        self.client = client
        self.years = years
        self.contact = contact  # polite pool; never recorded in provenance

    def search(self, query, limit, raw=False):
        return self.search_with_total(query, limit, raw).papers

    def search_with_total(self, query, limit, raw=False):
        """`raw`: a query built from keywords, searched in title and abstract (a filter, not `search`)."""
        params = {"per-page": min(limit, 200), "select": self.select}
        filters = []
        if raw:
            filters.append(f"title_and_abstract.search:{query}")
        else:
            params["search"] = query
        if self.years is not None and self.years.start is not None:
            filters.append(f"from_publication_date:{self.years.start}-01-01")
        if self.years is not None and self.years.end is not None:
            filters.append(f"to_publication_date:{self.years.end}-12-31")
        if filters:
            params["filter"] = ",".join(filters)
        if self.contact:
            params["mailto"] = self.contact
        key = env_key("OPENALEX_API_KEY")  # optional; never part of the recorded query
        sent_params = {**params, "api_key": key} if key else params
        payload = fetch(
            self.client,
            self.endpoint,
            sent_params,
            self.name,
            lambda response: response.json(),
            secret=key is not None,
            contact=self.contact,
            keyed=key is not None,
        )
        raw_hash = self.store.raw(payload)
        retrieved = datetime.now(UTC).isoformat()
        try:
            papers = [self._paper(row, query, retrieved, raw_hash) for row in payload["results"]]
        except (KeyError, TypeError, ValueError, AttributeError) as exc:
            raise SourceUnavailable(self.name) from exc
        sent = params.get("search") or params["filter"]
        return SearchResult(papers, _total((payload.get("meta") or {}).get("count")), sent)

    def _paper(self, row, query, retrieved, raw_hash):
        work = row["id"].rsplit("/", 1)[-1]
        return Paper(
            id=f"openalex:{work}",
            title=plain(row.get("title")),
            abstract=rebuild_abstract(row.get("abstract_inverted_index")),
            year=str(row.get("publication_year") or ""),
            doi=normalize_doi(row.get("doi") or ""),
            sources=[self.name],
            provenance=[
                Source(
                    connector="openalex",
                    record_id=f"openalex:{work}",
                    url=row["id"],
                    query=query,
                    retrieved_at=retrieved,
                    raw_sha256=raw_hash,
                )
            ],
        )


ARXIV_CATEGORIES = ("cs.CV", "eess.IV", "physics.med-ph")
ATOM = {
    "a": "http://www.w3.org/2005/Atom",
    "arxiv": "http://arxiv.org/schemas/atom",
    "opensearch": "http://a9.com/-/spec/opensearch/1.1/",
}
OPERATORS = {"AND", "OR", "NOT", "ANDNOT"}


class ArXiv:
    """arXiv Atom API. Python's expat refuses entity-expansion attacks; arXiv is the only producer here."""

    name = "arxiv"
    endpoint = "https://export.arxiv.org/api/query"

    def __init__(self, store, client=None, years=None, sleep=time.sleep):
        self.store = store
        self.client = client
        self.years = years
        self.sleep = sleep
        self.requested = False

    def search_query(self, query, raw=False):
        if raw:  # built from keywords: categories included; only the years are added
            parts = [query]
        else:
            words = [w for w in re.findall(r"\w[\w.\-]*", query) if w.upper() not in OPERATORS][:8]
            parts = [" AND ".join(f"all:{w}" for w in words)] if words else []
            parts.append("(" + " OR ".join(f"cat:{c}" for c in ARXIV_CATEGORIES) + ")")
        if self.years is not None and (self.years.start is not None or self.years.end is not None):
            parts.append(
                f"submittedDate:[{self.years.start or 1900}01010000 TO {self.years.end or 3000}12312359]"
            )
        return " AND ".join(parts)

    def search(self, query, limit, raw=False):
        return self.search_with_total(query, limit, raw).papers

    def search_with_total(self, query, limit, raw=False):
        if self.requested:
            self.sleep(3)  # arXiv API terms: no more than one request every three seconds
        self.requested = True
        search_query = self.search_query(query, raw)
        params = {"search_query": search_query, "start": 0, "max_results": min(limit, 200)}
        text = fetch(self.client, self.endpoint, params, self.name, lambda response: response.text)
        raw_hash = self.store.raw({"atom": text})
        retrieved = datetime.now(UTC).isoformat()
        try:
            root = ET.fromstring(text)
            entries = root.findall("a:entry", ATOM)
            papers = [self._paper(entry, search_query, retrieved, raw_hash) for entry in entries]
        except (ET.ParseError, AttributeError, ValueError) as exc:
            raise SourceUnavailable(self.name) from exc
        return SearchResult(
            papers, _total(root.findtext("opensearch:totalResults", namespaces=ATOM)), search_query
        )

    def _paper(self, entry, query, retrieved, raw_hash):
        link = entry.findtext("a:id", namespaces=ATOM).strip()
        if "/api/errors" in link:
            raise ValueError("arXiv returned an error entry")
        arxiv_id = re.sub(r"v\d+$", "", link.rsplit("/abs/", 1)[-1])
        return Paper(
            id=f"arxiv:{arxiv_id}",
            title=" ".join(entry.findtext("a:title", default="", namespaces=ATOM).split()),
            abstract=" ".join(entry.findtext("a:summary", default="", namespaces=ATOM).split()),
            year=entry.findtext("a:published", default="", namespaces=ATOM)[:4],
            doi=normalize_doi(entry.findtext("arxiv:doi", default="", namespaces=ATOM)),
            sources=[self.name],
            provenance=[
                Source(
                    connector="arxiv",
                    record_id=f"arxiv:{arxiv_id}",
                    url=f"https://arxiv.org/abs/{arxiv_id}",
                    query=query,
                    retrieved_at=retrieved,
                    raw_sha256=raw_hash,
                )
            ],
        )


class DemoConnector:
    """Synthetic fixtures, intentionally not real publications or scientific evidence."""

    def __init__(self, store, source="demo"):
        self.store = store
        self.source = source
        self.name = source

    def search(self, query, limit, raw=False):
        return self.search_with_total(query, limit, raw).papers

    def search_with_total(self, query, limit, raw=False):
        papers = []
        for i in range(1, min(limit, 12) + 1):
            row = {
                "title": f"SYNTHETIC DEMO {i}: retrieval augmented generation evaluation",
                "abstract": f"Synthetic study {i} evaluated retrieval augmented generation on a toy dataset. "
                "The reported accuracy increased in this simulated experiment. "
                "External validation was not performed.",
            }
            raw_hash = self.store.raw(row)
            papers.append(
                Paper(
                    id=f"demo:{i}",
                    **row,
                    year="2026",
                    sources=[self.source],
                    provenance=[
                        Source(
                            connector="synthetic_fixture",
                            record_id=f"demo:{i}",
                            url=f"urn:demo:{i}",
                            query=query,
                            retrieved_at="2026-09-12T00:00:00+00:00",
                            raw_sha256=raw_hash,
                        )
                    ],
                )
            )
        return SearchResult(papers, len(papers), query)


class MultiSource:
    """A field's sources: every planned query goes to every source, each with its own max_results.
    The graph's per-query `limit` bounds legacy single-source runs only and is ignored here."""

    def __init__(self, sources, raw=None):
        self.sources = list(sources)  # [(connector, max_results)]
        self.raw = dict(raw or {})  # {source name: query built from keywords}: searched once, never planned

    def search(self, query, limit):
        papers = []
        for connector, max_results in self.sources:
            if connector.name not in self.raw:
                papers.extend(connector.search(query, max_results))
        return papers

    def search_raw(self):
        papers = []
        for connector, max_results in self.sources:
            if connector.name in self.raw:
                papers.extend(connector.search(self.raw[connector.name], max_results, raw=True))
        return papers

    @property
    def planned(self):
        """True when some source still needs planned queries."""
        return any(connector.name not in self.raw for connector, _ in self.sources)


def domain_connector(domain, store, mode):
    from .sources import make_connector  # sources imports this module

    sources = [(make_connector(source, domain, store, mode), source.max_results) for source in domain.sources]
    return MultiSource(sources, domain.queries)


def deduplicate(papers):
    # Resolve known identifiers first; ambiguous title-only records stay separate.
    groups = []
    for paper in sorted(papers, key=lambda p: (not bool(p.doi), p.id)):
        paper = paper.model_copy(deep=True)
        paper.doi = normalize_doi(paper.doi)
        title = re.sub(r"\W+", " ", paper.title.casefold()).strip()
        matches = []
        for group in groups:
            if any(
                p.id == paper.id
                or (paper.doi and p.doi == paper.doi)
                or (
                    title
                    and title == re.sub(r"\W+", " ", p.title.casefold()).strip()
                    and p.year == paper.year
                    and not (p.doi and paper.doi and p.doi != paper.doi)
                )
                for p in group
            ):
                matches.append(group)
        known_dois = {p.doi for group in matches for p in group if p.doi}
        if len(known_dois) > 1:
            matches = [group for group in matches if any(p.id == paper.id for p in group)]
        merged = [paper]
        for group in matches:
            merged.extend(group)
            groups.remove(group)
        groups.append(merged)
    result = []
    for group in groups:
        primary = min(group, key=lambda p: (-len(p.abstract), p.id)).model_copy(deep=True)
        primary.doi = next((p.doi for p in group if p.doi), "")
        primary.pmcid = next((p.pmcid for p in group if p.pmcid), "")
        primary.sources = sorted({s for p in group for s in p.sources})
        sources = {canonical_json(s.model_dump()): s for p in group for s in p.provenance}
        primary.provenance = [sources[k] for k in sorted(sources)]
        result.append(primary)
    return sorted(result, key=lambda p: p.id)
