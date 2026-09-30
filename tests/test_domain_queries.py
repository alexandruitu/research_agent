"""DomainSpec's optional description/keywords/queries: additive, and a field run with built queries skips the
planning call for the sources that have one."""

import json
import sqlite3

import httpx
import pytest

from research_agent.runner import run_research
from research_agent.schemas import Contract, DomainSpec
from research_agent.storage import Store
from research_agent.web import checks

BASE = {
    "schema": 1,
    "field": {"id": "f1", "name": "CT-FFR", "version": 1},
    "topic": "deep learning CT-FFR",
    "criteria": {"include": [{"key": "i1", "text": "Uses deep learning."}], "exclude": []},
    "sources": [{"name": "europepmc", "max_results": 4}, {"name": "arxiv", "max_results": 4}],
    "years": {"from": None, "to": None},
}
KEYWORDS = {"all": ["CT-FFR"], "any": ["deep learning", "CNN"], "none": ["review"]}


def roles(run):
    with sqlite3.connect(run / "research.sqlite") as db:
        return [r for (r,) in db.execute("select role from calls")]


def test_old_domains_validate_and_dump_without_the_new_keys():
    spec = DomainSpec.model_validate(BASE)
    dumped = spec.model_dump(mode="json")
    assert not {"description", "keywords", "queries"} & set(dumped)
    assert dumped == DomainSpec.model_validate(dumped).model_dump(mode="json")


def test_new_keys_round_trip():
    data = BASE | {"description": "FFR from CT", "keywords": KEYWORDS, "queries": {"arxiv": "abs:x"}}
    dumped = DomainSpec.model_validate(data).model_dump(mode="json")
    assert dumped["keywords"] == KEYWORDS and dumped["queries"] == {"arxiv": "abs:x"}
    assert dumped["description"] == "FFR from CT"


@pytest.mark.parametrize(
    "extra",
    [
        {"queries": {"openalex": "x"}},  # not a source of this field
        {"queries": {"pubmed": "x"}},
        {"queries": {"arxiv": ""}},
        {"keywords": {"all": ["x" * 81]}},
        {"keywords": {"all": ["x"] * 21}},
        {"description": "x" * 2001},
    ],
)
def test_invalid_additions(extra):
    with pytest.raises(ValueError):
        DomainSpec.model_validate(BASE | extra)


def test_every_source_with_a_query_means_no_planning_call(tmp_path):
    queries = {"europepmc": "TITLE_ABS:CT", "arxiv": "abs:CT AND (cat:cs.CV)"}
    spec = DomainSpec.model_validate(BASE | {"keywords": KEYWORDS, "queries": queries})
    run = tmp_path / "run"
    result = run_research(run, Contract(topic=spec.topic, domain=spec, max_papers=3))
    assert "plan" not in roles(run)
    assert result["plan"]["queries"] == [] and result["plan"]["source_queries"] == queries
    used = {s["query"] for p in result["discovered"] for s in p["provenance"]}
    assert used == set(queries.values())
    assert "(from keywords): TITLE_ABS:CT" in (run / "report.md").read_text()
    domain = json.loads((run / "domain.json").read_text())
    assert domain["queries"] == queries and domain["keywords"] == KEYWORDS


def test_a_source_without_a_query_is_still_planned(tmp_path):
    spec = DomainSpec.model_validate(BASE | {"queries": {"arxiv": "abs:CT"}})
    run = tmp_path / "run"
    result = run_research(run, Contract(topic=spec.topic, domain=spec, max_papers=3))
    assert roles(run).count("plan") == 1
    by_source = {}
    for paper in result["discovered"]:
        for source in paper["sources"]:
            by_source.setdefault(source, set()).update(s["query"] for s in paper["provenance"])
    assert by_source == {"arxiv": {"abs:CT"}, "europepmc": {spec.topic}}


def test_criteria_test_searches_with_the_built_queries(tmp_path, monkeypatch):
    monkeypatch.setattr("research_agent.connectors.time.sleep", lambda _s: None)
    sent = []

    def handler(request):
        sent.append(dict(request.url.params))
        if "arxiv" in request.url.host:
            return httpx.Response(200, text='<feed xmlns="http://www.w3.org/2005/Atom"></feed>')
        return httpx.Response(200, json={"hitCount": 0, "resultList": {"result": []}})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    domain = BASE | {"queries": {"europepmc": "TITLE_ABS:CT"}}
    checks.criteria_test(domain, Store(tmp_path), mode="live", api_key="k", http_client=client)
    assert sent[0]["query"] == "TITLE_ABS:CT"
    assert sent[1]["search_query"].startswith("all:deep AND all:learning")  # no query: the topic, as before
