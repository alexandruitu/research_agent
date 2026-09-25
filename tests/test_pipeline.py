import json

import httpx
import pytest
from langgraph.checkpoint.sqlite import SqliteSaver
from pydantic import ValidationError

from research_agent.agents import Evaluator, validate_evidence
from research_agent.connectors import DemoConnector, EuropePMC, deduplicate
from research_agent.graph import build_graph, disagreement, score
from research_agent.report import write_report
from research_agent.schemas import Claim, Contract, Evidence, Review
from research_agent.storage import Store

CONFIG = {"configurable": {"thread_id": "test"}}


def setup(tmp_path):
    store = Store(tmp_path)
    return store, DemoConnector(store), Evaluator(store)


def test_end_to_end_with_independent_reviews_and_top10(tmp_path):
    store, connector, evaluator = setup(tmp_path)
    result = build_graph(connector, evaluator).invoke(
        {"contract": Contract(topic="retrieval augmented generation").model_dump()}
    )
    assert len(result["ranking"]) == 10
    assert len(result["decisions"]) == 12
    assert all(d["adjudicated"] for d in result["decisions"].values())
    assert result["reviews_a"]["demo:1"]["methods"] == 2
    assert result["reviews_b"]["demo:1"]["methods"] == 0
    with store.connect() as db:
        inputs = db.execute("SELECT role,input FROM calls WHERE role IN ('review_a','review_b')").fetchall()
    assert len(inputs) == 24
    for role, payload in inputs:
        assert "reviews" not in json.loads(payload)["payload"]
        assert "review_a" not in json.loads(payload)["payload"]
    write_report(result, tmp_path, {"models": {"all": "synthetic-demo-v1"}})
    assert "synthetic" in (tmp_path / "report.md").read_text()
    assert json.loads((tmp_path / "report.json").read_text())["state"]["ranking"] == result["ranking"]


def test_checkpoint_resume_without_repeating_discovery(tmp_path):
    _store, connector, evaluator = setup(tmp_path)
    with SqliteSaver.from_conn_string(str(tmp_path / "checkpoint.sqlite")) as saver:
        graph = build_graph(connector, evaluator, saver, ["extract"])
        graph.invoke({"contract": Contract(topic="test topic", max_papers=2).model_dump()}, CONFIG)
        assert set(graph.get_state(CONFIG).next) == {"review_a", "review_b"}

    class NoSearch:
        def search(self, *args):
            raise AssertionError("Discovery must not run again")

    with SqliteSaver.from_conn_string(str(tmp_path / "checkpoint.sqlite")) as saver:
        graph = build_graph(NoSearch(), evaluator, saver)
        result = graph.invoke(None, CONFIG)
        assert len(result["ranking"]) == 2
        assert not graph.get_state(CONFIG).next


def test_resume_after_reviewer_failure_keeps_successful_branch(tmp_path):
    store, connector, _evaluator = setup(tmp_path)

    class FailB(Evaluator):
        def ask(self, role, schema, payload):
            if role == "review_b":
                raise RuntimeError("temporary provider failure")
            return super().ask(role, schema, payload)

    with SqliteSaver.from_conn_string(str(tmp_path / "checkpoint.sqlite")) as saver:
        graph = build_graph(connector, FailB(store), saver)
        with pytest.raises(RuntimeError, match="temporary"):
            graph.invoke({"contract": Contract(topic="test topic", max_papers=1).model_dump()}, CONFIG)

    class Resume(Evaluator):
        def ask(self, role, schema, payload):
            if role in ("plan", "screen", "extract", "review_a"):
                raise AssertionError(f"Successful node repeated: {role}")
            return super().ask(role, schema, payload)

    with SqliteSaver.from_conn_string(str(tmp_path / "checkpoint.sqlite")) as saver:
        result = build_graph(connector, Resume(store), saver).invoke(None, CONFIG)
    assert len(result["ranking"]) == 1


def test_dedup_doi_title_and_provenance(tmp_path):
    _, connector, _ = setup(tmp_path)
    p = connector.search("query one", 1)[0]
    p.doi = "https://doi.org/10.1000/TEST"
    q = p.model_copy(deep=True)
    q.id = "other:1"
    q.doi = "10.1000/test"
    q.provenance[0].query = "query two"
    merged = deduplicate([p, q])
    assert len(merged) == 1
    assert merged[0].doi == "10.1000/test"
    assert len(merged[0].provenance) == 2
    q.doi = "10.1000/different"
    assert len(deduplicate([p, q])) == 2


def test_invalid_quote_and_schema_fail_closed():
    evidence = Evidence(
        claims=[Claim(statement="invented", quote="This text is fabricated")],
        study_design="unknown",
        limitations=["unknown"],
    )
    with pytest.raises(ValueError, match="exact span"):
        validate_evidence(evidence, "Original retrieved abstract")
    with pytest.raises(ValidationError):
        Review(
            verdict="include",
            relevance=5,
            methods=1,
            support=1,
            strengths=["s"],
            weaknesses=["w"],
            assessment="a",
            takeaways=["t"],
        )


