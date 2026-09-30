"""Search sources beyond Europe PMC, OpenAlex and arXiv, all through official APIs, plus the source registry.

Every connector: `search(query, limit, raw=False)` and `search_with_total(...) -> SearchResult`, papers in the
`Paper` shape with `sources=[name]` and every identifier the API gives (doi, pmid, pmcid, arxiv, s2). Requests go
through `connectors.fetch` (shared rate buckets, Retry-After, User-Agent). Keys come from the environment at
request time; a required key that is missing raises SourceKeyMissing before any request. Payloads are scrubbed
of the key value before they reach the Raw Layer, and provenance URLs are record pages, never request URLs.
No LLM calls here."""

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import UTC, datetime

from . import ratelimit
from .connectors import (
    ArXiv,
    DemoConnector,
    EuropePMC,
    OpenAlex,
    SearchResult,
    SourceKeyMissing,
    SourceUnavailable,
    _total,
    env_key,
    fetch,
    normalize_doi,
    plain,
    scrub,
)
from .querybuild import PLAIN, matches
from .schemas import Paper, Source


@dataclass(frozen=True)
class SourceInfo:
    name: str
    label: str
    group: str  # biomedical | preprints | multidisciplinary | publishers | identity
    covers: str
    auth: str  # none | optional | required
    env: tuple = ()  # key variables: the required one first when auth == "required"
    capabilities: tuple = ("search",)  # search and/or fulltext
    resolvers: tuple = ()  # full-text resolver names this source provides
    max_results: int = 100
    rps: float = field(default=0)
    rps_keyed: float = field(default=0)


def _info(name, label, group, covers, auth, env=(), capabilities=("search",), resolvers=()):
    bucket = ratelimit.bucket_name(name)
    rps, rps_keyed = ratelimit.RATES.get(bucket, (0, 0))
    return SourceInfo(
        name, label, group, covers, auth, tuple(env), capabilities, resolvers, 100, rps, rps_keyed
    )


REGISTRY = {
    info.name: info
    for info in (
        _info(
            "europepmc",
            "Europe PMC",
            "biomedical",
            "Life-science literature incl. PubMed and PMC",
            "none",
            capabilities=("search", "fulltext"),
            resolvers=("pmc_oa", "europepmc"),
        ),
        _info(
            "pubmed",
            "PubMed",
            "biomedical",
            "MEDLINE citations with MeSH (NCBI E-utilities)",
            "optional",
            env=("NCBI_API_KEY",),
        ),
        _info("arxiv", "arXiv", "preprints", "Preprints in cs.CV, eess.IV, physics.med-ph", "none"),
        _info("medrxiv", "medRxiv", "preprints", "Health-science preprints (via Europe PMC)", "none"),
        _info("biorxiv", "bioRxiv", "preprints", "Biology preprints (via Europe PMC)", "none"),
        _info(
            "openalex",
            "OpenAlex",
            "multidisciplinary",
            "Open catalogue of scholarly works",
            "optional",
            env=("OPENALEX_API_KEY",),
        ),
        _info(
            "semantic_scholar",
            "Semantic Scholar",
            "multidisciplinary",
            "AI2 paper graph; open-access PDF links",
            "optional",
            env=("S2_API_KEY",),
            capabilities=("search", "fulltext"),
            resolvers=("semantic_scholar_oa",),
        ),
        _info(
            "core",
            "CORE",
            "multidisciplinary",
            "Open-access research outputs and full texts",
            "required",
            env=("CORE_API_KEY",),
            capabilities=("search", "fulltext"),
            resolvers=("core",),
        ),
        _info(
            "unpaywall",
            "Unpaywall",
            "multidisciplinary",
            "Legal open-access PDFs by DOI",
            "none",
            capabilities=("fulltext",),
            resolvers=("unpaywall",),
        ),
        _info(
            "ieee",
            "IEEE Xplore",
            "publishers",
            "IEEE journals and conferences (metadata, OA full text)",
            "required",
            env=("IEEE_API_KEY",),
            capabilities=("search", "fulltext"),
            resolvers=("ieee",),
        ),
        _info(
            "springer",
            "Springer Nature",
            "publishers",
            "Springer Nature journals and books; OA JATS full text",
            "required",
            env=("SPRINGER_API_KEY",),
            capabilities=("search", "fulltext"),
            resolvers=("springer_oa",),
        ),
        _info(
            "scopus",
            "Scopus",
            "publishers",
            "Elsevier abstract and citation database",
            "required",
            env=("ELSEVIER_API_KEY", "ELSEVIER_INSTTOKEN"),
        ),
        _info(
            "sciencedirect",
            "ScienceDirect",
            "publishers",
            "Elsevier full text where your institution is entitled",
            "required",
            env=("ELSEVIER_API_KEY", "ELSEVIER_INSTTOKEN"),
            capabilities=("fulltext",),
            resolvers=("sciencedirect",),
        ),
        _info(
            "crossref",
            "Crossref",
            "identity",
            "DOI registry: search, DOI lookup for papers without one",
            "none",
        ),
    )
}


