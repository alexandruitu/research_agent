"""Authors in the web app: the importer and its identifier-only merge, display on rows / drawer / reader /
library, the author filter (by id and by name) on papers, groups and library, the typeahead, and the OpenAlex
backfill (a stub: no network)."""

import uuid

import httpx
import pytest
from sqlalchemy import func, select
from web_fixtures import add_authors, make_demo_run

from research_agent import ratelimit
from research_agent.web.authors import backfill, store_paper_authors
from research_agent.web.db.models import Author, Paper, PaperAuthor
from research_agent.web.importer.research import import_research_run
from research_agent.web.worker import Worker

API = "/api/v1"
ORCID = "0000-0002-1825-0097"
ANA = {"name": "Ana Popescu", "orcid": ORCID, "openalex_id": "A1", "affiliations": ["Carol Davila"]}
JON_ID = {"name": "Jon Smith", "openalex_id": "A2"}  # an identified Jon Smith
JON = {"name": "Jon Smith"}  # a name-only Jon Smith: maybe the same person, maybe not


@pytest.fixture(autouse=True)
def no_waits(monkeypatch):
    monkeypatch.setattr("research_agent.connectors.time.sleep", lambda s: None)
    monkeypatch.setattr(ratelimit.TokenBucket, "acquire", lambda self: 0.0)


def paper_row(db, source_id):
    return db.scalar(select(Paper).where(Paper.source_id == source_id))


def names(db, source_id):
    paper = paper_row(db, source_id)
    return [
        (a.name, a.orcid, a.openalex_id)
        for _, a in db.execute(
            select(PaperAuthor, Author)
            .join(Author, Author.id == PaperAuthor.author_id)
            .where(PaperAuthor.paper_id == paper.id)
            .order_by(PaperAuthor.position)
        )
    ]


@pytest.fixture
def authored(db, tmp_path):
    """A demo run whose papers have authors: demo:1 (Ana, identified Jon, 2 more), demo:2 (Ana as an OpenAlex-
    only record, name-only Jon), demo:3 (name-only Jon)."""
    folder = add_authors(make_demo_run(tmp_path / "runs" / "a"))  # web_fixtures.DEMO_AUTHORS
    run = import_research_run(db, folder).run_id
    db.commit()
    return run


def test_the_importer_stores_authors_and_merges_only_by_identifier(db, authored):
    assert names(db, "demo:1") == [
        ("Ana Popescu", ORCID, "A1"),
        ("Jon Smith", None, "A2"),
        ("Third Author", None, None),
        ("Fourth Author", None, None),
    ]
    # the OpenAlex id finds Ana's row (her name as first stored stays); name-only Jon is a separate row
    assert names(db, "demo:2") == [("Ana Popescu", ORCID, "A1"), ("Jon Smith", None, None)]
    jons = db.scalars(select(Author).where(Author.normalized_name == "jon smith")).all()
    assert sorted((j.openalex_id or "") for j in jons) == ["", "A2"]  # never merged into the identified one
    link = db.scalar(select(PaperAuthor).where(PaperAuthor.paper_id == paper_row(db, "demo:1").id))
    assert link.position == 1 and link.affiliations == ["Carol Davila"]


def test_an_identifier_seen_later_completes_the_row_without_merging_people(db, tmp_path):
    paper = Paper(source_id="x:1", title="t")
    other = Paper(source_id="x:2", title="t")
    db.add_all([paper, other])
    db.flush()
    store_paper_authors(db, paper, [{"name": "Ana Popescu", "openalex_id": "A1"}])
    store_paper_authors(db, other, [{"name": "Ana Popescu", "openalex_id": "A1", "orcid": ORCID}])
    [row] = db.scalars(select(Author).where(Author.openalex_id == "A1")).all()
    assert row.orcid == ORCID
    # a different ORCID on another OpenAlex id is another person
    store_paper_authors(
        db, other, [{"name": "Ana Popescu", "openalex_id": "A9", "orcid": "0000-0001-0000-0001"}]
    )
    assert (
        db.scalar(select(func.count()).select_from(Author).where(Author.normalized_name == "ana popescu"))
        == 2
    )


def test_reimporting_a_run_without_authors_keeps_stored_authors(db, tmp_path, authored):
    plain = import_research_run(
        db, make_demo_run(tmp_path / "runs" / "b")
    ).run_id  # same demo ids, no authors
    db.commit()
    assert plain != authored
    assert names(db, "demo:3") == [("Jon Smith", None, None)]


