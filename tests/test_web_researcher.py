"""Researcher topics in the web app: the author_lookup job (stubbed OpenAlex / Semantic Scholar, and demo),
co-author computation, the topic version round-trip, the default criterion, preview, and "Matched by" on the
Results rows of a demo run (no network)."""

import uuid

import httpx
import pytest

from research_agent import ratelimit
from research_agent.authorsearch import DEFAULT_CRITERION
from research_agent.storage import Store
from research_agent.web.authorlookup import author_lookup, coauthors_of
from research_agent.web.db.models import Job, Run, SourceRow
from research_agent.web.preview import field_preview
from research_agent.web.worker import Worker

API = "/api/v1"
ANA = {"name": "Ana Popescu", "openalex_id": "A1", "orcid": "0000-0002-1825-0097", "s2_id": ""}
AUTHORS = {
    "people": [ANA],
    "group": "coauthors",
    "coauthors": [{"name": "Bob Stan", "openalex_id": "A2", "orcid": "", "s2_id": ""}],
    "institutions": [],
    "min_shared": 3,
}
DRAFT = {
    "name": "Ana Popescu",
    "topic": "Papers by Ana Popescu and her co-authors",
    "include": [],
    "exclude": [],
    "sources": ["openalex", "pubmed", "europepmc", "arxiv"],
    "years": {"from": 2018, "to": None},
    "authors": AUTHORS,
}


@pytest.fixture(autouse=True)
def no_waits(monkeypatch):
    monkeypatch.setattr("research_agent.connectors.time.sleep", lambda s: None)
    monkeypatch.setattr(ratelimit.TokenBucket, "acquire", lambda self: 0.0)


def authorship(aid, name, orcid="", inst=None):
    row = {"author": {"id": f"https://openalex.org/{aid}", "display_name": name, "orcid": orcid}}
    if inst:
        row["institutions"] = [{"id": f"https://openalex.org/{inst[0]}", "display_name": inst[1]}]
    return row


WORKS = [
    {
        "id": "W1",
        "doi": "https://doi.org/10.1/a",
        "authorships": [authorship("A1", "Ana", inst=("I5", "UMF")), authorship("A2", "Bob")],
    },
    {
        "id": "W2",
        "doi": None,
        "authorships": [authorship("A1", "Ana"), authorship("A2", "Bob"), authorship("A3", "Cid")],
    },
    {
        "id": "W3",
        "doi": None,
        "authorships": [authorship("A9", "Ana alt"), authorship("A2", "Bob"), authorship("A2", "Bob")],
    },
]


def test_coauthors_count_shared_works_once_and_exclude_the_people():
    coauthors, institutions = coauthors_of(WORKS, ["A1", "A9"])
    assert [(c["openalex_id"], c["shared"]) for c in coauthors] == [("A2", 3), ("A3", 1)]
    assert institutions == [{"openalex_id": "I5", "name": "UMF", "works": 1}]


def stub(requests):
    def handler(request):
        requests.append(request)
        if request.url.path == "/authors":
            return httpx.Response(
                200,
                json={
                    "results": [
                        {
                            "id": "https://openalex.org/A1",
                            "display_name": "Ana Popescu",
                            "orcid": "https://orcid.org/0000-0002-1825-0097",
                            "works_count": 40,
                            "last_known_institutions": [
                                {"id": "https://openalex.org/I5", "display_name": "UMF"}
                            ],
                            "topics": [{"display_name": "Imaging"}],
                        }
                    ]
                },
            )
        if request.url.path == "/works":
            return httpx.Response(200, json={"meta": {"next_cursor": None}, "results": WORKS})
        if "semanticscholar" in request.url.host:
            authors = [{"authorId": "777", "externalIds": {"ORCID": "0000-0002-1825-0097"}}]
            return httpx.Response(200, json={"authors": authors})
        return httpx.Response(404)

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_lookup_search_lists_candidates():
    requests = []
    result = author_lookup(
        {"step": "search", "name": "ana popescu"}, client=stub(requests), contact="t@x.org"
    )
    assert result["candidates"] == [
        {
            "openalex_id": "A1",
            "name": "Ana Popescu",
            "orcid": "0000-0002-1825-0097",
            "works_count": 40,
            "institution": {"openalex_id": "I5", "name": "UMF"},
            "concepts": ["Imaging"],
        }
    ]
    assert requests[0].url.params["search"] == "ana popescu" and requests[0].url.params["mailto"] == "t@x.org"


def test_lookup_group_computes_coauthors_and_maps_the_orcid_to_semantic_scholar():
    requests = []
    people = [{"openalex_id": "A1", "name": "Ana Popescu", "orcid": "0000-0002-1825-0097"}]
    result = author_lookup({"step": "group", "people": people}, client=stub(requests))
    assert result["people"][0]["s2_id"] == "777"
    shared = [(c["openalex_id"], c["shared"]) for c in result["coauthors"]]
    assert shared == [("A2", 3), ("A9", 1), ("A3", 1)]  # A9 is another person until it is picked too
    works = next(r for r in requests if r.url.path == "/works")
    assert works.url.params["filter"] == "authorships.author.id:A1"


def test_demo_lookup_is_deterministic_and_offline():
    one = author_lookup({"step": "search", "name": "Ana", "mode": "demo"})
    assert one == author_lookup({"step": "search", "name": "Ana", "mode": "demo"})
    group = author_lookup({"step": "group", "people": [{"openalex_id": "A1", "name": "Ana"}], "mode": "demo"})
    assert [c["shared"] for c in group["coauthors"]] == [7, 3, 1] and group["people"][0]["s2_id"]


