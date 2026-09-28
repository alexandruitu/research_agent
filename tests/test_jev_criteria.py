import json

import httpx
import pytest
from eval_helpers import jev_criteria_client

from research_agent.jev import JevError, JevScreener, criteria_questions
from research_agent.storage import MissingCall, Store

DOMAIN = {
    "topic": "deep learning CT-FFR",
    "criteria": {
        "include": [{"key": "i1", "text": "The study uses deep learning."}],
        "exclude": [{"key": "e1", "text": "The paper is a review."}],
    },
    "thresholds": {
        "keep_min": 0.8,
        "include_fail_max": 0.05,
        "exclude_hit_min": 0.95,
        "exclude_clear_max": 0.2,
    },
}
PAPER = {
    "id": "MED:1",
    "title": "Paper 1 title",
    "abstract": "We trained a network.",
    "sources": ["europepmc"],
}


def test_one_noul_question_per_criterion():
    questions = criteria_questions(DOMAIN)
    assert list(questions) == ["i1", "e1"]
    assert questions["e1"]["type"] == "noul"
    assert "Is this true of the paper? The paper is a review." in questions["e1"]["instructions"]
    assert "deep learning CT-FFR" in questions["i1"]["instructions"]
    assert set(questions["i1"]["criteria"]) == {"true", "false"}


def test_screen_criteria_decides_names_the_criterion_and_caches(tmp_path):
    store = Store(tmp_path)
    client = jev_criteria_client(lambda _i, key: {"i1": 0.9, "e1": 0.97}[key])
    jev = JevScreener(store, "k", client=client)
    verdict = jev.screen_criteria(PAPER, DOMAIN)
    assert verdict["decision"] == "exclude" and verdict["decided_by"] == "e1"
    assert verdict["probabilities"] == {"i1": 0.9, "e1": 0.97}
    assert verdict["model_version"] == "jev-1.13.0" and verdict["thresholds"] == DOMAIN["thresholds"]
    assert verdict["cached"] is False and client.calls == [(1, ["e1", "i1"])]
    again = jev.screen_criteria(PAPER, DOMAIN)
    assert again["cached"] is True and len(client.calls) == 1
    assert jev.cached_criteria_probabilities(PAPER, DOMAIN) == ({"i1": 0.9, "e1": 0.97}, "jev-1.13.0")


def test_state_is_evidence_only(tmp_path):
    bodies = []

    def handler(request):
        bodies.append(json.loads(request.content))
        answers = {k: {"type": "noul", "noul": 0.5} for k in bodies[-1]["questions"]}
        return httpx.Response(200, json={"model": "m", "answers": answers})

    JevScreener(
        Store(tmp_path), "k", client=httpx.Client(transport=httpx.MockTransport(handler))
    ).screen_criteria(PAPER, DOMAIN)
    assert bodies[0]["state"] == {"title": PAPER["title"], "abstract": PAPER["abstract"]}


def test_missing_answer_for_a_criterion_fails_closed(tmp_path):
    def handler(request):
        return httpx.Response(200, json={"model": "m", "answers": {"i1": {"type": "noul", "noul": 0.9}}})

    jev = JevScreener(Store(tmp_path), "k", client=httpx.Client(transport=httpx.MockTransport(handler)))
    with pytest.raises(JevError):
        jev.screen_criteria(PAPER, DOMAIN)


def test_offline_lookup_raises_on_a_miss(tmp_path):
    with pytest.raises(MissingCall):
        JevScreener(Store(tmp_path), "offline").cached_criteria_probabilities(PAPER, DOMAIN)
