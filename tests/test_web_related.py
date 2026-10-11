"""Reader step 3: find related / earlier work (worker job reader_related). Stub connectors and demo only."""

import uuid

import pytest
from sqlalchemy import select

from research_agent.connectors import SourceKeyMissing, SourceUnavailable
from research_agent.schemas import Paper as SearchPaper
from research_agent.schemas import Source
from research_agent.web.db.models import Job, LibraryItem, Paper, Run
from research_agent.web.related import RelatedFailed, find_related, key_terms, keywords_for
from research_agent.web.worker import Worker

API = "/api/v1"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (
            "Synthetic study 1 evaluated retrieval augmented generation on a toy dataset.",
            ["retrieval augmented generation", "toy dataset", "Synthetic"],
        ),
        (
            "We propose a U-Net for CT liver segmentation with deep learning; the AUC was 0.91 on external validation.",
            ["CT liver segmentation", "deep learning", "external validation", "U-Net", "AUC"],
        ),
        ("MRI and CT were compared.", ["MRI", "CT"]),
        ("the of and with", []),
        ("", []),
        ("transformer transformer attention", ["transformer attention"]),
        ("Radiomics. Radiomics features. Texture.", ["Radiomics features", "Texture"]),
    ],
)
def test_key_terms(text, expected):
    assert key_terms(text) == expected


def test_key_terms_are_capped_and_deterministic():
    text = "alpha beta. gamma delta. epsilon zeta. eta theta. iota kappa. lambda mu."
    assert key_terms(text) == key_terms(text) and len(key_terms(text)) == 5
    assert keywords_for(["a b", "c"]) == {"all": ["a b"], "any": ["c"], "none": []}
    assert keywords_for([]) is None


# --- the job with stub connectors --------------------------------------------------------------------------


def paper(pid, title, year="2020", doi="", source="europepmc"):
    return SearchPaper(
        id=pid,
        title=title,
        abstract=f"{title}. Retrieval augmented generation on a toy dataset.",
        year=year,
        doi=doi,
        sources=[source],
        provenance=[
            Source(
                connector=source,
                record_id=pid,
                url=f"https://example.org/{pid}",
                query="q",
                retrieved_at="",
                raw_sha256="",
            )
        ],
    )


class Stub:
    def __init__(self, papers=None, error=None):
        self.papers, self.error, self.queries = papers or [], error, []

    def search(self, query, limit):
        self.queries.append((query, limit))
        if self.error:
            raise self.error
        return self.papers[:limit]


SELECTION = "Synthetic study 1 evaluated retrieval augmented generation on a toy dataset."


def me_of(db):
    return db.scalar(select(Paper).where(Paper.source_id == "demo:1"))


def test_partial_failure_is_a_warning_and_dedup_merges(db, imported):
    me = me_of(db)
    stubs = {
        "europepmc": Stub(
            [paper("x:1", "Grounded RAG", "2019", doi="10.1/a"), paper("x:2", "Old RAG", "2015")]
        ),
        "openalex": Stub(
            [paper("y:9", "Grounded RAG", "2019", doi="https://doi.org/10.1/A", source="openalex")]
        ),
        "core": Stub(error=SourceUnavailable("core", reason="rate limited (HTTP 429)")),
        "ieee": Stub(error=SourceKeyMissing("ieee", "IEEE_API_KEY")),
    }
    result = find_related(db, me, SELECTION, "related", names=list(stubs), make=stubs.__getitem__)
    assert result["terms"][0] == "retrieval augmented generation"
    assert stubs["europepmc"].queries[0][1] == 10
    assert "TITLE_ABS:" in result["queries"]["europepmc"]
    assert {w["source"] for w in result["warnings"]} == {"core", "ieee"}
    assert all(w["reason"] and "KEY" not in w["reason"] for w in result["warnings"])
    grounded = [r for r in result["results"] if r["title"] == "Grounded RAG"]
    assert len(grounded) == 1 and grounded[0]["sources"] == ["europepmc", "openalex"]
    assert grounded[0]["url"] == "https://doi.org/10.1/a"


def test_all_sources_failing_fails_the_job(db, imported):
    stubs = {
        "europepmc": Stub(error=SourceUnavailable("europepmc", reason="timeout")),
        "openalex": Stub(error=RuntimeError("boom")),
    }
    with pytest.raises(RelatedFailed, match="No search source answered"):
        find_related(db, me_of(db), SELECTION, "related", names=list(stubs), make=stubs.__getitem__)


