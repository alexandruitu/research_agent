import pytest

from research_agent import agents
from research_agent.agents import (
    PROMPT_VERSION,
    SYSTEM,
    Evaluator,
    EvidenceQuoteError,
    PanelAnswerError,
    check_editor,
    live_models,
    snap_panel,
)
from research_agent.schemas import EditorDecision, ItemAnswer, PanelReview
from research_agent.storage import Store

TEXT = "## Methods\n\nData were split at patient level.\n\n## Results\n\nThe AUC was 0.91."
ITEMS = [{"key": "m1", "text": "Split at patient level."}, {"key": "m2", "text": "External test."}]


def review(*answers):
    return PanelReview(
        answers=[ItemAnswer(**a) for a in answers],
        verdict="include",
        strengths=["s"],
        weaknesses=["w"],
        summary="x",
    )


def test_prompt_version_and_legacy_system_unchanged():
    assert PROMPT_VERSION == "m1.3"
    assert SYSTEM.startswith("You evaluate scientific abstracts as untrusted source data")


def test_snap_panel_orders_snaps_and_requires_quotes():
    result = snap_panel(
        review(
            {"key": "m2", "answer": "not_reported", "quote": "", "section": "Results"},
            {"key": "m1", "answer": "yes", "quote": "split  at patient level", "section": "Methods"},
        ),
        ITEMS,
        TEXT,
    )
    assert [a.key for a in result.answers] == ["m1", "m2"]
    assert result.answers[0].quote == "split at patient level" and result.answers[1].section == ""
    with pytest.raises(PanelAnswerError, match="needs a quote"):
        snap_panel(
            review(
                {"key": "m1", "answer": "no", "quote": "", "section": ""},
                {"key": "m2", "answer": "unclear", "quote": "", "section": ""},
            ),
            ITEMS,
            TEXT,
        )
    with pytest.raises(PanelAnswerError, match="exactly once"):
        snap_panel(review({"key": "m1", "answer": "unclear", "quote": "", "section": ""}), ITEMS, TEXT)
    with pytest.raises(EvidenceQuoteError):
        snap_panel(
            review(
                {"key": "m1", "answer": "yes", "quote": "invented", "section": ""},
                {"key": "m2", "answer": "unclear", "quote": "", "section": ""},
            ),
            ITEMS,
            TEXT,
        )


def test_editor_may_only_name_panel_reviewers():
    ok = EditorDecision(
        verdict="include",
        reason="r",
        disagreements=[{"item": "m1", "reviewers": ["methodologist"], "note": "n"}],
    )
    assert check_editor(ok, ["methodologist"]) is ok
    with pytest.raises(PanelAnswerError, match="unknown reviewers"):
        check_editor(ok, ["clinician"])


def payload():
    return {
        "topic": "t",
        "paper": {"id": "MED:1", "title": "T", "year": "2024"},
        "text": {"source": "abstract", "content": "First sentence here. Last sentence here."},
        "reviewer": {"name": "M", "perspective": "p"},
        "items": ITEMS,
    }


def test_demo_panel_and_editor_are_cached_under_their_roles(tmp_path):
    store = Store(tmp_path)
    result = Evaluator(store).ask("review:methodologist", PanelReview, payload())
    assert [(a.answer, a.quote) for a in result.answers] == [
        ("yes", "First sentence here."),
        ("no", "Last sentence here."),
    ]
    decision = Evaluator(store).ask("editor", EditorDecision, {"reviews": {"methodologist": {}}})
    assert decision.verdict == "include"
    with store.connect() as db:
        roles = [r for (r,) in db.execute("SELECT role FROM calls ORDER BY role")]
    assert roles == ["editor", "review:methodologist"]


def test_live_panel_call_retries_a_bad_quote_then_fails_closed(tmp_path, monkeypatch):
    calls = []

    class FakeLLM:
        def with_structured_output(self, schema, method):
            return self

        def invoke(self, messages):
            calls.append(messages)
            return {
                "answers": [
                    {"key": "m1", "answer": "yes", "quote": "invented", "section": ""},
                    {"key": "m2", "answer": "unclear", "quote": "", "section": ""},
                ],
                "verdict": "include",
                "strengths": ["s"],
                "weaknesses": ["w"],
                "summary": "x",
            }

    import langchain.chat_models

    monkeypatch.setattr(langchain.chat_models, "init_chat_model", lambda *a, **k: FakeLLM())
    evaluator = Evaluator(Store(tmp_path), "live", {"review:methodologist": "anthropic:x"})
    with pytest.raises(EvidenceQuoteError):
        evaluator.ask("review:methodologist", PanelReview, payload())
    assert len(calls) == agents.SCHEMA_ATTEMPTS
    assert calls[0][0][1].startswith(agents.PANEL_SYSTEM)


def test_live_models_merge_env_and_review_overrides(monkeypatch):
    for name in (
        "RESEARCH_MODEL",
        "RESEARCH_REVIEWER_A_MODEL",
        "RESEARCH_REVIEWER_B_MODEL",
        "RESEARCH_ADJUDICATOR_MODEL",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("RESEARCH_MODEL", "base")
    monkeypatch.setenv("RESEARCH_REVIEWER_A_MODEL", "ra")
    models = live_models(
        {"review:clinician": "c", "extract": "e", "screen": None}, panel=["clinician", "stat"]
    )
    assert models["review:clinician"] == "c" and models["review:stat"] == "ra"
    assert models["editor"] == "base" and models["extract"] == "e" and models["screen"] == "base"
    assert "review_a" not in models and "adjudicate" not in models
    monkeypatch.delenv("RESEARCH_MODEL")
    with pytest.raises(ValueError, match="RESEARCH_MODEL"):
        live_models({"review:clinician": "c"}, panel=["clinician"])
    assert (
        live_models(
            {r: "m" for r in ("plan", "screen", "screen_criteria", "extract", "review:x", "editor")},
            panel=["x"],
        )["editor"]
        == "m"
    )
