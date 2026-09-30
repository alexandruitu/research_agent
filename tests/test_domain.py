import json

import pytest
from pydantic import ValidationError

from research_agent.schemas import Contract, DomainError, DomainSpec, Paper, read_domain


def domain(**overrides):
    data = {
        "schema": 1,
        "field": {"id": "f-1", "name": "ML CT-FFR", "version": 3},
        "topic": "machine learning or deep learning estimation of CT-derived fractional flow reserve",
        "criteria": {
            "include": [{"key": "i1", "text": "The study uses machine learning or deep learning."}],
            "exclude": [
                {
                    "key": "e1",
                    "text": "The paper is a review, editorial or commentary without original results.",
                }
            ],
        },
        "sources": [
            {"name": "europepmc", "max_results": 100},
            {"name": "openalex", "max_results": 100, "contact": "research-team@example.org"},
        ],
        "years": {"from": 2018, "to": None},
        "thresholds": {
            "keep_min": 0.8,
            "include_fail_max": 0.05,
            "exclude_hit_min": 0.95,
            "exclude_clear_max": 0.2,
        },
    }
    data.update(overrides)
    return data


def test_the_spec_example_validates_and_dumps_with_its_own_key_names():
    spec = DomainSpec.model_validate(domain())
    assert spec.years.start == 2018 and spec.years.end is None
    assert spec.field.version == 3 and spec.sources[1].contact == "research-team@example.org"
    dumped = spec.model_dump()
    assert dumped["schema"] == 1 and dumped["years"] == {"from": 2018, "to": None}
    assert DomainSpec.model_validate(dumped) == spec


def test_minimal_domain_uses_default_years_and_thresholds():
    data = domain()
    for key in ("field", "years", "thresholds"):
        del data[key]
    spec = DomainSpec.model_validate(data)
    assert spec.field is None and spec.years.start is None and spec.years.end is None
    assert spec.thresholds.model_dump() == {
        "keep_min": 0.8,
        "include_fail_max": 0.05,
        "exclude_hit_min": 0.95,
        "exclude_clear_max": 0.2,
    }


def many(prefix, n):
    return [{"key": f"{prefix}{i}", "text": f"Criterion number {i}."} for i in range(1, n + 1)]


@pytest.mark.parametrize(
    "overrides",
    [
        {"extra": 1},
        {"schema": 2},
        {"topic": "x"},
        {"sources": []},
        {"sources": [{"name": "semanticscholar"}]},
        {"sources": [{"name": "arxiv"}, {"name": "arxiv"}]},
        {"sources": [{"name": "arxiv", "max_results": 0}]},
        {"sources": [{"name": "arxiv", "max_results": 201}]},
        {"sources": [{"name": "openalex", "contact": "not-an-email"}]},
        {"sources": [{"name": "arxiv", "api_key": "x"}]},
        {"criteria": {"include": [], "exclude": []}},
        {"criteria": {"include": [{"key": "i1", "text": "x" * 501}]}},
        {"criteria": {"include": many("i", 11)}},
        {"criteria": {"exclude": many("e", 11)}},
        {"criteria": {"include": [{"key": "e1", "text": "Wrong prefix here."}]}},
        {"criteria": {"include": [{"key": "i1", "text": "One."}, {"key": "i1", "text": "Two."}]}},
        {"criteria": {"include": [{"key": "i1", "text": "Fine text.", "weight": 2}]}},
        {"years": {"from": 2020, "to": 2019}},
        {"years": {"since": 2020}},
        {"thresholds": {"keep_min": 0.05, "include_fail_max": 0.05}},
        {"thresholds": {"exclude_hit_min": 0.2, "exclude_clear_max": 0.2}},
        {"thresholds": {"keep_min": 1.5}},
    ],
)
def test_invalid_domains_are_refused(overrides):
    with pytest.raises(ValidationError):
        DomainSpec.model_validate(domain(**overrides))


def test_read_domain_reports_every_problem_in_one_readable_message(tmp_path):
    path = tmp_path / "domain.json"
    path.write_text(json.dumps(domain(topic="x", sources=[])))
    with pytest.raises(DomainError) as info:
        read_domain(path)
    message = str(info.value)
    assert message.startswith("domain.json is invalid: ")
    assert "topic: String should have at least 3 characters" in message
    assert "sources: List should have at least 1 item" in message


def test_read_domain_refuses_unreadable_and_non_json_files(tmp_path):
    with pytest.raises(DomainError, match="cannot read"):
        read_domain(tmp_path / "missing.json")
    bad = tmp_path / "bad.json"
    bad.write_text("{not json")
    with pytest.raises(DomainError, match="not valid JSON"):
        read_domain(bad)
    good = tmp_path / "good.json"
    good.write_text(json.dumps(domain()))
    assert read_domain(good).topic.startswith("machine learning")


def test_contract_carries_the_domain_and_round_trips_through_a_dump():
    spec = DomainSpec.model_validate(domain())
    contract = Contract(topic=spec.topic, domain=spec)
    dumped = contract.model_dump()
    assert dumped["domain"]["years"] == {"from": 2018, "to": None} and dumped["domain"]["schema"] == 1
    assert Contract.model_validate(dumped) == contract
    with pytest.raises(ValidationError, match="topic must equal"):
        Contract(topic="something else entirely", domain=spec)
    assert Contract(topic="legacy topic").model_dump()["domain"] is None


def test_paper_sources_default_to_empty_for_old_reports():
    paper = {
        "id": "x:1",
        "title": "t",
        "abstract": "a",
        "provenance": [
            {
                "connector": "c",
                "record_id": "x:1",
                "url": "u",
                "query": "q",
                "retrieved_at": "r",
                "raw_sha256": "h",
            }
        ],
    }
    assert Paper.model_validate(paper).sources == []
    assert Paper.model_validate({**paper, "sources": ["openalex"]}).sources == ["openalex"]


def test_every_search_source_is_a_valid_domain_source_and_a_field_may_list_all():
    from research_agent.schemas import SEARCH_SOURCES

    spec = DomainSpec.model_validate(domain(sources=[{"name": n} for n in SEARCH_SOURCES]))
    assert [s.name for s in spec.sources] == list(SEARCH_SOURCES) and len(SEARCH_SOURCES) == 12


def test_queries_may_name_new_sources():
    spec = DomainSpec.model_validate(domain(sources=[{"name": "pubmed"}], queries={"pubmed": '"ct"[tiab]'}))
    assert spec.queries == {"pubmed": '"ct"[tiab]'}


def test_paper_dump_omits_empty_new_ids_and_keeps_set_ones():
    from research_agent.schemas import Paper, Source

    prov = Source(connector="x", record_id="x", url="u", query="q", retrieved_at="t", raw_sha256="h")
    paper = Paper(id="a", title="t", abstract="a", provenance=[prov])
    assert not {"pmid", "arxiv", "s2"} & set(paper.model_dump())
    paper = Paper(id="a", title="t", abstract="a", provenance=[prov], pmid="1", s2="abc")
    dumped = paper.model_dump()
    assert dumped["pmid"] == "1" and dumped["s2"] == "abc" and "arxiv" not in dumped
    assert Paper.model_validate(dumped) == paper