def test_self_is_excluded_and_badges_are_set(db, imported):
    me = me_of(db)
    run = db.get(Run, imported["research"])
    run.name = "RAG run"
    other = db.scalar(select(Paper).where(Paper.source_id == "demo:2"))
    db.add(LibraryItem(paper_id=other.id, run_id=run.id))
    db.flush()
    stubs = {
        "europepmc": Stub(
            [
                paper("demo:1", me.title, str(me.year or "")),  # the paper being read, by id
                paper("z:1", me.title, str(me.year or "")),  # ... and by title
                paper("demo:2", other.title, str(other.year or "")),
            ]
        )
    }
    result = find_related(db, me, SELECTION, "related", names=["europepmc"], make=stubs.__getitem__)
    titles = [r["title"] for r in result["results"]]
    assert me.title not in titles
    row = next(r for r in result["results"] if r["paper_id"] == str(other.id))
    assert row["in_library"] and row["seen_in_runs"][0]["name"] == "RAG run"
    assert row["sources"] == ["europepmc"]  # the team library is a badge, not a source
    local_only = [r for r in result["results"] if not r["sources"]]
    assert local_only and all(r["seen_in_runs"] for r in local_only)  # papers seen in runs, found locally


def test_earlier_work_sorts_by_year_ascending(db, imported):
    stubs = {"europepmc": Stub([paper("a", "C", "2021"), paper("b", "A", ""), paper("c", "B", "2003")])}
    result = find_related(db, me_of(db), SELECTION, "earlier", names=["europepmc"], make=stubs.__getitem__)
    years = [r["year"] for r in result["results"] if not r["paper_id"]]
    assert years == ["2003", "2021", None] and result["mode"] == "earlier"
    assert "paper_year" in result
    assert not any(w in str(result).casefold() for w in ("novel", "novelty", "first to"))


def test_nothing_to_search_is_refused(db, imported):
    with pytest.raises(RelatedFailed, match="no key terms"):
        find_related(db, me_of(db), "the of and", "related", names=["europepmc"], make=lambda n: Stub())


# --- API + worker (demo, real sessions) ----------------------------------------------------------------------


def test_viewers_cannot_search_members_can(sign_in, imported, db):
    me = me_of(db)
    url = f"{API}/runs/{imported['research']}/papers/{me.id}/reader/related"
    viewer, vcsrf = sign_in("viewer")
    assert viewer.post(url, json={"selection": SELECTION}, headers=vcsrf).status_code == 403
    member, csrf = sign_in("member")
    r = member.post(url, json={"selection": SELECTION, "mode": "earlier"}, headers=csrf)
    assert r.status_code == 202 and r.json()["kind"] == "reader_related" and r.json()["run_id"] is None
    job = db.get(Job, uuid.UUID(r.json()["id"]))
    assert job.payload["reader_run_id"] == str(imported["research"]) and "run_id" not in job.payload
    assert job.payload["mode"] == "earlier" and job.payload["search_mode"] == "demo"
    bad = member.post(url, json={"selection": "the of"}, headers=csrf)
    assert bad.status_code == 422 and bad.json()["code"] == "no_terms"


@pytest.fixture
def related_world(world):
    from web_fixtures import make_demo_run

    from research_agent.web.importer.research import import_research_run

    settings, factory, sign_in = world
    with factory() as db:
        run_id = import_research_run(db, make_demo_run(settings.runs_dir / "demo")).run_id
        me = db.scalar(select(Paper).where(Paper.source_id == "demo:1"))
        db.commit()
    return settings, factory, sign_in, run_id, me


def test_demo_job_finds_related_without_network(related_world):
    settings, factory, sign_in, run_id, me = related_world
    member, csrf = sign_in("member")
    r = member.post(
        f"{API}/runs/{run_id}/papers/{me.id}/reader/related", json={"selection": SELECTION}, headers=csrf
    )
    Worker(settings, factory).drain()
    job = member.get(f"{API}/jobs/{r.json()['id']}").json()
    assert job["status"] == "done", job
    result = job["progress"]["result"]
    assert result["search_mode"] == "demo" and result["answered"] == ["europepmc"] and not result["warnings"]
    assert result["results"] and all(row["title"] != me.title for row in result["results"])
    assert any(row["seen_in_runs"] for row in result["results"])
    with factory() as db:
        assert db.get(Run, run_id).status == "done"
