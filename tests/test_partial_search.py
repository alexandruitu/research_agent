"""Partial search: an optional source that fails is skipped with a recorded warning (no network)."""

import json

import httpx
import pytest

from research_agent import runner
from research_agent.connectors import (
    AllSourcesFailed,
    DemoConnector,
    MultiSource,
    SourceKeyMissing,
    SourceUnavailable,
    failure_reason,
)
from research_agent.runner import run_research
from research_agent.schemas import Contract, DomainSpec, SourceSpec
from research_agent.storage import Store

DOMAIN = {
    "schema": 1,
    "topic": "deep learning CT-FFR",
    "criteria": {
        "include": [{"key": "i1", "text": "Uses deep learning."}],
        "exclude": [{"key": "e1", "text": "Is a review."}],
    },
    "sources": [
        {"name": "europepmc", "max_results": 5},
        {"name": "semantic_scholar", "max_results": 5},
    ],
}


class Down:
    def __init__(self, name, exc=None):
        self.name = name
        self.exc = exc or SourceUnavailable(name, reason="rate limited (HTTP 429)")

    def search(self, query, limit, raw=False):
        raise self.exc


def demo(store, name):
    return DemoConnector(store, source=name)


def test_source_spec_required_defaults_off_and_is_left_out_of_dumps():
    assert SourceSpec(name="europepmc").required is False
    assert "required" not in SourceSpec(name="europepmc").model_dump()
    assert SourceSpec(name="europepmc", required=True).model_dump()["required"] is True
    assert DomainSpec.model_validate(DOMAIN).sources[0].required is False


def test_a_failing_optional_source_is_skipped_with_a_warning(tmp_path):
    store = Store(tmp_path)
    multi = MultiSource([(demo(store, "europepmc"), 3), (Down("semantic_scholar"), 3)])
    multi.begin()
    papers = multi.search("q", 3) + multi.search("q2", 3)
    assert papers and all(p.sources == ["europepmc"] for p in papers)
    search = multi.check()
    assert search["sources_used"] == ["europepmc"] and search["sources_skipped"] == ["semantic_scholar"]
    (warning,) = search["search_warnings"]
    assert warning["source"] == "semantic_scholar" and warning["error_type"] == "SourceUnavailable"
    assert warning["reason"] == "rate limited (HTTP 429)" and "S2_API_KEY" in warning["detail"]


def test_a_missing_key_names_the_variable(tmp_path):
    missing = Down("core", SourceKeyMissing("core", "CORE_API_KEY"))
    multi = MultiSource([(missing, 3), (demo(Store(tmp_path), "europepmc"), 3)], raw={"core": "q"})
    multi.search_raw()
    (warning,) = multi.check()["search_warnings"]
    assert warning["error_type"] == "SourceKeyMissing" and warning["reason"] == "API key missing"
    assert "CORE_API_KEY" in warning["detail"]


def test_a_required_source_failing_stops_the_search():
    multi = MultiSource([(Down("europepmc"), 3), (Down("arxiv"), 3)], required=["europepmc"])
    with pytest.raises(SourceUnavailable) as caught:
        multi.search("q", 3)
    assert caught.value.source == "europepmc"


def test_every_source_failing_stops_the_search_naming_them():
    multi = MultiSource([(Down("europepmc"), 3), (Down("arxiv"), 3)])
    multi.search("q", 3)
    with pytest.raises(AllSourcesFailed) as caught:
        multi.check()
    assert caught.value.message == (
        "No search source answered: europepmc (rate limited (HTTP 429)); arxiv (rate limited (HTTP 429))"
    )


def test_a_single_source_failing_raises_its_own_exception():
    multi = MultiSource([(Down("europepmc"), 3)])
    multi.search("q", 3)
    with pytest.raises(SourceUnavailable) as caught:
        multi.check()
    assert type(caught.value) is SourceUnavailable and caught.value.source == "europepmc"


@pytest.mark.parametrize(
    "exc,reason",
    [
        (
            httpx.HTTPStatusError("", request=httpx.Request("GET", "http://x"), response=httpx.Response(429)),
            "rate limited (HTTP 429)",
        ),
        (
            httpx.HTTPStatusError("", request=httpx.Request("GET", "http://x"), response=httpx.Response(503)),
            "server error (HTTP 503)",
        ),
        (
            httpx.HTTPStatusError("", request=httpx.Request("GET", "http://x"), response=httpx.Response(403)),
            "request refused (HTTP 403)",
        ),
        (httpx.ReadTimeout("t"), "timed out"),
        (httpx.ConnectError("c"), "network error"),
        (ValueError("bad json"), "unreadable response"),
    ],
)
def test_failure_reasons_are_short_and_safe(exc, reason):
    assert failure_reason(exc) == reason


def test_a_field_run_with_a_skipped_source_completes_and_records_the_warning(tmp_path, monkeypatch):
    spec = DomainSpec.model_validate(DOMAIN)

    def connector(contract, store):
        return MultiSource([(demo(store, "europepmc"), 5), (Down("semantic_scholar"), 5)])

    monkeypatch.setattr(runner, "make_connector", connector)
    run = tmp_path / "run"
    result = run_research(run, Contract(topic=spec.topic, domain=spec, max_papers=2))
    assert result["sources_skipped"] == ["semantic_scholar"] and result["sources_used"] == ["europepmc"]
    progress = json.loads((run / "progress.json").read_text())
    assert progress["status"] == "completed" and progress["stages"]["discover"] == "completed"
    assert progress["search_warnings"][0]["source"] == "semantic_scholar"
    report = json.loads((run / "report.json").read_text())
    assert report["state"]["search_warnings"] == progress["search_warnings"]
    assert report["manifest"]["search"]["sources_skipped"] == ["semantic_scholar"]
    assert "Partial search" in (run / "report.md").read_text()


def test_a_field_run_where_every_source_fails_records_why(tmp_path, monkeypatch):
    spec = DomainSpec.model_validate(DOMAIN)
    monkeypatch.setattr(
        runner,
        "make_connector",
        lambda c, s: MultiSource([(Down("europepmc"), 5), (Down("semantic_scholar"), 5)]),
    )
    with pytest.raises(AllSourcesFailed):
        run_research(tmp_path / "run", Contract(topic=spec.topic, domain=spec))
    progress = json.loads((tmp_path / "run" / "progress.json").read_text())
    assert progress["status"] == "failed" and progress["message"].startswith("No search source answered")
    assert [w["source"] for w in progress["search_warnings"]] == ["europepmc", "semantic_scholar"]


def test_a_legacy_run_has_no_search_record(tmp_path):
    result = run_research(tmp_path / "run", Contract(topic="retrieval augmented generation", max_papers=1))
    assert "search_warnings" not in result
