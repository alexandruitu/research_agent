import json

import pytest
from eval_helpers import europepmc, jev_criteria_client, row

from research_agent.agents import (
    PROMPT_VERSION,
    CriteriaAnswerError,
    Evaluator,
    EvidenceQuoteError,
    snap_screen,
)
from research_agent.connectors import DemoConnector, EuropePMC
from research_agent.criteria import screen_payload
from research_agent.graph import build_graph
from research_agent.jev import JevScreener
from research_agent.report import write_report
from research_agent.schemas import Contract, CriteriaScreen, CriterionAnswer, DomainSpec, Screen
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


FIELD = DomainSpec.model_validate(
    {
        "schema": 1,
        "field": {"id": "f1", "name": "ML CT-FFR", "version": 2},
        "topic": "deep learning CT-FFR",
        "criteria": {
            "include": [{"key": "i1", "text": "Uses deep learning."}],
            "exclude": [{"key": "e1", "text": "Is a review."}],
        },
        "sources": [{"name": "europepmc"}],
    }
)


class QuotingEvaluator(Evaluator):
    """Demo evaluator whose criteria screen drops MED:6 by e1 and is unsure about MED:7."""

    def _demo(self, role, payload):
        if role == "screen_criteria" and payload["paper"]["id"] == "MED:6":
            return screen(("i1", "yes", ""), ("e1", "yes", "Abstract 6 on the topic."), reason="a review")
        if role == "screen_criteria" and payload["paper"]["id"] == "MED:7":
            return screen(("i1", "unclear", ""), ("e1", "no", ""), reason="unclear")
        return super()._demo(role, payload)


def field_run(tmp_path):
    store = Store(tmp_path)
    rows = [row(i) for i in range(1, 8)] + [row(8, abstract="")]
    probabilities = {
        1: (0.9, 0.1),
        2: (0.01, 0.1),
        3: (0.9, 0.99),
        4: (0.5, 0.5),
        6: (0.5, 0.5),
        7: (0.5, 0.5),
    }
    jev = JevScreener(
        store,
        "k",
        client=jev_criteria_client(lambda i, key: probabilities.get(i, (0.5, 0.5))[0 if key == "i1" else 1]),
    )
    contract = Contract(topic=FIELD.topic, domain=FIELD).model_dump()
    graph = build_graph(EuropePMC(store, europepmc({"*": rows})), QuotingEvaluator(store), jev=jev)
    return graph.invoke({"contract": contract})


def test_field_run_screens_per_criterion_and_names_the_decider(tmp_path):
    screens = field_run(tmp_path)["screens"]
    assert screens["MED:1"]["decision"] == "include" and screens["MED:1"]["tier"] == "jev"
    assert screens["MED:1"]["decided_by"] is None
    assert screens["MED:1"]["criteria"] == {
        "i1": {"jev_p": 0.9, "llm": None, "quote": None},
        "e1": {"jev_p": 0.1, "llm": None, "quote": None},
    }
    assert (screens["MED:2"]["decision"], screens["MED:2"]["decided_by"]) == ("exclude", "i1")
    assert screens["MED:2"]["reason"] == "Jev: i1 p=0.01, e1 p=0.10 (jev-1.13.0); dropped by i1"
    assert (screens["MED:3"]["decision"], screens["MED:3"]["decided_by"]) == ("exclude", "e1")
    assert screens["MED:4"]["tier"] == "llm" and screens["MED:4"]["decision"] == "include"
    assert screens["MED:4"]["jev"]["decision"] == "escalate"
    assert screens["MED:4"]["criteria"]["i1"] == {"jev_p": 0.5, "llm": "yes", "quote": None}
    assert screens["MED:6"]["decision"] == "exclude" and screens["MED:6"]["decided_by"] == "e1"
    assert screens["MED:6"]["criteria"]["e1"] == {
        "jev_p": 0.5,
        "llm": "yes",
        "quote": "Abstract 6 on the topic.",
    }
    assert screens["MED:6"]["reason"] == "a review"
    assert screens["MED:7"]["decision"] == "uncertain" and screens["MED:7"]["decided_by"] is None
    assert screens["MED:8"] == {
        "decision": "uncertain",
        "reason": "No abstract available; retained in audit, unranked.",
        "tier": "rule",
        "decided_by": None,
        "criteria": {k: {"jev_p": None, "llm": None, "quote": None} for k in ("i1", "e1")},
    }


def test_field_run_report_json_is_a_superset_of_todays_shape(tmp_path):
    result = field_run(tmp_path)
    write_report(result, tmp_path, {"models": {"all": "synthetic-demo-v1"}})
    state = json.loads((tmp_path / "report.json").read_text())["state"]
    assert state["contract"]["domain"]["field"] == {"id": "f1", "name": "ML CT-FFR", "version": 2}
    assert state["papers"][0]["sources"] == ["europepmc"]
    for screen_entry in state["screens"].values():
        assert {"decision", "reason", "tier", "decided_by", "criteria"} <= set(screen_entry)
    markdown = (tmp_path / "report.md").read_text()
    assert "Field: ML CT-FFR · version 2" in markdown and "Found by: europepmc" in markdown


def test_legacy_screens_gain_topic_match_cells(tmp_path):
    store = Store(tmp_path)
    contract = Contract(topic="retrieval augmented generation", max_papers=2).model_dump()
    screens = build_graph(DemoConnector(store), Evaluator(store)).invoke({"contract": contract})["screens"]
    assert screens["demo:1"]["criteria"] == {} and screens["demo:1"]["decided_by"] is None


def test_plan_payload_is_unchanged_for_legacy_runs_and_gets_the_criteria_for_fields(tmp_path):
    seen = []

    class Recording(Evaluator):
        def ask(self, role, schema, payload):
            if role == "plan":
                seen.append(payload)
            return super().ask(role, schema, payload)

    store = Store(tmp_path)
    legacy = Contract(topic="retrieval augmented generation", max_papers=1).model_dump()
    build_graph(DemoConnector(store), Recording(store), interrupt_after=["plan"]).invoke({"contract": legacy})
    field = Contract(topic=FIELD.topic, domain=FIELD, max_papers=1).model_dump()
    build_graph(DemoConnector(store), Recording(store), interrupt_after=["plan"]).invoke({"contract": field})
    assert "domain" not in seen[0] and seen[0]["topic"] == "retrieval augmented generation"
    assert seen[1]["criteria"] == FIELD.model_dump()["criteria"] and seen[1]["years"] == {
        "from": None,
        "to": None,
    }
    assert "domain" not in seen[1]
