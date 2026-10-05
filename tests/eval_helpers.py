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


def jev_criteria_client(probability):
    """Mock TypeSafe client answering every question in the request.
    `probability(index, key)` -> p, with index the N in the title 'Paper N title' (None if absent)."""
    calls = []

    def handler(request):
        body = json.loads(request.content)
        match = re.search(r"Paper (\d+) title", body["state"]["title"])
        index = int(match.group(1)) if match else None
        calls.append((index, sorted(body["questions"])))
        answers = {key: {"type": "noul", "noul": probability(index, key)} for key in body["questions"]}
        return httpx.Response(200, json={"model": "jev-1.13.0", "answers": answers})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    client.calls = calls
    return client


def panel_gold(n=10, positive_ids=(1, 2, 3), name="panel-toy"):
    """Gold set whose years alternate 2023/2024, for matched sampling."""
    gold = make_gold(n=n, positive_ids=positive_ids, name=name)
    for c in gold.candidates:
        c.year = "2023" if int(c.id.split(":")[1]) % 2 else "2024"
    return gold


def small_review(path, reviewers=("methodologist", "statistician")):
    """A review.json with two or three short reviewers; the 'shared' item lets item agreement be defined."""
    import json

    panel = [
        {
            "key": key,
            "name": key.title(),
            "version": 1,
            "perspective": f"You review as the {key} of the panel.",
            "items": [
                {"key": "shared", "text": "The data split is described.", "weight": 2},
                {"key": f"{key[0]}1", "text": f"{key} item one.", "red_flag_if": "no"},
            ],
        }
        for key in reviewers
    ]
    review = {"schema": 1, "panel": panel, "editor": {"instructions": "Decide."}, "fulltext": {"sources": []}}
    path.write_text(json.dumps(review))
    return path


class PanelStub(Evaluator):
    """Demo evaluator with paper-dependent panel answers: positives (title 'Paper N' with N in `positives`)
    get 'yes' answers and an include verdict, the rest 'no' and exclude; `contrarian` flips its verdict and
    answers 'not_reported' on its own item; counts calls per role."""

    def __init__(self, store, positives=(1, 2, 3), contrarian="statistician", **kwargs):
        super().__init__(store, **kwargs)
        self.positives, self.contrarian, self.calls = set(positives), contrarian, {}

    def _demo(self, role, payload):
        from research_agent.schemas import EditorDecision, ItemAnswer, PanelReview

        self.calls[role] = self.calls.get(role, 0) + 1
        index = int(re.search(r"Paper (\d+) title", payload["paper"]["title"]).group(1))
        good = index in self.positives
        if role.startswith("review:"):
            content = payload["text"]["content"]
            first, last = content.split(". ")[0] + ".", content.split(". ")[-1]
            own = role == f"review:{self.contrarian}"
            answers = [
                ItemAnswer(key=i["key"], answer="not_reported", quote="", section="")
                if own and i["key"] != "shared"
                else ItemAnswer(
                    key=i["key"], answer="yes" if good else "no", quote=first if good else last, section=""
                )
                for i in payload["items"]
            ]
            verdict = ("exclude" if good else "include") if own else ("include" if good else "exclude")
            return PanelReview(
                answers=answers, verdict=verdict, strengths=["s"], weaknesses=["w"], summary="stub"
            )
        if role == "editor":
            return EditorDecision(
                verdict="include" if good else "exclude", reason=f"{len(payload['reviews'])} reviews"
            )
        return super()._demo(role, payload)


class FakeFulltext:
    """Full text for chosen paper ids (text_source 'pmc_oa'), the abstract for the rest."""

    def __init__(self, ids=()):
        self.ids = set(ids)

    def resolve(self, paper):
        source = "pmc_oa" if paper["id"] in self.ids else "abstract"
        return {
            "text_source": source,
            "content": paper["abstract"],
            "sections": [],
            "truncated": False,
            "origin": None,
            "reason": None,
            "text_licence": source,
        }
