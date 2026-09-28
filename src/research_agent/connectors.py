"""Network retrieval and identity resolution contain no LLM calls."""

import hashlib
import html
import json
import re
import time
from datetime import UTC, datetime
from typing import Protocol

import httpx

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


class SourceUnavailable(RuntimeError):
    """A source failed after retries or answered with something unreadable. Fail closed: the run stops
    (checkpoint kept). The message is only the source name, so it is safe to show and to log."""

    def __init__(self, source):
        super().__init__(source)
        self.source = source


def fetch(client, url, params, source, decode):
    """One GET with the Europe PMC policy of M1: 3 attempts, backoff 1 s then 2 s on transport errors and
    429/5xx, 30 s timeout. Any failure, including an undecodable body, raises SourceUnavailable."""

    def attempts(http):
        for attempt in range(3):
            try:
                response = http.get(url, params=params)
                response.raise_for_status()
                return decode(response)
            except (httpx.TransportError, httpx.HTTPStatusError) as exc:
                retryable = (
                    not isinstance(exc, httpx.HTTPStatusError) or exc.response.status_code in RETRYABLE
                )
                if not retryable or attempt == 2:
                    raise SourceUnavailable(source) from exc
                time.sleep(2**attempt)
            except ValueError as exc:
                raise SourceUnavailable(source) from exc

    if client is not None:
        return attempts(client)
    with httpx.Client(timeout=30, follow_redirects=True) as http:
        return attempts(http)


class Connector(Protocol):
    def search(self, query: str, limit: int) -> list[Paper]: ...


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

    def search(self, query, limit):
        query = self.full_query(query)
        params = {"query": query, "format": "json", "resultType": "core", "pageSize": limit}
        # A single bounded page per query; raw payload retained before parsing.
        payload = fetch(self.client, self.endpoint, params, self.name, lambda response: response.json())
        raw_hash = self.store.raw(payload)
        retrieved = datetime.now(UTC).isoformat()
        try:
            return [self._paper(row, query, retrieved, raw_hash) for row in payload["resultList"]["result"]]
        except (KeyError, TypeError, ValueError) as exc:
            raise SourceUnavailable(self.name) from exc

    def _paper(self, row, query, retrieved, raw_hash):
        source, rid = row["source"], row["id"]
        return Paper(
            id=f"{source}:{rid}",
            title=plain(row.get("title")),
            abstract=plain(row.get("abstractText")),
            year=str(row.get("pubYear", "")),
            doi=normalize_doi(row.get("doi", "")),
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


class DemoConnector:
    """Synthetic fixtures, intentionally not real publications or scientific evidence."""

    def __init__(self, store, source="demo"):
        self.store = store
        self.source = source

    def search(self, query, limit):
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
        return papers


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
        sources = {canonical_json(s.model_dump()): s for p in group for s in p.provenance}
        primary.provenance = [sources[k] for k in sorted(sources)]
        result.append(primary)
    return sorted(result, key=lambda p: p.id)