class Keyed:
    """Shared plumbing of the new connectors."""

    name = ""
    required_env = None  # a key this source cannot work without
    optional_env = None  # a key that raises the rate limit

    def __init__(self, store, client=None, years=None, contact=None, keywords=None):
        self.store = store
        self.client = client
        self.years = years
        self.contact = contact
        self.keywords = keywords  # {all, any, none}: local filter for sources without boolean search

    def key(self):
        if self.required_env:
            value = env_key(self.required_env)
            if value is None:
                raise SourceKeyMissing(self.name, self.required_env)
            return value
        return env_key(self.optional_env) if self.optional_env else None

    def get(self, url, params, key=None, headers=None, decode=None):
        return fetch(
            self.client,
            url,
            params,
            self.name,
            decode or (lambda response: response.json()),
            headers=headers,
            secret=key is not None,
            contact=self.contact,
            keyed=key is not None,
        )

    def keep(self, raw_payload, key):
        return self.store.raw(scrub(raw_payload, key))

    @property
    def span(self):
        if self.years is None or (self.years.start is None and self.years.end is None):
            return None
        return self.years.start, self.years.end

    def search(self, query, limit, raw=False):
        return self.search_with_total(query, limit, raw).papers

    def filtered(self, papers, raw):
        if raw and self.keywords and self.name in PLAIN:
            return [p for p in papers if matches(self.keywords, f"{p.title} {p.abstract}")]
        return papers

    def paper(self, local_id, title, abstract, year, url, query, retrieved, raw_hash, **ids):
        record = f"{self.name}:{local_id}"
        return Paper(
            id=record,
            title=" ".join(plain(title).split()),
            abstract=" ".join(plain(abstract).split()),
            year=str(year or "")[:4],
            doi=normalize_doi(ids.pop("doi", None) or ""),
            pmcid=ids.pop("pmcid", None) or "",
            pmid=str(ids.pop("pmid", None) or ""),
            arxiv=re.sub(r"v\d+$", "", ids.pop("arxiv", None) or ""),
            s2=ids.pop("s2", None) or "",
            sources=[self.name],
            provenance=[
                Source(
                    connector=self.name,
                    record_id=record,
                    url=url,
                    query=query,
                    retrieved_at=retrieved,
                    raw_sha256=raw_hash,
                )
            ],
        )


def _now():
    return datetime.now(UTC).isoformat()


def _malformed(name, exc):
    raise SourceUnavailable(name) from exc


PLAIN_NOTE = "{label}'s total counts the plain query; results were then filtered locally by the keywords"


