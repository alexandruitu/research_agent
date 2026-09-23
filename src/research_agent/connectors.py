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


class Connector(Protocol):
    def search(self, query: str, limit: int) -> list[Paper]: ...


class EuropePMC:
    endpoint = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"

    def __init__(self, store, client=None):
        self.store = store
        self.client = client

    def search(self, query, limit):
        params = {"query": query, "format": "json", "resultType": "core", "pageSize": limit}

        # A single bounded page per query in M1; raw payload retained before parsing.
        def fetch(client):
            for attempt in range(3):
                try:
                    response = client.get(self.endpoint, params=params)
                    response.raise_for_status()
                    return response.json()
                except (httpx.TransportError, httpx.HTTPStatusError) as exc:
                    retryable = not isinstance(exc, httpx.HTTPStatusError) or exc.response.status_code in (
                        429,
                        500,
                        502,
                        503,
                        504,
                    )
                    if not retryable or attempt == 2:
                        raise
                    time.sleep(2**attempt)

        if self.client is not None:
            payload = fetch(self.client)
        else:
            with httpx.Client(timeout=30) as client:
                payload = fetch(client)
        raw_hash = self.store.raw(payload)
        retrieved = datetime.now(UTC).isoformat()
        result = []
        for row in payload["resultList"]["result"]:
            source, rid = row["source"], row["id"]
            result.append(
                Paper(
                    id=f"{source}:{rid}",
                    title=plain(row.get("title")),
                    abstract=plain(row.get("abstractText")),
                    year=str(row.get("pubYear", "")),
                    doi=normalize_doi(row.get("doi", "")),
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
            )
        return result


class DemoConnector:
    """Synthetic fixtures, intentionally not real publications or scientific evidence."""

    def __init__(self, store):
        self.store = store

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
