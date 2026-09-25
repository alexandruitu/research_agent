import json

import httpx
import pytest
from pydantic import ValidationError

from research_agent.agents import Evaluator
from research_agent.connectors import DemoConnector
from research_agent.graph import build_graph
from research_agent.jev import JevError, JevScreener, JevThresholds
from research_agent.schemas import Contract
from research_agent.storage import Store

PAPER = {"id": "p:1", "title": "Deep learning CT-FFR", "abstract": "We trained a network on CT."}
TOPIC = "deep learning CT-FFR"


def answer(p, model="jev-1.13.0"):
    return {
        "model": model,
        "answers": {"topic_match": {"type": "noul", "noul": p}},
        "usage": {"input_tokens": 10, "output_tokens": 1},
    }


class Api:
    """Mock TypeSafe endpoint; `probability` may be a float or a function of the request body."""

    def __init__(self, probability=0.95, statuses=()):
        self.probability = probability
        self.statuses = list(statuses)
        self.requests = []

    def __call__(self, request):
        body = json.loads(request.content)
        self.requests.append((request, body))
        if self.statuses:
            status = self.statuses.pop(0)
            if status != 200:
                return httpx.Response(status, json={"detail": "secret-key-echo"})
        p = self.probability(body) if callable(self.probability) else self.probability
        return httpx.Response(200, json=answer(p))

    def client(self):
        return httpx.Client(transport=httpx.MockTransport(self))


def screener(tmp_path, api, **kwargs):
    return JevScreener(Store(tmp_path), "test-key", client=api.client(), sleep=lambda _s: None, **kwargs)


def test_request_contract_sends_evidence_only(tmp_path):
    api = Api(0.95)
    verdict = screener(tmp_path, api).screen(TOPIC, PAPER)
    request, body = api.requests[0]
    assert str(request.url) == "https://api.typesafe.ai/v1/systemone"
    assert request.headers["authorization"] == "Bearer test-key"
    assert body["model"] == "jev-latest"
    assert body["state"] == {"title": PAPER["title"], "abstract": PAPER["abstract"]}
    question = body["questions"]["topic_match"]
    assert question["type"] == "noul" and TOPIC in question["instructions"]
    assert set(question["criteria"]) == {"true", "false"}
    assert verdict["decision"] == "include"
    assert verdict["probabilities"] == {"topic_match": 0.95}
    assert verdict["model_version"] == "jev-1.13.0"


@pytest.mark.parametrize(
    ("p", "decision"),
    [
        (0.95, "include"),
        (0.8, "include"),
        (0.79, "escalate"),
        (0.5, "escalate"),
        (0.06, "escalate"),
        (0.05, "exclude"),
        (0.0, "exclude"),
    ],
)
def test_asymmetric_thresholds_favour_recall(tmp_path, p, decision):
    # include needs confidence >= 0.6 (p >= 0.8); exclude needs >= 0.9 (p <= 0.05).
    verdict = screener(tmp_path, Api(p)).screen(TOPIC, PAPER)
    assert verdict["decision"] == decision


def test_multiple_criteria_all_must_hold_and_any_confident_no_excludes(tmp_path):
    criteria = {
        "a": {"type": "noul", "instructions": "A?", "criteria": {"true": "yes", "false": "no"}},
        "b": {"type": "noul", "instructions": "B?", "criteria": {"true": "yes", "false": "no"}},
    }

    def respond(pa, pb):
        def handler(request):
            answers = {"a": {"type": "noul", "noul": pa}, "b": {"type": "noul", "noul": pb}}
            return httpx.Response(200, json={"model": "jev-1", "answers": answers})

        return httpx.Client(transport=httpx.MockTransport(handler))

    def run(pa, pb, name):
        s = JevScreener(Store(tmp_path / name), "k", client=respond(pa, pb), criteria=criteria)
        return s.screen(TOPIC, PAPER)["decision"]

    assert run(0.9, 0.9, "1") == "include"
    assert run(0.9, 0.5, "2") == "escalate"
    assert run(0.9, 0.01, "3") == "exclude"


def test_raw_probabilities_cached_and_thresholds_not_part_of_key(tmp_path):
    api = Api(0.7)
    first = screener(tmp_path, api).screen(TOPIC, PAPER)
    assert first["decision"] == "escalate" and first["cached"] is False
    looser = screener(tmp_path, api, thresholds=JevThresholds(min_confidence=0.3))
    second = looser.screen(TOPIC, PAPER)
    assert second["decision"] == "include" and second["cached"] is True
    assert len(api.requests) == 1
    with Store(tmp_path).connect() as db:
        role, model, output = db.execute("SELECT role, model, output FROM calls").fetchone()
    assert (role, model) == ("jev_screen", "jev-latest")
    assert json.loads(output)["model"] == "jev-1.13.0"


def test_different_topic_or_abstract_is_a_cache_miss(tmp_path):
    api = Api(0.95)
    s = screener(tmp_path, api)
    s.screen(TOPIC, PAPER)
    s.screen("another topic", PAPER)
    s.screen(TOPIC, dict(PAPER, abstract="Different abstract."))
    assert len(api.requests) == 3


def test_transient_errors_are_retried_then_fail_closed(tmp_path):
    api = Api(0.95, statuses=[529, 429, 200])
    assert screener(tmp_path, api).screen(TOPIC, PAPER)["decision"] == "include"
    assert len(api.requests) == 3
    api = Api(0.95, statuses=[529, 529, 529, 529])
    with pytest.raises(httpx.HTTPStatusError):
        screener(tmp_path / "x", api).screen(TOPIC, PAPER)