class SemanticScholar(Keyed):
    """Graph API relevance search (no boolean syntax: see querybuild.PLAIN). Optional S2_API_KEY header."""

    name = "semantic_scholar"
    optional_env = "S2_API_KEY"
    endpoint = "https://api.semanticscholar.org/graph/v1/paper/search"
    fields = "paperId,externalIds,title,abstract,year,openAccessPdf"
    page = 100

    def search_with_total(self, query, limit, raw=False):
        key = self.key()
        params = {"query": query, "fields": self.fields}
        if self.span:
            params["year"] = f"{self.span[0] or ''}-{self.span[1] or ''}"
        headers = {"x-api-key": key} if key else None
        papers, total, offset = [], None, 0
        while offset < limit:
            params.update(offset=offset, limit=min(self.page, limit - offset))
            payload = self.get(self.endpoint, dict(params), key, headers)
            raw_hash, retrieved = self.keep(payload, key), _now()
            try:
                total = _total(payload.get("total")) if total is None else total
                rows = payload["data"]
                papers.extend(self._paper(row, query, retrieved, raw_hash) for row in rows)
            except (KeyError, TypeError, ValueError, AttributeError) as exc:
                _malformed(self.name, exc)
            following = payload.get("next")
            if not rows or not isinstance(following, int) or following <= offset:
                break  # last page, or a cursor that does not advance
            offset = following
        note = PLAIN_NOTE.format(label="Semantic Scholar") if raw and self.keywords else None
        sent = query + (f" [year {params['year']}]" if "year" in params else "")
        return SearchResult(self.filtered(papers[:limit], raw), total, sent, note)

    def _paper(self, row, query, retrieved, raw_hash):
        ids = row.get("externalIds") or {}
        pmc = ids.get("PubMedCentral")
        return self.paper(
            row["paperId"],
            row.get("title"),
            row.get("abstract"),
            row.get("year"),
            f"https://www.semanticscholar.org/paper/{row['paperId']}",
            query,
            retrieved,
            raw_hash,
            doi=ids.get("DOI"),
            pmid=ids.get("PubMed"),
            pmcid=f"PMC{pmc}" if pmc else "",
            arxiv=ids.get("ArXiv"),
            s2=row["paperId"],
        )


class Crossref(Keyed):
    """Works search (`query.bibliographic`, no boolean syntax: see querybuild.PLAIN), polite pool via mailto."""

    name = "crossref"
    endpoint = "https://api.crossref.org/works"
    select = "DOI,title,issued,abstract,type"

    def params(self, query, rows):
        params = {"query.bibliographic": query, "rows": rows, "select": self.select}
        filters = []
        if self.span and self.span[0]:
            filters.append(f"from-pub-date:{self.span[0]}")
        if self.span and self.span[1]:
            filters.append(f"until-pub-date:{self.span[1]}")
        if filters:
            params["filter"] = ",".join(filters)
        if self.contact:
            params["mailto"] = self.contact
        return params

    def search_with_total(self, query, limit, raw=False):
        params = self.params(query, min(limit, 1000))
        payload = self.get(self.endpoint, params)
        raw_hash, retrieved = self.keep(payload, None), _now()
        try:
            message = payload["message"]
            papers = [self._paper(row, query, retrieved, raw_hash) for row in message["items"]]
        except (KeyError, TypeError, ValueError, AttributeError, IndexError) as exc:
            _malformed(self.name, exc)
        note = PLAIN_NOTE.format(label="Crossref") if raw and self.keywords else None
        sent = query + (f" [{params['filter']}]" if "filter" in params else "")
        return SearchResult(self.filtered(papers, raw), _total(message.get("total-results")), sent, note)

    @staticmethod
    def year(row):
        parts = ((row.get("issued") or {}).get("date-parts") or [[None]])[0]
        return parts[0] if parts and parts[0] else ""

    def _paper(self, row, query, retrieved, raw_hash):
        doi = normalize_doi(row["DOI"])
        return self.paper(
            doi,
            (row.get("title") or [""])[0],
            row.get("abstract"),
            self.year(row),
            f"https://doi.org/{doi}",
            query,
            retrieved,
            raw_hash,
            doi=doi,
        )


class CrossrefEnricher:
    """DOIs for papers without one: Crossref lookup by title (+ year), accepted only on an exact normalized
    title and equal year. Bounded per run; answers cached in the store's `lookups` table (Raw Layer)."""

    MAX_LOOKUPS = 50

    def __init__(self, store, client=None, contact=None, limit=MAX_LOOKUPS):
        self.crossref = Crossref(store, client, contact=contact)
        self.store = store
        self.limit = limit

    @staticmethod
    def norm(title):
        return re.sub(r"\W+", " ", plain(title).casefold()).strip()

    def lookup(self, title, year):
        key = {"source": "crossref", "title": self.norm(title), "year": year}
        hit = self.store.cached_lookup(key)
        if hit is None:
            self.crossref.years = _Span(int(year), int(year)) if str(year).isdigit() else None
            params = self.crossref.params(title, 3)
            payload = self.crossref.get(self.crossref.endpoint, params)
            try:
                rows = payload["message"]["items"]
                hit = {
                    "doi": next(
                        (
                            normalize_doi(r["DOI"])
                            for r in rows
                            if self.norm((r.get("title") or [""])[0]) == key["title"]
                            and str(Crossref.year(r)) == str(year)
                        ),
                        "",
                    )
                }
            except (KeyError, TypeError, AttributeError) as exc:
                _malformed("crossref", exc)
            self.store.record_lookup(key, hit)
        return hit["doi"]

    def enrich(self, papers):
        done, out = 0, []
        for paper in papers:
            if not paper.doi and paper.title.strip() and paper.year and done < self.limit:
                done += 1
                doi = self.lookup(paper.title, paper.year)
                if doi:
                    paper = paper.model_copy(update={"doi": doi})
            out.append(paper)
        return out


