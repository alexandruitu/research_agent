"""TypeSafe Jev screening tier: a fast, cheap classifier that runs ahead of the LLM screen.

Jev answers yes/no criteria (Noul) as probabilities. Only confident answers are acted on;
everything else escalates to the LLM. Thresholds are asymmetric because a wrongly excluded
paper is lost for good, while a wrongly included one is filtered by later stages.

Raw probabilities are cached in the `calls` table (Raw Layer) *without* the thresholds in the
key, so re-tuning thresholds against a gold set costs no API calls. Jev is not deterministic
across model versions: the version the API reports is stored with every response.
"""

import os
import time
from dataclasses import dataclass
from typing import Literal

import httpx
from pydantic import BaseModel, ValidationError

from .connectors import digest
from .storage import MissingCall

JEV_SCREEN_VERSION = "jev-screen.1"
ENDPOINT = "https://api.typesafe.ai/v1/systemone"
DEFAULT_MODEL = "jev-latest"
RETRYABLE = {429, 500, 502, 503, 504, 529}


class JevError(RuntimeError):
    """Malformed or unusable Jev response. Fail closed: the run stops, the checkpoint stays."""


@dataclass(frozen=True)
class JevThresholds:
    """Noul answers carry no confidence; it is derived as |2p - 1| (0 at p=0.5, 1 at p=0/1).

    min_confidence=0.6 -> auto-include at p >= 0.80.
    exclude_min_confidence=0.9 -> auto-exclude at p <= 0.05.
    """

    min_confidence: float = 0.6
    exclude_min_confidence: float = 0.9

    def __post_init__(self):
        for value in (self.min_confidence, self.exclude_min_confidence):
            if not 0 <= value <= 1:
                raise ValueError("Jev confidence thresholds must be within 0..1")
        if self.exclude_min_confidence < self.min_confidence:
            raise ValueError("exclude_min_confidence must be stricter than (>=) min_confidence: recall first")


def confidence(probability):
    return round(abs(2 * probability - 1), 6)


def decide_from_probabilities(probabilities, thresholds):
    """Any confident 'no' excludes; include only when every criterion is confidently 'yes'."""
    if any(p < 0.5 and confidence(p) >= thresholds.exclude_min_confidence for p in probabilities.values()):
        return "exclude"
    if all(p > 0.5 and confidence(p) >= thresholds.min_confidence for p in probabilities.values()):
        return "include"
    return "escalate"


def default_criteria(topic):
    return {
        "topic_match": {
            "type": "noul",
            "instructions": (
                f"The paper's central subject is the research topic: {topic}. "
                "Judge only from the title and abstract in the state."
            ),
            "criteria": {
                "true": "Methods, data or findings reported in the abstract are about the topic.",
                "false": "The topic is only mentioned in passing, or the work is about something else.",
            },
        }
    }


class _Noul(BaseModel):
    type: Literal["noul"]
    noul: float

    def check(self):
        if not 0 <= self.noul <= 1:
            raise ValueError("noul probability outside 0..1")


class _Response(BaseModel):
    model: str
    answers: dict[str, _Noul]


class JevScreener:
    def __init__(
        self,
        store,
        api_key,
        model=DEFAULT_MODEL,
        thresholds=None,
        criteria=None,
        client=None,
        sleep=time.sleep,
    ):
        self.store = store
        self.api_key = api_key
        self.model = model
        self.thresholds = thresholds or JevThresholds()
        self.criteria = criteria
        self.client = client
        self.sleep = sleep

    @classmethod
    def from_env(cls, store, thresholds=None, **kwargs):
        key = os.getenv("TYPESAFE_API_KEY")
        if not key:
            raise ValueError("Set TYPESAFE_API_KEY in .env to use the Jev screening tier")
        return cls(store, key, thresholds=thresholds, **kwargs)

    def _request(self, topic, paper):
        # Evidence only: never a prior verdict or conclusion.
        state = {"title": paper["title"], "abstract": paper["abstract"]}
        questions = self.criteria or default_criteria(topic)
        inputs = {"model": self.model, "state": state, "questions": questions}
        key = digest({"role": "jev_screen", "version": JEV_SCREEN_VERSION, "inputs": inputs})
        return key, inputs, questions

    def cached_probabilities(self, topic, paper):
        """Raw probabilities and API model version from the cache only; never calls the API."""
        key, _inputs, questions = self._request(topic, paper)
        raw = self.store.cached(key)
        if raw is None:
            raise MissingCall(f"jev_screen call not in cache ({key[:12]})")
        response = self._parse(raw, questions)
        return {q: response.answers[q].noul for q in questions}, response.model

    def screen(self, topic, paper):
        key, inputs, questions = self._request(topic, paper)
        raw = self.store.cached(key)
        cached = raw is not None
        if not cached:
            raw = self._post(inputs)
        response = self._parse(raw, questions)
        if not cached:
            self.store.record(key, "jev_screen", self.model, JEV_SCREEN_VERSION, inputs, raw)
        probabilities = {q: response.answers[q].noul for q in questions}
        return {
            "decision": self.decide(probabilities),
            "probabilities": probabilities,
            "model_version": response.model,
            "min_confidence": self.thresholds.min_confidence,
            "exclude_min_confidence": self.thresholds.exclude_min_confidence,
            "cached": cached,
        }

    def decide(self, probabilities):
        return decide_from_probabilities(probabilities, self.thresholds)

    @staticmethod
    def _parse(raw, questions):
        try:
            response = _Response.model_validate(raw)
            for question in questions:
                response.answers[question].check()
        except (ValidationError, KeyError, ValueError) as exc:
            raise JevError(f"Unexpected Jev response ({type(exc).__name__})") from None
        return response

    def _post(self, body):
        headers = {"Authorization": f"Bearer {self.api_key}"}

        def fetch(client):
            for attempt in range(3):
                try:
                    response = client.post(ENDPOINT, json=body, headers=headers)
                    response.raise_for_status()
                    try:
                        return response.json()
                    except ValueError:
                        raise JevError("Unexpected Jev response (not JSON)") from None
                except (httpx.TransportError, httpx.HTTPStatusError) as exc:
                    retryable = (
                        not isinstance(exc, httpx.HTTPStatusError) or exc.response.status_code in RETRYABLE
                    )
                    if not retryable or attempt == 2:
                        raise
                    self.sleep(2**attempt)

        if self.client is not None:
            return fetch(self.client)
        with httpx.Client(timeout=30) as client:
            return fetch(client)