def test_auth_and_validation_errors_are_not_retried_and_do_not_leak(tmp_path):
    for status in (401, 422):
        api = Api(statuses=[status])
        with pytest.raises(httpx.HTTPStatusError) as caught:
            screener(tmp_path / str(status), api).screen(TOPIC, PAPER)
        assert len(api.requests) == 1
        assert "test-key" not in str(caught.value)


@pytest.mark.parametrize(
    "payload",
    [
        {"model": "jev-1", "answers": {}},
        {"model": "jev-1", "answers": {"topic_match": {"type": "noul", "noul": 1.5}}},
        {"model": "jev-1", "answers": {"topic_match": {"type": "choice", "choice": "x"}}},
        {"answers": {"topic_match": {"type": "noul", "noul": 0.9}}},
    ],
)
def test_malformed_response_fails_closed_and_is_not_cached(tmp_path, payload):
    client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, json=payload)))
    s = JevScreener(Store(tmp_path), "k", client=client)
    with pytest.raises(JevError):
        s.screen(TOPIC, PAPER)
    with Store(tmp_path).connect() as db:
        assert db.execute("SELECT count(*) FROM calls").fetchone()[0] == 0


def test_threshold_validation():
    with pytest.raises(ValueError):
        JevThresholds(min_confidence=1.2)
    with pytest.raises(ValueError, match="stricter"):
        JevThresholds(min_confidence=0.95, exclude_min_confidence=0.9)


def test_contract_jev_requires_live_mode():
    with pytest.raises(ValidationError, match="live"):
        Contract(topic="test topic", jev=True)
    assert Contract(topic="test topic", mode="live", jev=True).jev_min_confidence == 0.6


# --- cascade inside the graph -------------------------------------------------------------------


def by_paper(mapping):
    def probability(body):
        return mapping[body["state"]["title"].split(":")[0].split()[-1]]

    return probability


def run_graph(tmp_path, api, screen_calls):
    store = Store(tmp_path)

    class Counting(Evaluator):
        def _demo(self, role, payload):
            if role == "screen":
                screen_calls.append(payload["paper"]["id"])
                if payload["paper"]["id"] == "demo:3":
                    from research_agent.schemas import Screen

                    return Screen(decision="exclude", reason="LLM says no")
            return super()._demo(role, payload)

    jev = JevScreener(store, "k", client=api.client())
    graph = build_graph(DemoConnector(store), Counting(store), jev=jev)
    return graph.invoke({"contract": Contract(topic="test topic", max_papers=3).model_dump()}), store


def test_cascade_routes_only_uncertain_papers_to_llm(tmp_path):
    api = Api(by_paper({"1": 0.97, "2": 0.02, "3": 0.5}))
    llm_screens = []
    result, _ = run_graph(tmp_path, api, llm_screens)
    screens = result["screens"]
    assert llm_screens == ["demo:3"]
    assert screens["demo:1"]["tier"] == "jev" and screens["demo:1"]["decision"] == "include"
    assert screens["demo:2"]["tier"] == "jev" and screens["demo:2"]["decision"] == "exclude"
    assert screens["demo:3"]["tier"] == "llm" and screens["demo:3"]["decision"] == "exclude"
    # Audit: Jev decision and probabilities are kept even when the LLM decided.
    assert screens["demo:3"]["jev"]["decision"] == "escalate"
    assert screens["demo:3"]["jev"]["probabilities"] == {"topic_match": 0.5}
    assert screens["demo:1"]["jev"]["model_version"] == "jev-1.13.0"
    assert "demo:2" not in result["evidence"] and "demo:1" in result["evidence"]


def test_llm_receives_no_jev_conclusion_on_escalation(tmp_path):
    api = Api(0.5)
    store = Store(tmp_path)
    seen = []

    class Spy(Evaluator):
        def ask(self, role, schema, payload):
            if role == "screen":
                seen.append(payload)
            return super().ask(role, schema, payload)

    graph = build_graph(DemoConnector(store), Spy(store), jev=JevScreener(store, "k", client=api.client()))
    graph.invoke({"contract": Contract(topic="test topic", max_papers=1).model_dump()})
    assert set(seen[0]) == {"topic", "paper"}


def test_missing_abstract_never_calls_jev(tmp_path):
    api = Api()
    store = Store(tmp_path)
    connector = DemoConnector(store)

    class Missing:
        def search(self, *args):
            p = connector.search("t", 1)[0]
            p.abstract = ""
            return [p]

    jev = JevScreener(store, "k", client=api.client())
    result = build_graph(Missing(), Evaluator(store), jev=jev).invoke(
        {"contract": Contract(topic="test topic").model_dump()}
    )
    assert api.requests == []
    assert result["screens"]["demo:1"]["decision"] == "uncertain"


def test_jev_failure_stops_the_run(tmp_path):
    api = Api(statuses=[401])
    with pytest.raises(httpx.HTTPStatusError):
        run_graph(tmp_path, api, [])


def test_decide_from_probabilities_is_the_screener_rule(tmp_path):
    from research_agent.jev import decide_from_probabilities

    thresholds = JevThresholds()
    s = JevScreener(Store(tmp_path), "k", thresholds=thresholds)
    for p in (0.0, 0.05, 0.06, 0.5, 0.79, 0.8, 1.0):
        assert decide_from_probabilities({"q": p}, thresholds) == s.decide({"q": p})


def test_cached_probabilities_read_without_http(tmp_path):
    from research_agent.storage import MissingCall

    api = Api(0.7)
    screener(tmp_path, api).screen(TOPIC, PAPER)
    offline = JevScreener(Store(tmp_path), "no-key")  # no client: any HTTP attempt would hit the network
    probabilities, version = offline.cached_probabilities(TOPIC, PAPER)
    assert probabilities == {"topic_match": 0.7} and version == "jev-1.13.0"
    with pytest.raises(MissingCall):
        offline.cached_probabilities("another topic", PAPER)
