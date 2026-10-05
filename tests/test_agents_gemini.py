"""Gemini (google_genai) goes through the same structured-output path as Anthropic. No network."""

import langchain.chat_models
import pytest
from langchain_core.exceptions import OutputParserException

from research_agent.agents import Evaluator
from research_agent.schemas import PanelReview
from research_agent.storage import Store

TEXT = "We trained a CNN on 500 CT scans. External validation used 200 patients."
ITEMS = [{"key": "split", "text": "The split is described."}]


def payload():
    return {
        "topic": "ct",
        "paper": {"id": "MED:1", "title": "T", "abstract": TEXT},
        "text": {"source": "abstract", "content": TEXT},
        "items": ITEMS,
    }


def good():
    return {
        "answers": [{"key": "split", "answer": "yes", "quote": "500 CT scans", "section": "abstract"}],
        "verdict": "include",
        "strengths": ["s"],
        "weaknesses": ["w"],
        "summary": "ok",
    }


class FakeModel:
    def __init__(self, seen, outputs):
        self.seen, self.outputs = seen, outputs

    def with_structured_output(self, schema, method=None):
        self.seen["method"] = method
        return self

    def invoke(self, messages):
        out = self.outputs.pop(0)
        if isinstance(out, Exception):
            raise out
        return out


def test_google_genai_model_uses_json_schema_and_retries(tmp_path, monkeypatch):
    seen, outputs = {}, [OutputParserException("bad json"), good()]

    def fake(model, **kwargs):
        seen["model"], seen["kwargs"] = model, kwargs
        return FakeModel(seen, outputs)

    monkeypatch.setattr(langchain.chat_models, "init_chat_model", fake)
    evaluator = Evaluator(Store(tmp_path), "live", {"review:m": "google_genai:gemini-2.5-flash"})
    result = evaluator.ask("review:m", PanelReview, payload())
    assert result.answers[0].quote == "500 CT scans"
    assert seen["model"] == "google_genai:gemini-2.5-flash" and seen["method"] == "json_schema"
    assert {"timeout", "max_retries", "max_tokens"} <= set(seen["kwargs"]) and outputs == []


def test_gemini_chat_model_builds_a_json_schema_runnable_offline():
    genai = pytest.importorskip("langchain_google_genai")
    llm = genai.ChatGoogleGenerativeAI(
        model="gemini-2.5-flash", google_api_key="test-not-a-key", max_tokens=100, timeout=5, max_retries=1
    )
    assert llm.max_output_tokens == 100
    assert llm.with_structured_output(PanelReview, method="json_schema") is not None
