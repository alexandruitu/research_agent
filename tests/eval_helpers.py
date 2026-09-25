"""Shared fixtures for the eval-harness tests. All network access is mocked."""

import json
import re

import httpx

from research_agent.agents import Evaluator
from research_agent.eval.gold import GoldCandidate, GoldSet
from research_agent.schemas import Screen


def row(i, title=None, doi=None, abstract=None, year="2024"):
    """One Europe PMC result row."""
    return {
        "source": "MED",
        "id": str(i),
        "title": title or f"Paper {i} title",
        "pubYear": year,
        "doi": doi if doi is not None else f"10.1000/p{i}",
        "abstractText": abstract if abstract is not None else f"Abstract {i} on the topic. Second sentence.",
    }


def europepmc(rows_by_query):
    """Mock Europe PMC client. `rows_by_query` is a dict (with optional '*' default) or a callable."""

    def handler(request):
        query = request.url.params["query"]
        if callable(rows_by_query):
            rows = rows_by_query(query)
        else:
            rows = rows_by_query.get(query, rows_by_query.get("*", []))
        return httpx.Response(200, json={"resultList": {"result": rows}})

    return httpx.Client(transport=httpx.MockTransport(handler))


def jev_client(p_by_index):
    """Mock TypeSafe client: probability keyed by the N in the title 'Paper N title' (default 0.5)."""
    calls = []

    def handler(request):
        body = json.loads(request.content)
        index = int(re.search(r"Paper (\d+) title", body["state"]["title"]).group(1))
        calls.append(index)
        p = p_by_index.get(index, 0.5)
        return httpx.Response(
            200, json={"model": "jev-1.13.0", "answers": {"topic_match": {"type": "noul", "noul": p}}}
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    client.calls = calls
    return client


def make_gold(n=12, positive_ids=(1, 2, 3, 4), name="toy"):
    candidates = [
        GoldCandidate(
            id=f"MED:{i}",
            doi=f"10.1000/p{i}",
            title=f"Paper {i} title",
            abstract=f"Abstract {i} on the topic. Second sentence.",
            year="2024",
            label="include" if i in positive_ids else "not_included",
        )
        for i in range(1, n + 1)
    ]
    return GoldSet(
        name=name,
        citation="Test et al. 2026",
        topic="deep learning CT-FFR",
        query="ctffr",
        built_at="2026-09-25T00:00:00+00:00",
        candidates=candidates,
    )


class StubEvaluator(Evaluator):
    """Demo evaluator whose LLM screen excludes chosen ids and counts its screen calls."""

    def __init__(self, store, exclude=(), **kwargs):
        super().__init__(store, **kwargs)
        self.exclude = set(exclude)
        self.screen_calls = 0

    def _demo(self, role, payload):
        if role == "screen":
            self.screen_calls += 1
            if payload["paper"]["id"] in self.exclude:
                return Screen(decision="exclude", reason="off topic")
        return super()._demo(role, payload)