def test_rows_drawer_and_reader_show_authors(sign_in, db, authored):
    viewer, _ = sign_in("viewer")
    rows = viewer.get(f"{API}/runs/{authored}/papers", params={"page_size": 50}).json()["items"]
    first = next(r for r in rows if r["paper"]["source_id"] == "demo:1")
    assert [a["name"] for a in first["authors"]] == ["Ana Popescu", "Jon Smith", "Third Author"]
    assert first["author_count"] == 4 and first["authors"][0]["orcid"] == ORCID
    bare = next(r for r in rows if r["paper"]["source_id"] == "demo:4")
    assert bare["authors"] == [] and bare["author_count"] == 0
    paper_id = first["paper"]["id"]
    drawer = viewer.get(f"{API}/runs/{authored}/papers/{paper_id}").json()
    assert len(drawer["authors"]) == 4 and drawer["authors"][0]["affiliations"] == ["Carol Davila"]
    reader = viewer.get(f"{API}/runs/{authored}/papers/{paper_id}/reader").json()
    assert [a["position"] for a in reader["authors"]] == [1, 2, 3, 4]


def ids(response):
    assert response.status_code == 200, response.text
    return sorted(r["paper"]["source_id"] for r in response.json()["items"])


def test_filter_papers_by_author_id_and_by_name(sign_in, db, authored):
    viewer, _ = sign_in("viewer")
    url = f"{API}/runs/{authored}/papers"
    ana = db.scalar(select(Author.id).where(Author.orcid == ORCID))
    assert ids(viewer.get(url, params={"author_id": str(ana)})) == ["demo:1", "demo:2"]
    jon_id = db.scalar(select(Author.id).where(Author.openalex_id == "A2"))
    assert ids(viewer.get(url, params={"author_id": str(jon_id)})) == ["demo:1"]  # the identified one only
    # a name match covers every Jon Smith, identified or not
    assert ids(viewer.get(url, params={"author_name": "  JON smith "})) == ["demo:1", "demo:2", "demo:3"]
    assert ids(viewer.get(url, params={"author_name": "Nobody"})) == []
    assert ids(viewer.get(url, params={"author_id": str(uuid.uuid4())})) == []
    both = viewer.get(url, params={"author_name": "jon smith", "decision": "include"})
    assert set(ids(both)) <= {"demo:1", "demo:2", "demo:3"}
    groups = viewer.get(f"{url}/groups", params={"by": "year", "author_id": str(ana)}).json()
    assert sum(g["count"] for g in groups) == 2
    assert viewer.get(url, params={"author_name": ""}).status_code == 422
    assert viewer.get(url, params={"author_id": "not-a-uuid"}).status_code == 422


def test_filter_library_by_author(sign_in, db, authored):
    member, csrf = sign_in("member")
    papers = [str(paper_row(db, s).id) for s in ("demo:1", "demo:3", "demo:4")]
    r = member.post(f"{API}/library", json={"run_id": str(authored), "paper_ids": papers}, headers=csrf)
    assert r.status_code == 201, r.text
    items = member.get(f"{API}/library", params={"scope": "personal"}).json()["items"]
    by_source = {i["paper"]["source_id"]: i for i in items}
    assert by_source["demo:1"]["author_count"] == 4 and len(by_source["demo:1"]["authors"]) == 3
    jon_id = db.scalar(select(Author.id).where(Author.openalex_id == "A2"))
    mine = {"scope": "personal"}
    assert ids(member.get(f"{API}/library", params={"author_id": str(jon_id)} | mine)) == ["demo:1"]
    assert ids(member.get(f"{API}/library", params={"author_name": "Jon Smith"} | mine)) == [
        "demo:1",
        "demo:3",
    ]
    detail = member.get(f"{API}/library/{by_source['demo:1']['id']}").json()
    assert len(detail["authors"]) == 4


def test_typeahead_lists_identified_first_with_counts(sign_in, db, authored):
    viewer, _ = sign_in("viewer")
    found = viewer.get(f"{API}/authors", params={"q": "jon"}).json()
    assert [(a["name"], a["openalex_id"], a["paper_count"]) for a in found] == [
        ("Jon Smith", "A2", 1),
        ("Jon Smith", None, 2),
    ]
    assert viewer.get(f"{API}/authors", params={"q": "popescu ana"}).json()[0]["paper_count"] == 2
    scoped = viewer.get(f"{API}/authors", params={"q": "author", "run_id": str(authored)}).json()
    assert {a["name"] for a in scoped} == {"Third Author", "Fourth Author"}
    assert viewer.get(f"{API}/authors", params={"q": "jon", "library": True}).json() == []
    assert viewer.get(f"{API}/authors", params={"q": "jon", "run_id": str(uuid.uuid4())}).status_code == 404
    one = viewer.get(f"{API}/authors/{found[0]['id']}").json()
    assert one["name"] == "Jon Smith" and one["paper_count"] == 1
    assert viewer.get(f"{API}/authors/{uuid.uuid4()}").status_code == 404