def test_scoring_and_disagreement():
    a = {"verdict": "include", "relevance": 4, "methods": 4, "support": 4}
    assert score(a) == 100
    b = dict(a, methods=3)
    assert not disagreement(a, b)
    assert disagreement(a, dict(a, methods=2))
    assert disagreement(a, dict(a, verdict="uncertain"))


def test_missing_abstract_empty_search_and_uncertain_unranked(tmp_path):
    _store, connector, evaluator = setup(tmp_path)

    class Empty:
        def search(self, *args):
            return []

    assert (
        build_graph(Empty(), evaluator).invoke({"contract": Contract(topic="test topic").model_dump()})[
            "ranking"
        ]
        == []
    )

    class Missing:
        def search(self, *args):
            p = connector.search("test", 1)[0]
            p.abstract = ""
            return [p]

    result = build_graph(Missing(), evaluator).invoke({"contract": Contract(topic="test topic").model_dump()})
    assert result["ranking"] == []
    assert result["screens"]["demo:1"]["decision"] == "uncertain"


def test_europe_pmc_parsing_and_raw_provenance(tmp_path):
    store = Store(tmp_path)

    def response(request):
        assert request.url.params["resultType"] == "core"
        assert request.url.params["pageSize"] == "2"
        return httpx.Response(
            200,
            json={
                "resultList": {
                    "result": [
                        {
                            "source": "MED",
                            "id": "123",
                            "title": "A &amp; B",
                            "pubYear": "2025",
                            "doi": "10.1000/ABC",
                            "abstractText": "<p>Example abstract text.</p>",
                        }
                    ]
                }
            },
        )

    with httpx.Client(transport=httpx.MockTransport(response)) as client:
        papers = EuropePMC(store, client).search("test", 2)
    assert papers[0].title == "A & B"
    assert papers[0].doi == "10.1000/abc"
    with store.connect() as db:
        row = db.execute(
            "SELECT payload FROM raw WHERE hash=?", (papers[0].provenance[0].raw_sha256,)
        ).fetchone()
    assert json.loads(row[0])["resultList"]["result"][0]["id"] == "123"


def test_source_failure_is_not_reported_as_empty(tmp_path):
    with (
        httpx.Client(transport=httpx.MockTransport(lambda req: httpx.Response(400))) as client,
        pytest.raises(httpx.HTTPStatusError),
    ):
        EuropePMC(Store(tmp_path), client).search("bad", 2)


def test_dedup_missing_doi_cannot_bridge_conflicting_dois(tmp_path):
    _, connector, _ = setup(tmp_path)
    a = connector.search("test", 1)[0]
    a.doi = "10.1000/a"
    b = a.model_copy(update={"id": "other:2", "doi": "10.1000/b"})
    c = a.model_copy(update={"id": "other:3", "doi": ""})
    assert len(deduplicate([c, a, b])) == 3
    assert len(deduplicate([a, b, c])) == 3


def test_agreement_and_uncertain_adjudication(tmp_path):
    store, connector, _ = setup(tmp_path)

    class Agree(Evaluator):
        def _demo(self, role, payload):
            if role == "adjudicate":
                raise AssertionError("Agreement must not invoke adjudicator")
            return super()._demo("review_a" if role == "review_b" else role, payload)

    result = build_graph(connector, Agree(store)).invoke(
        {"contract": Contract(topic="agreement", max_papers=1).model_dump()}
    )
    assert not result["decisions"]["demo:1"]["adjudicated"]

    class Uncertain(Evaluator):
        def _demo(self, role, payload):
            result = super()._demo(role, payload)
            if role == "adjudicate":
                result.review.verdict = "uncertain"
            return result

    result = build_graph(connector, Uncertain(Store(tmp_path / "uncertain"))).invoke(
        {"contract": Contract(topic="uncertain", max_papers=1).model_dump()}
    )
    assert result["ranking"] == []
    assert result["decisions"]["demo:1"]["review"]["verdict"] == "uncertain"


def test_live_adapter_structured_output_and_cache(tmp_path, monkeypatch):
    import langchain.chat_models

    from research_agent.schemas import Plan

    calls = []

    class FakeModel:
        def with_structured_output(self, schema, method=None):
            assert schema is Plan and method == "json_schema"
            return self

        def invoke(self, messages):
            calls.append(messages)
            assert messages[0][0] == "system"
            return Plan(queries=["test query"], rationale="adapter test")

    monkeypatch.setattr(langchain.chat_models, "init_chat_model", lambda *args, **kwargs: FakeModel())
    evaluator = Evaluator(Store(tmp_path), "live", {"plan": "test:model"})
    first = evaluator.ask("plan", Plan, {"topic": "test"})
    second = evaluator.ask("plan", Plan, {"topic": "test"})
    assert first == second
    assert len(calls) == 1


