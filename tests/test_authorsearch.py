"""Researcher topics in the pipeline: per-source author queries, skipped sources with warnings, the OpenAlex
and Semantic Scholar author connectors (stubbed HTTP), demo records, and "Matched by" (no network)."""

import httpx
import pytest

from research_agent import ratelimit
from research_agent.authorsearch import (
    DEFAULT_CRITERION,
    build_author_queries,
    matched_by,
    skip_reason,
    skipped,
)
from research_agent.connectors import MultiSource, SourceNotApplicable
from research_agent.querybuild import QueryError
from research_agent.schemas import AuthorSearch, DomainSpec, Years
from research_agent.sources import DemoAuthorConnector, NotApplicable, make_connector
from research_agent.storage import Store

ANA = {"name": "Ana Popescu", "openalex_id": "A1", "orcid": "0000-0002-1825-0097", "s2_id": "111"}
BOB = {"name": "Bob Stan", "openalex_id": "A2"}  # no ORCID: searched by name in PubMed / Europe PMC
SPEC = {"people": [ANA], "group": "coauthors", "coauthors": [BOB], "institutions": [], "min_shared": 3}
INST = {"people": [ANA], "group": "institution", "institutions": [{"name": "UMF Iasi", "openalex_id": "I5"}]}
KEYWORDS = {"all": ["segmentation"], "any": [], "none": []}


@pytest.fixture(autouse=True)
def no_waits(monkeypatch):
    monkeypatch.setattr("research_agent.connectors.time.sleep", lambda s: None)
    monkeypatch.setattr(ratelimit.TokenBucket, "acquire", lambda self: 0.0)


def test_each_source_gets_its_author_query():
    names = ["openalex", "pubmed", "europepmc", "semantic_scholar", "arxiv"]
    q = build_author_queries(SPEC, names)
    assert q["openalex"] == "authorships.author.id:A1|A2"
    assert q["pubmed"] == '(0000-0002-1825-0097[auid] OR "Bob Stan"[au])'
    assert q["europepmc"] == '(AUTHORID:"0000-0002-1825-0097" OR AUTH:"Bob Stan")'
    assert q["semantic_scholar"] == "author:111"
    assert skipped(q["arxiv"]) == "arXiv cannot search by author"


def test_a_topic_restriction_adds_the_keyword_query():
    q = build_author_queries(SPEC, ["openalex", "pubmed", "europepmc"], KEYWORDS)
    assert q["openalex"] == "authorships.author.id:A1|A2,title_and_abstract.search:segmentation"
    assert q["pubmed"].endswith(" AND (segmentation[tiab])")
    assert q["europepmc"].endswith(" AND (TITLE_ABS:segmentation)")


def test_person_only_and_institution_groups():
    person = SPEC | {"group": "person"}
    assert build_author_queries(person, ["openalex"])["openalex"] == "authorships.author.id:A1"
    q = build_author_queries(INST, ["openalex", "pubmed", "europepmc", "semantic_scholar"])
    assert q["openalex"] == "authorships.institutions.lineage:I5"
    assert q["pubmed"] == '"UMF Iasi"[ad]' and q["europepmc"] == 'AFF:"UMF Iasi"'
    assert skipped(q["semantic_scholar"]) == "Semantic Scholar cannot search by institution"


def test_semantic_scholar_without_an_id_is_skipped_with_a_reason():
    spec = SPEC | {"people": [ANA | {"s2_id": ""}], "group": "person"}
    assert "no Semantic Scholar author id" in skip_reason(spec, "semantic_scholar")


def test_a_too_long_query_is_refused():
    many = [{"name": "x" * 60 + str(n), "openalex_id": f"A{n + 10}"} for n in range(50)]
    with pytest.raises(QueryError):
        build_author_queries(SPEC | {"coauthors": many}, ["pubmed"])


def test_institution_group_needs_an_institution():
    with pytest.raises(ValueError):
        AuthorSearch.model_validate(SPEC | {"group": "institution"})


def domain(names, spec=SPEC, keywords=None):
    queries = build_author_queries(spec, names, keywords)
    return DomainSpec.model_validate(
        {
            "schema": 1,
            "topic": "Ana Popescu and group",
            "criteria": {"include": [{"key": "i1", "text": DEFAULT_CRITERION}], "exclude": []},
            "sources": [{"name": n} for n in names],
            "queries": queries,
            "authors": spec,
            **({"keywords": keywords} if keywords else {}),
        }
    )


