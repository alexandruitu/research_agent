import pytest

from research_agent.agents import (
    PROMPT_VERSION,
    CriteriaAnswerError,
    Evaluator,
    EvidenceQuoteError,
    snap_screen,
)
from research_agent.criteria import screen_payload
from research_agent.schemas import CriteriaScreen, CriterionAnswer, Screen
from research_agent.storage import Store

ABSTRACT = "We review prior work on CT-FFR. No new patients were enrolled."
CRITERIA = {
    "include": [{"key": "i1", "text": "Reports original results."}],
    "exclude": [{"key": "e1", "text": "The paper is a review."}],
}
DOMAIN = {"topic": "CT-FFR", "criteria": CRITERIA}
PAPER = {"id": "MED:1", "title": "t", "abstract": ABSTRACT, "sources": ["europepmc"]}


def screen(*answers, reason="r"):
    return CriteriaScreen(
        answers=[CriterionAnswer(key=k, answer=a, quote=q) for k, a, q in answers], reason=reason
    )


def test_prompt_version_is_bumped():
    assert PROMPT_VERSION == "m1.2"


def test_quotes_snap_to_the_abstract_and_answers_follow_the_field_order():
    result = snap_screen(
        screen(
            ("e1", "yes", "We review prior work on CT-FFR."), ("i1", "no", "No new patients were enrolled.")
        ),
        CRITERIA,
        ABSTRACT,
    )
    assert [a.key for a in result.answers] == ["i1", "e1"]
    assert result.answers[1].quote == "We review prior work on CT-FFR."  # the abstract's own text
    assert all(a.quote in ABSTRACT for a in result.answers)


@pytest.mark.parametrize(
    "answers,error",
    [
        ((("i1", "yes", ""),), CriteriaAnswerError),  # e1 missing
        ((("i1", "yes", ""), ("e1", "no", ""), ("e2", "no", "")), CriteriaAnswerError),  # unknown key
        ((("i1", "yes", ""), ("i1", "yes", ""), ("e1", "no", "")), CriteriaAnswerError),  # duplicate
        ((("i1", "no", ""), ("e1", "no", "")), CriteriaAnswerError),  # 'no' on inclusion needs a quote
        ((("i1", "yes", ""), ("e1", "yes", " ")), CriteriaAnswerError),  # 'yes' on exclusion needs a quote
        ((("i1", "yes", ""), ("e1", "yes", "We summarise prior work.")), EvidenceQuoteError),  # mangled
        (
            (("i1", "yes", "Invented."), ("e1", "no", "")),
            EvidenceQuoteError,
        ),  # optional quotes are checked too
    ],
)
def test_bad_answers_are_refused(answers, error):
    with pytest.raises(error):
        snap_screen(screen(*answers), CRITERIA, ABSTRACT)


def test_demo_screen_answers_every_criterion_and_is_cached_under_the_new_role(tmp_path):
    store = Store(tmp_path)
    result = Evaluator(store).ask("screen_criteria", CriteriaScreen, screen_payload(DOMAIN, PAPER))
    assert [(a.key, a.answer, a.quote) for a in result.answers] == [("i1", "yes", ""), ("e1", "no", "")]
    with store.connect() as db:
        role, version, raw = db.execute("SELECT role, prompt_version, input FROM calls").fetchone()
    assert (role, version) == ("screen_criteria", "m1.2") and "sources" not in raw


def test_paper_sources_never_reach_a_model_or_a_cache_key(tmp_path):
    store = Store(tmp_path)
    first = Evaluator(store).ask("screen", Screen, {"topic": "t", "paper": PAPER})
    without = {k: v for k, v in PAPER.items() if k != "sources"}
    offline = Evaluator(store, offline=True)
    assert offline.ask("screen", Screen, {"topic": "t", "paper": without}) == first


def test_prompt_version_can_be_pinned_to_read_an_old_cache(tmp_path):
    store = Store(tmp_path)
    Evaluator(store, prompt_version="m1.1").ask("screen", Screen, {"topic": "t", "paper": PAPER})
    with store.connect() as db:
        assert db.execute("SELECT prompt_version FROM calls").fetchone()[0] == "m1.1"
    Evaluator(store, prompt_version="m1.1", offline=True).ask(
        "screen", Screen, {"topic": "t", "paper": PAPER}
    )


def test_screen_criteria_falls_back_to_the_screen_model():
    assert Evaluator(None, "live", {"screen": "anthropic:x"}).model_for("screen_criteria") == "anthropic:x"
    both = {"screen": "anthropic:x", "screen_criteria": "openai:y"}
    assert Evaluator(None, "live", both).model_for("screen_criteria") == "openai:y"


def test_live_screen_retries_a_mangled_quote_then_fails_closed(tmp_path, monkeypatch):
    import langchain.chat_models

    bad = screen(("i1", "yes", ""), ("e1", "yes", "We summarise prior work."))
    good = screen(("i1", "yes", ""), ("e1", "yes", "We review prior work on CT-FFR."))

    class Flaky:
        def __init__(self, outputs):
            self.outputs, self.calls = outputs, 0

        def with_structured_output(self, schema, method=None):
            return self

        def invoke(self, messages):
            self.calls += 1
            return self.outputs[min(self.calls, len(self.outputs)) - 1]

    def evaluator(directory, model):
        monkeypatch.setattr(langchain.chat_models, "init_chat_model", lambda *a, **k: model)
        return Evaluator(Store(directory), "live", {"screen": "test:model"})

    model = Flaky([bad, good])
    result = evaluator(tmp_path, model).ask("screen_criteria", CriteriaScreen, screen_payload(DOMAIN, PAPER))
    assert model.calls == 2 and result.answers[1].quote in ABSTRACT
    always_bad = Flaky([bad])
    with pytest.raises(EvidenceQuoteError):
        evaluator(tmp_path / "x", always_bad).ask(
            "screen_criteria", CriteriaScreen, screen_payload(DOMAIN, PAPER)
        )
    assert always_bad.calls == 3