def test_backfill_looks_up_papers_with_a_doi_and_no_authors(db):
    papers = {}
    for doi in ("10.1/found", "10.1/missing", "10.1/empty", "10.1/broken"):
        papers[doi] = Paper(source_id=f"d:{doi}", title="t", doi=doi)
    papers["none"] = Paper(source_id="d:nodoi", title="t", doi="")
    db.add_all(papers.values())
    db.flush()
    store_paper_authors(db, papers["10.1/broken"], [])  # still a candidate: nothing stored

    def lookup(doi):
        from research_agent.connectors import SourceUnavailable

        if doi == "10.1/broken":
            raise SourceUnavailable("openalex", reason="server error (HTTP 503)")
        return {"10.1/found": [ANA, JON], "10.1/missing": None, "10.1/empty": []}[doi]

    seen = []
    summary = backfill(db, lookup=lookup, progress=seen.append)
    assert summary == {"total": 4, "done": 4, "updated": 1, "not_found": 1, "no_authors": 1, "failed": 1}
    assert [s["done"] for s in seen] == [1, 2, 3, 4]
    assert names(db, "d:10.1/found") == [("Ana Popescu", ORCID, "A1"), ("Jon Smith", None, None)]
    again = backfill(db, lookup=lookup)
    assert again["total"] == 3  # the found paper is no longer a candidate


def openalex_stub(requests):
    def handler(request):
        requests.append(request)
        if request.url.path.endswith("10.1/unknown"):
            return httpx.Response(404, json={"error": "not found"})
        return httpx.Response(
            200,
            json={
                "id": "https://openalex.org/W9",
                "authorships": [
                    {
                        "author": {
                            "id": "https://openalex.org/A7",
                            "display_name": "Mara Ionescu",
                            "orcid": "https://orcid.org/0000-0003-0000-0007",
                        },
                        "institutions": [{"display_name": "UMF Iasi"}],
                    }
                ],
            },
        )

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_backfill_job_from_settings_runs_in_the_worker(world):
    settings, factory, sign_in = world
    with factory() as db:
        db.add_all(
            [
                Paper(source_id="b:1", title="t", doi="10.1/known"),
                Paper(source_id="b:2", title="t", doi="10.1/unknown"),
            ]
        )
        db.commit()
    admin, csrf = sign_in("admin")
    member, member_csrf = sign_in("member")
    assert member.post(f"{API}/authors/backfill", headers=member_csrf).status_code == 403
    admin.patch(f"{API}/settings", json={"contact_email": "team@example.org"}, headers=csrf)
    assert admin.get(f"{API}/authors/backfill").json() == {"candidates": 2, "job": None}
    r = admin.post(f"{API}/authors/backfill", headers=csrf)
    assert r.status_code == 202 and r.json()["kind"] == "authors_backfill"
    assert admin.post(f"{API}/authors/backfill", headers=csrf).json()["id"] == r.json()["id"]  # one at a time
    requests = []
    Worker(settings, factory, sleep=lambda s: None, http_client=openalex_stub(requests)).tick()
    job = admin.get(f"{API}/jobs/{r.json()['id']}").json()
    assert job["status"] == "done"
    assert job["progress"]["result"] == {
        "total": 2,
        "done": 2,
        "updated": 1,
        "not_found": 1,
        "no_authors": 0,
        "failed": 0,
    }
    assert {q.url.params["mailto"] for q in requests} == {"team@example.org"}  # the polite pool
    assert all(q.url.params["select"] == "id,doi,authorships" for q in requests)
    status = admin.get(f"{API}/authors/backfill").json()
    assert status["candidates"] == 1 and status["job"]["id"] == r.json()["id"]
    found = admin.get(f"{API}/authors", params={"q": "mara"}).json()
    assert [(a["orcid"], a["openalex_id"], a["paper_count"]) for a in found] == [
        ("0000-0003-0000-0007", "A7", 1)
    ]


def test_library_typeahead_counts_only_libraries_the_user_sees(sign_in, db, authored):
    from web_fixtures import give_full_text

    member, csrf = sign_in("member")
    viewer, _ = sign_in("viewer")
    give_full_text(db, "demo:3")
    body = {"run_id": str(authored), "paper_ids": [str(paper_row(db, "demo:1").id)]}
    assert member.post(f"{API}/library", json=body, headers=csrf).status_code == 201  # My library
    company = body | {"paper_ids": [str(paper_row(db, "demo:3").id)], "scope": "company"}
    assert member.post(f"{API}/library", json=company, headers=csrf).status_code == 201

    def counts(client, **extra):
        found = client.get(f"{API}/authors", params={"q": "jon", "library": True, **extra}).json()
        return sorted(((a["openalex_id"] or ""), a["paper_count"]) for a in found)

    assert len(counts(member)) == 2  # both of the member's libraries
    assert counts(member, scope="personal") == [("A2", 1)]  # demo:1 has the identified Jon
    assert counts(member, scope="company") == [("", 1)]  # demo:3 has the name-only Jon
    assert counts(viewer) == [("", 1)]  # the member's own library never counts for others
    assert counts(viewer, scope="personal") == []