@dataclass
class _Span:
    start: int | None
    end: int | None


class PubMed(Keyed):
    """NCBI E-utilities: esearch (JSON ids, relevance order) then efetch (XML records). tool/email identify us;
    NCBI_API_KEY (optional) raises the limit from 3 to 10 requests per second."""

    name = "pubmed"
    optional_env = "NCBI_API_KEY"
    base = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/"

    def common(self, key):
        params = {"db": "pubmed", "tool": "research-agent"}
        if self.contact:
            params["email"] = self.contact
        if key:
            params["api_key"] = key
        return params

    def term(self, query):
        if not self.span:
            return query
        return f"({query}) AND ({self.span[0] or 1800}:{self.span[1] or 3000}[dp])"

    def search_with_total(self, query, limit, raw=False):
        key = self.key()
        term = self.term(query)
        params = self.common(key) | {"term": term, "retmax": limit, "retmode": "json", "sort": "relevance"}
        found = self.get(self.base + "esearch.fcgi", params, key)
        try:
            result = found["esearchresult"]
            ids = [str(i) for i in result["idlist"]][:limit]
        except (KeyError, TypeError) as exc:
            _malformed(self.name, exc)
        if not ids:
            return SearchResult([], _total(result.get("count")), term)
        params = self.common(key) | {"id": ",".join(ids), "retmode": "xml"}
        xml = self.get(self.base + "efetch.fcgi", params, key, decode=lambda response: response.text)
        raw_hash, retrieved = self.keep({"esearch": found, "efetch": xml}, key), _now()
        try:
            root = ET.fromstring(xml)
            papers = [self._paper(a, term, retrieved, raw_hash) for a in root.findall("PubmedArticle")]
        except (ET.ParseError, AttributeError, ValueError, TypeError) as exc:
            _malformed(self.name, exc)
        return SearchResult(papers, _total(result.get("count")), term)

    def _paper(self, article, query, retrieved, raw_hash):
        citation = article.find("MedlineCitation")
        pmid = citation.findtext("PMID").strip()
        art = citation.find("Article")
        title = " ".join("".join(art.find("ArticleTitle").itertext()).split())
        parts = []
        for node in art.findall("Abstract/AbstractText"):
            text = " ".join("".join(node.itertext()).split())
            label = node.get("Label")
            parts.append(f"{label}: {text}" if label and text else text)
        year = (
            art.findtext("Journal/JournalIssue/PubDate/Year")
            or (art.findtext("Journal/JournalIssue/PubDate/MedlineDate") or "")[:4]
            or art.findtext("ArticleDate/Year")
            or ""
        )
        ids = {
            i.get("IdType"): (i.text or "").strip()
            for i in article.findall("PubmedData/ArticleIdList/ArticleId")
        }
        return self.paper(
            pmid,
            title,
            " ".join(p for p in parts if p),
            year,
            f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
            query,
            retrieved,
            raw_hash,
            doi=ids.get("doi"),
            pmid=pmid,
            pmcid=ids.get("pmc"),
        )


PREPRINT_SERVERS = {"medrxiv": "medRxiv", "biorxiv": "bioRxiv"}


class Preprints(EuropePMC):
    """medRxiv / bioRxiv through Europe PMC's preprint index (source PPR, publisher = the server). Their own API
    only lists whole date windows (no search), so Europe PMC gives the same records with a real query and an
    honest hit count. The filter is appended after the query (an override cannot drop it)."""

    def __init__(self, store, name, client=None, years=None):
        super().__init__(store, client, years)
        self.name = name

    def full_query(self, query):
        return super().full_query(f'({query}) AND (SRC:PPR AND PUBLISHER:"{PREPRINT_SERVERS[self.name]}")')