def test_the_lookup_job_runs_in_the_worker(world):
    settings, factory, sign_in = world
    member, csrf = sign_in("member")
    r = member.post(
        f"{API}/authors/lookup", json={"step": "search", "name": "Ana", "mode": "demo"}, headers=csrf
    )
    assert r.status_code == 202 and r.json()["kind"] == "author_lookup"
    with factory() as db:
        assert "run_id" not in db.get(Job, uuid.UUID(r.json()["id"])).payload
    Worker(settings, factory).drain()
    job = member.get(f"{API}/jobs/{r.json()['id']}").json()
    assert job["status"] == "done", job
    candidates = job["progress"]["result"]["candidates"]
    assert candidates[0]["name"] == "Ana" and set(candidates[0]) == {
        "openalex_id",
        "name",
        "orcid",
        "works_count",
        "institution",
        "concepts",
    }
    bad = member.post(f"{API}/authors/lookup", json={"step": "group", "people": []}, headers=csrf)
    assert bad.status_code == 422


def enable(db, *names):
    for name in names:
        db.get(SourceRow, name).enabled = True
    db.commit()


def test_a_researcher_topic_round_trips_with_the_default_criterion(sign_in, db):
    enable(db, "openalex", "pubmed", "arxiv")
    member, csrf = sign_in("member")
    r = member.post(f"{API}/fields", json=DRAFT, headers=csrf)
    assert r.status_code == 201, r.text
    current = r.json()["current"]
    assert current["authors"] == AUTHORS
    assert [c["text"] for c in current["include"]] == [DEFAULT_CRITERION]
    assert current["queries"]["openalex"] == "authorships.author.id:A1|A2"
    assert current["queries"]["arxiv"] == "skipped: arXiv cannot search by author"
    restricted = DRAFT | {
        "keywords": {"all": ["segmentation"]},
        "include": [{"text": "The study segments organs."}],
        "base_version": 1,
    }
    r = member.post(f"{API}/fields/{r.json()['id']}/versions", json=restricted, headers=csrf)
    assert r.status_code == 201, r.text
    current = r.json()["current"]
    assert [c["text"] for c in current["include"]] == ["The study segments organs."]
    assert current["queries"]["pubmed"].endswith("AND (segmentation[tiab])")
    plain = {k: v for k, v in DRAFT.items() if k != "authors"}
    assert member.post(f"{API}/fields", json=plain, headers=csrf).status_code == 422  # criteria still needed


def test_preview_works_for_researcher_topics(sign_in, db, tmp_path):
    enable(db, "openalex", "pubmed", "arxiv")
    member, csrf = sign_in("member")
    body = {"sources": ["openalex", "pubmed", "arxiv"], "authors": AUTHORS, "mode": "demo"}
    r = member.post(f"{API}/fields/preview", json=body, headers=csrf)
    assert r.status_code == 202, r.text
    payload = db.get(Job, uuid.UUID(r.json()["id"])).payload
    assert payload["authors"]["people"][0]["openalex_id"] == "A1"
    rows = {row["source"]: row for row in field_preview(payload, Store(tmp_path))["sources"]}
    assert rows["openalex"]["count"] == 3 and rows["pubmed"]["count"] == 4
    assert (
        rows["arxiv"]["error"] == "Skipped: arXiv cannot search by author" and rows["arxiv"]["count"] is None
    )


def test_a_researcher_run_shows_matched_by_and_filters_by_it(world):
    from test_web_field_runs import pipeline_spawn

    settings, factory, sign_in = world
    with factory() as db:
        enable(db, "openalex", "pubmed", "arxiv")
    member, csrf = sign_in("member")
    field_id = member.post(f"{API}/fields", json=DRAFT, headers=csrf).json()["id"]
    r = member.post(
        f"{API}/runs", json={"field_id": field_id, "max_papers": 10, "mode": "demo"}, headers=csrf
    )
    assert r.status_code == 202, r.text
    run_id = r.json()["run_id"]
    Worker(settings, factory, spawn=pipeline_spawn, sleep=lambda s: None).tick()
    with factory() as db:
        run = db.get(Run, uuid.UUID(run_id))
        assert run.status == "done", run.error
        assert [w["source"] for w in run.search_warnings] == ["arxiv"]
    rows = member.get(f"{API}/runs/{run_id}/papers", params={"page_size": 50}).json()["items"]
    found = {row["paper"]["source_id"]: row["matched_by"] for row in rows}
    assert found["demo-author:person-1"] == [{"kind": "person", "name": "Ana Popescu"}]
    assert found["demo-author:coauthor-1"] == [{"kind": "coauthor", "name": "Bob Stan"}]
    assert found["demo-author:name"] == [{"kind": "name_match", "name": "Ana Popescu"}]
    only = member.get(f"{API}/runs/{run_id}/papers", params={"matched_by": "coauthor"}).json()["items"]
    assert [row["paper"]["source_id"] for row in only] == ["demo-author:coauthor-1"]
    names = member.get(f"{API}/runs/{run_id}/papers", params={"matched_by": "name_match"}).json()["items"]
    assert [row["paper"]["source_id"] for row in names] == ["demo-author:name"]