def test_quote_matching_tolerates_unicode_whitespace_and_snaps_to_exact_span():
    from research_agent.agents import snap_evidence

    abstract = "Threshold of ≤ 0.80 defined significance. Second  sentence here."
    evidence = Evidence(
        claims=[
            Claim(statement="a", quote="Threshold of ≤ 0.80 defined significance."),
            Claim(statement="b", quote="Second sentence here."),
        ],
        study_design="x",
        limitations=["y"],
    )
    snapped = snap_evidence(evidence, abstract)
    assert snapped.claims[0].quote == "Threshold of ≤ 0.80 defined significance."
    assert snapped.claims[1].quote == "Second  sentence here."
    validate_evidence(snapped, abstract)  # snapped quotes are exact substrings
    bad = Evidence(
        claims=[Claim(statement="c", quote="Invented sentence text")], study_design="x", limitations=["y"]
    )
    with pytest.raises(ValueError, match="exact span"):
        snap_evidence(bad, abstract)


def _live_evaluator(tmp_path, monkeypatch, model):
    import langchain.chat_models

    monkeypatch.setattr(langchain.chat_models, "init_chat_model", lambda *a, **k: model)
    return Evaluator(Store(tmp_path), "live", {"plan": "test:model"})


def _validation_error():
    from research_agent.schemas import Plan

    try:
        Plan.model_validate({"queries": "not a list"})
    except ValidationError as exc:
        return exc


def _parser_exception():
    from langchain_core.exceptions import OutputParserException

    return OutputParserException("Failed to parse Plan from completion (truncated JSON)")


@pytest.mark.parametrize("make_error", [_validation_error, _parser_exception])
def test_live_schema_failure_is_retried_then_fails_closed(tmp_path, monkeypatch, make_error):
    from research_agent.schemas import Plan

    class Flaky:
        def __init__(self, failures):
            self.failures, self.calls = failures, 0

        def with_structured_output(self, schema, method=None):
            assert method == "json_schema"
            return self

        def invoke(self, messages):
            self.calls += 1
            if self.calls <= self.failures:
                raise make_error()
            return Plan(queries=["q"], rationale="ok")

    model = Flaky(2)
    assert _live_evaluator(tmp_path, monkeypatch, model).ask("plan", Plan, {"topic": "t"}).queries == ["q"]
    assert model.calls == 3
    model = Flaky(3)
    with pytest.raises(type(make_error())):
        _live_evaluator(tmp_path / "x", monkeypatch, model).ask("plan", Plan, {"topic": "t"})
    assert model.calls == 3


def test_offline_evaluator_serves_cache_and_raises_on_miss(tmp_path):
    from research_agent.schemas import Screen
    from research_agent.storage import MissingCall

    store = Store(tmp_path)
    payload = {"topic": "t", "paper": {"id": "x"}}
    Evaluator(store).ask("screen", Screen, payload)  # demo call fills the cache
    offline = Evaluator(store, offline=True)
    assert offline.ask("screen", Screen, payload).decision == "include"
    with pytest.raises(MissingCall):
        offline.ask("screen", Screen, {"topic": "other", "paper": {"id": "x"}})


def _snap(abstract, quote):
    from research_agent.agents import snap_evidence

    evidence = Evidence(claims=[Claim(statement="a", quote=quote)], study_design="x", limitations=["y"])
    snapped = snap_evidence(evidence, abstract)
    validate_evidence(snapped, abstract)
    return snapped.claims[0].quote


def test_quote_matching_is_grapheme_aware_for_combining_sequences():
    import unicodedata

    nfc = "Sørensen café method used here today."
    nfd = unicodedata.normalize("NFD", nfc)
    assert nfd != nfc
    # Abstract decomposed, quote precomposed, and the reverse.
    assert _snap(nfd, unicodedata.normalize("NFC", "café method used here")) == (
        unicodedata.normalize("NFD", "café method used here")
    )
    assert _snap(nfc, unicodedata.normalize("NFD", "café method used here")) == "café method used here"


def test_snapped_span_starts_and_ends_on_grapheme_chunk_boundaries():
    import unicodedata

    abstract = unicodedata.normalize("NFD", "Le café est bon.")
    assert (
        _snap(abstract, unicodedata.normalize("NFC", "é est bon.")) == "e\u0301 est bon."
    )  # not a bare mark
    assert (
        _snap(abstract, unicodedata.normalize("NFC", "Le café est")) == "Le cafe\u0301 est"
    )  # keeps the mark


def test_quote_matching_ignores_format_characters():
    assert _snap("Deep vessel\u00adsegmentation works.", "vesselsegmentation works.") == (
        "vessel\u00adsegmentation works."
    )
    assert _snap("A zero\u200bwidth case.", "zerowidth case.") == "zero\u200bwidth case."


def test_quote_matching_handles_ligature_inside_a_quote():
    assert _snap("The \ufb01ne \ufb02ow was measured.", "The fine flow was") == "The \ufb01ne \ufb02ow was"