class Core(Keyed):
    """CORE v3 works search (Bearer CORE_API_KEY, required). The query matches all fields incl. full text."""

    name = "core"
    required_env = "CORE_API_KEY"
    endpoint = "https://api.core.ac.uk/v3/search/works"
    page = 100

    def full_query(self, query):
        if not self.span:
            return query
        parts = [f"({query})"]
        if self.span[0]:
            parts.append(f"yearPublished>={self.span[0]}")
        if self.span[1]:
            parts.append(f"yearPublished<={self.span[1]}")
        return " AND ".join(parts)

    def search_with_total(self, query, limit, raw=False):
        key = self.key()
        q = self.full_query(query)
        papers, total, offset = [], None, 0
        while offset < limit:
            size = min(self.page, limit - offset)
            params = {"q": q, "limit": size, "offset": offset}
            payload = self.get(self.endpoint, params, key, {"Authorization": f"Bearer {key}"})
            raw_hash, retrieved = self.keep(payload, key), _now()
            try:
                total = _total(payload.get("totalHits")) if total is None else total
                rows = payload["results"]
                papers.extend(self._paper(row, q, retrieved, raw_hash) for row in rows)
            except (KeyError, TypeError, ValueError, AttributeError) as exc:
                _malformed(self.name, exc)
            offset += size
            if len(rows) < size or (total is not None and offset >= total):
                break
        return SearchResult(papers[:limit], total, q)

    def _paper(self, row, query, retrieved, raw_hash):
        rid = str(row["id"])
        return self.paper(
            rid,
            row.get("title"),
            row.get("abstract"),
            row.get("yearPublished"),
            f"https://core.ac.uk/works/{rid}",
            query,
            retrieved,
            raw_hash,
            doi=row.get("doi"),
            pmid=row.get("pubmedId"),
            arxiv=row.get("arxivId"),
        )


class IEEE(Keyed):
    """IEEE Xplore Metadata Search API (apikey param, IEEE_API_KEY required)."""

    name = "ieee"
    required_env = "IEEE_API_KEY"
    endpoint = "https://ieeexploreapi.ieee.org/api/v1/search/articles"

    def search_with_total(self, query, limit, raw=False):
        key = self.key()
        params = {"querytext": query, "max_records": min(limit, 200), "start_record": 1, "format": "json"}
        if self.span and self.span[0]:
            params["start_year"] = self.span[0]
        if self.span and self.span[1]:
            params["end_year"] = self.span[1]
        payload = self.get(self.endpoint, params | {"apikey": key}, key)
        raw_hash, retrieved = self.keep(payload, key), _now()
        try:
            papers = [self._paper(row, query, retrieved, raw_hash) for row in payload.get("articles") or []]
        except (KeyError, TypeError, ValueError, AttributeError) as exc:
            _malformed(self.name, exc)
        years = "".join(f" [{k} {params[k]}]" for k in ("start_year", "end_year") if k in params)
        return SearchResult(papers, _total(payload.get("total_records")), query + years)

    def _paper(self, row, query, retrieved, raw_hash):
        number = str(row["article_number"])
        return self.paper(
            number,
            row.get("title"),
            row.get("abstract"),
            row.get("publication_year"),
            f"https://ieeexplore.ieee.org/document/{number}/",
            query,
            retrieved,
            raw_hash,
            doi=row.get("doi"),
        )


class Springer(Keyed):
    """Springer Nature Meta API v2 (api_key param, SPRINGER_API_KEY required); the response echoes the key,
    which is scrubbed before the Raw Layer."""

    name = "springer"
    required_env = "SPRINGER_API_KEY"
    endpoint = "https://api.springernature.com/meta/v2/json"
    page = 25

    def full_query(self, query):
        if not self.span:
            return query
        parts = [f"({query})"]
        if self.span[0]:
            parts.append(f"datefrom:{self.span[0]}-01-01")
        if self.span[1]:
            parts.append(f"dateto:{self.span[1]}-12-31")
        return " AND ".join(parts)

    def search_with_total(self, query, limit, raw=False):
        key = self.key()
        q = self.full_query(query)
        papers, total, start = [], None, 1
        while start <= limit:
            size = min(self.page, limit - start + 1)
            payload = self.get(self.endpoint, {"q": q, "s": start, "p": size, "api_key": key}, key)
            raw_hash, retrieved = self.keep(payload, key), _now()
            try:
                total = _total((payload.get("result") or [{}])[0].get("total")) if total is None else total
                rows = payload["records"]
                papers.extend(self._paper(row, q, retrieved, raw_hash) for row in rows)
            except (KeyError, TypeError, ValueError, AttributeError, IndexError) as exc:
                _malformed(self.name, exc)
            start += size
            if len(rows) < size or (total is not None and start > total):
                break
        return SearchResult(papers[:limit], total, q)

    @staticmethod
    def abstract(value):
        if isinstance(value, dict):
            p = value.get("p") or []
            return " ".join(p if isinstance(p, list) else [p])
        return value or ""

    def _paper(self, row, query, retrieved, raw_hash):
        doi = normalize_doi(row.get("doi") or row["identifier"].removeprefix("doi:"))
        urls = [u.get("value") for u in row.get("url") or [] if u.get("value")]
        return self.paper(
            doi,
            row.get("title"),
            self.abstract(row.get("abstract")),
            (row.get("publicationDate") or "")[:4],
            urls[0] if urls else f"https://doi.org/{doi}",
            query,
            retrieved,
            raw_hash,
            doi=doi,
        )