def test_skipped_sources_warn_and_the_others_answer(tmp_path):
    spec = domain(["openalex", "arxiv"])
    sources = [(make_connector(s, spec, Store(tmp_path), "demo"), 10) for s in spec.sources]
    assert isinstance(sources[1][0], NotApplicable)
    multi = MultiSource(sources, spec.queries)
    papers = multi.search_raw()
    state = multi.check()
    assert papers and state["sources_skipped"] == ["arxiv"]
    (warning,) = state["search_warnings"]
    assert (
        warning["error_type"] == "SourceNotApplicable"
        and warning["reason"] == "arXiv cannot search by author"
    )
    assert "Author search" in warning["detail"]
    with pytest.raises(SourceNotApplicable):
        sources[1][0].search("x", 1)


def test_old_domains_dump_unchanged():
    plain = {
        "schema": 1,
        "topic": "abc topic",
        "criteria": {"include": [{"key": "i1", "text": "Some criterion"}], "exclude": []},
        "sources": [{"name": "europepmc"}],
    }
    assert "authors" not in DomainSpec.model_validate(plain).model_dump(mode="json", by_alias=True)


def test_openalex_author_mode_sends_the_whole_filter(tmp_path):
    seen = []

    def handler(request):
        seen.append(request.url.params)
        return httpx.Response(200, json={"meta": {"count": 0}, "results": []})

    spec = domain(["openalex"])
    spec.years = Years.model_validate({"from": 2020})
    connector = make_connector(
        spec.sources[0], spec, Store(tmp_path), "live", httpx.Client(transport=httpx.MockTransport(handler))
    )
    result = connector.search_with_total(spec.queries["openalex"], 10, raw=True)
    assert seen[0]["filter"] == "authorships.author.id:A1|A2,from_publication_date:2020-01-01"
    assert "search" not in seen[0] and result.query == seen[0]["filter"]


def test_semantic_scholar_lists_each_authors_papers_and_filters_locally(tmp_path):
    seen = []

    def handler(request):
        seen.append(request.url.path)
        rows = [
            {"paperId": "p1", "title": "Liver segmentation", "abstract": "a", "year": 2022, "authors": []},
            {"paperId": "p2", "title": "Other topic", "abstract": "b", "year": 2022, "authors": []},
            {"paperId": "p3", "title": "Old segmentation", "abstract": "c", "year": 2001, "authors": []},
        ]
        return httpx.Response(200, json={"data": rows})

    spec = domain(["semantic_scholar"], keywords=KEYWORDS)
    spec.years = Years.model_validate({"from": 2010})
    client = httpx.Client(transport=httpx.MockTransport(handler))
    connector = make_connector(spec.sources[0], spec, Store(tmp_path), "live", client)
    result = connector.search_with_total("author:111", 10, raw=True)
    assert seen == ["/graph/v1/author/111/papers"]
    assert [p.id for p in result.papers] == ["semantic_scholar:p1"]


def test_demo_records_cover_person_coauthors_and_name_matches(tmp_path):
    connector = DemoAuthorConnector(Store(tmp_path), "pubmed", AuthorSearch.model_validate(SPEC))
    papers = connector.search("q", 20)
    ids = [p.id for p in papers]
    assert ids == [
        "demo-author:person-1",
        "demo-author:person-2",
        "demo-author:coauthor-1",
        "demo-author:name",
    ]
    kinds = [matched_by([a.model_dump() for a in p.authors], SPEC)[0]["kind"] for p in papers]
    assert kinds == ["person", "person", "coauthor", "name_match"]
    openalex = DemoAuthorConnector(Store(tmp_path), "openalex", AuthorSearch.model_validate(SPEC))
    assert "demo-author:name" not in [p.id for p in openalex.search("q", 20)]  # searched by id only


def test_matched_by_prefers_identifiers_and_labels_name_only_matches():
    by_id = [{"name": "A. Popescu", "openalex_id": "A1"}, {"name": "Bob Stan"}]
    assert matched_by(by_id, SPEC) == [
        {"kind": "person", "name": "Ana Popescu"},
        {"kind": "name_match", "name": "Bob Stan"},
    ]
    other_bob = [{"name": "Bob Stan", "openalex_id": "A99"}]  # another person with the same name
    assert matched_by(other_bob, SPEC) == [{"kind": "name_match", "name": "Bob Stan"}]
    assert matched_by([{"name": "Bob Stan", "openalex_id": "A2"}], SPEC) == [
        {"kind": "coauthor", "name": "Bob Stan"}
    ]
    at_inst = [{"name": "Someone", "affiliations": ["Dept of Imaging, UMF Iasi, Romania"]}]
    assert matched_by(at_inst, INST) == [{"kind": "institution", "name": "UMF Iasi"}]
    assert matched_by([{"name": "Nobody"}], SPEC) == []
    assert matched_by(by_id, None) == []