class Scopus(Keyed):
    """Elsevier Scopus Search API, STANDARD view (headers X-ELS-APIKey, optional X-ELS-Insttoken). STANDARD has
    no abstract; a COMPLETE-view `dc:description` is read when present."""

    name = "scopus"
    required_env = "ELSEVIER_API_KEY"
    endpoint = "https://api.elsevier.com/content/search/scopus"
    page = 25

    def headers(self, key):
        headers = {"X-ELS-APIKey": key, "Accept": "application/json"}
        token = env_key("ELSEVIER_INSTTOKEN")
        if token:
            headers["X-ELS-Insttoken"] = token
        return headers

    def full_query(self, query):
        if not self.span:
            return query
        parts = [f"({query})"]
        if self.span[0]:
            parts.append(f"PUBYEAR > {self.span[0] - 1}")
        if self.span[1]:
            parts.append(f"PUBYEAR < {self.span[1] + 1}")
        return " AND ".join(parts)

    def search_with_total(self, query, limit, raw=False):
        key = self.key()
        q = self.full_query(query)
        papers, total, start = [], None, 0
        while start < limit:
            size = min(self.page, limit - start)
            payload = self.get(
                self.endpoint, {"query": q, "start": start, "count": size}, key, self.headers(key)
            )
            raw_hash, retrieved = self.keep(payload, key), _now()
            try:
                results = payload["search-results"]
                total = _total(results.get("opensearch:totalResults")) if total is None else total
                rows = [e for e in results.get("entry") or [] if "error" not in e]
                papers.extend(self._paper(row, q, retrieved, raw_hash) for row in rows)
            except (KeyError, TypeError, ValueError, AttributeError) as exc:
                _malformed(self.name, exc)
            start += size
            if len(rows) < size or (total is not None and start >= total):
                break
        return SearchResult(papers[:limit], total, q)

    def _paper(self, row, query, retrieved, raw_hash):
        sid = row["dc:identifier"].removeprefix("SCOPUS_ID:")
        return self.paper(
            sid,
            row.get("dc:title"),
            row.get("dc:description"),
            (row.get("prism:coverDate") or "")[:4],
            f"https://www.scopus.com/record/display.uri?eid={row.get('eid') or '2-s2.0-' + sid}",
            query,
            retrieved,
            raw_hash,
            doi=row.get("prism:doi"),
            pmid=row.get("pubmed-id"),
        )


CONNECTORS = {
    "semantic_scholar": SemanticScholar,
    "crossref": Crossref,
    "pubmed": PubMed,
    "core": Core,
    "ieee": IEEE,
    "springer": Springer,
    "scopus": Scopus,
}


def make_connector(source, domain, store, mode, client=None):
    """The connector for one SourceSpec of a field (demo: synthetic records, no network)."""
    name = source.name
    if mode == "demo":
        return DemoConnector(store, source=name)
    if name == "europepmc":
        return EuropePMC(store, client, years=domain.years)
    if name == "openalex":
        return OpenAlex(store, client, years=domain.years, contact=source.contact)
    if name == "arxiv":
        return ArXiv(store, client, years=domain.years)
    if name in PREPRINT_SERVERS:
        return Preprints(store, name, client, years=domain.years)
    keywords = domain.keywords.model_dump() if domain.keywords else None
    return CONNECTORS[name](store, client, years=domain.years, contact=source.contact, keywords=keywords)
