"""Field versions with a description, keyword groups and query overrides; runs get the built queries."""

import uuid

import pytest
import sqlalchemy as sa

from research_agent.web.db.migrate import upgrade
from research_agent.web.db.models import FieldVersion, Job, Run, SourceRow

API = "/api/v1"
KEYWORDS = {"all": ["CT-FFR"], "any": ["deep learning", "CNN", "cnn"], "none": ["review"]}
DRAFT = {
    "name": "ML CT-FFR",
    "topic": "machine learning estimation of CT-derived fractional flow reserve",
    "include": [{"text": "The study uses machine learning."}],
    "exclude": [],
    "sources": ["europepmc", "openalex"],
    "years": {"from": 2018, "to": None},
}


def create(client, csrf, **overrides):
    return client.post(f"{API}/fields", json={**DRAFT, **overrides}, headers=csrf)


def test_a_version_keeps_description_keywords_and_overrides(sign_in):
    member, csrf = sign_in("member")
    r = create(
        member,
        csrf,
        description="  FFR estimated from coronary CT with ML. ",
        keywords=KEYWORDS,
        query_override={"openalex": '"CT-FFR"', "europepmc": None},
    )
    assert r.status_code == 201, r.text
    current = r.json()["current"]
    assert current["description"] == "FFR estimated from coronary CT with ML."
    assert current["keywords"] == {"all": ["CT-FFR"], "any": ["deep learning", "CNN"], "none": ["review"]}
    assert current["query_override"] == {"europepmc": None, "openalex": '"CT-FFR"', "arxiv": None}
    assert current["queries"] == {
        "europepmc": 'TITLE_ABS:"CT-FFR" AND (TITLE_ABS:"deep learning" OR TITLE_ABS:CNN) NOT TITLE_ABS:review',
        "openalex": '"CT-FFR"',
    }


def test_a_version_without_keywords_reads_as_before(sign_in):
    member, csrf = sign_in("member")
    current = create(member, csrf).json()["current"]
    assert current["description"] == "" and current["keywords"] is None
    assert current["query_override"] is None and current["queries"] is None


@pytest.mark.parametrize(
    "extra",
    [
        {"keywords": {"none": ["review"]}},
        {"keywords": {"all": ["x" * 81]}},
        {"keywords": {"all": ["line\nbreak"]}},
        {"keywords": {"all": ["x"] * 21}},
        {"keywords": {"all": [""]}},
        {"query_override": {"openalex": "a, b"}},
        {"query_override": {"arxiv": "x" * 2001}},
        {"description": "x" * 2001},
    ],
)
def test_invalid_keyword_input_is_refused(sign_in, extra):
    member, csrf = sign_in("member")
    assert create(member, csrf, **extra).status_code == 422


def test_saving_a_new_version_can_change_keywords(sign_in):
    member, csrf = sign_in("member")
    field_id = create(member, csrf, keywords=KEYWORDS).json()["id"]
    body = {**DRAFT, "base_version": 1, "keywords": {"all": ["FFR"]}}
    r = member.post(f"{API}/fields/{field_id}/versions", json=body, headers=csrf)
    assert r.status_code == 201, r.text
    assert r.json()["current"]["keywords"] == {"all": ["FFR"], "any": [], "none": []}
    old = member.get(f"{API}/fields/{field_id}/versions/1").json()
    assert old["keywords"]["any"] == ["deep learning", "CNN"]


def test_a_run_gets_queries_for_its_enabled_sources(world):
    _settings, factory, sign_in = world
    member, csrf = sign_in("member")
    with factory() as db:
        db.get(SourceRow, "openalex").enabled = True
        db.commit()
    field_id = create(
        member, csrf, keywords=KEYWORDS, description="about FFR", query_override={"openalex": "custom"}
    ).json()["id"]
    r = member.post(f"{API}/runs", json={"field_id": field_id, "max_papers": 3, "mode": "demo"}, headers=csrf)
    assert r.status_code == 202, r.text
    with factory() as db:
        run = db.get(Run, uuid.UUID(r.json()["run_id"]))
        domain = run.manifest["domain_request"]
        assert db.get(Job, uuid.UUID(r.json()["job"]["id"])).payload["domain"] == domain
    assert domain["queries"]["openalex"] == "custom"
    assert domain["queries"]["europepmc"].startswith('TITLE_ABS:"CT-FFR"')
    assert domain["keywords"]["all"] == ["CT-FFR"] and domain["description"] == "about FFR"


def test_a_run_without_keywords_has_no_queries(world):
    _settings, factory, sign_in = world
    member, csrf = sign_in("member")
    field_id = create(member, csrf).json()["id"]
    r = member.post(f"{API}/runs", json={"field_id": field_id, "max_papers": 3, "mode": "demo"}, headers=csrf)
    with factory() as db:
        domain = db.get(Run, uuid.UUID(r.json()["run_id"])).manifest["domain_request"]
    assert not {"queries", "keywords", "description"} & set(domain)


def test_the_criteria_test_of_a_draft_carries_its_queries(sign_in, db):
    member, csrf = sign_in("member")
    field_id = create(member, csrf).json()["id"]
    draft = {**DRAFT, "keywords": {"any": ["FFR"]}}
    r = member.post(f"{API}/fields/{field_id}/test", json={"draft": draft, "mode": "demo"}, headers=csrf)
    assert r.status_code == 202, r.text
    job = db.get(Job, uuid.UUID(r.json()["id"]))
    assert job.payload["domain"]["queries"] == {"europepmc": "TITLE_ABS:FFR"}


def test_the_demo_worker_runs_a_keyword_field_without_a_planning_call(world):
    import sqlite3

    from research_agent.web.worker import Worker

    settings, factory, sign_in = world
    member, csrf = sign_in("member")
    field_id = create(member, csrf, keywords=KEYWORDS).json()["id"]
    r = member.post(f"{API}/runs", json={"field_id": field_id, "max_papers": 3, "mode": "demo"}, headers=csrf)
    Worker(settings, factory).drain()
    with factory() as db:
        run = db.get(Run, uuid.UUID(r.json()["run_id"]))
        assert run.status == "done", run.error
        folder = run.folder
        # the import links the run to the version it started from (keywords compared too)
        versions = db.scalars(sa.select(FieldVersion).where(FieldVersion.field_id == run.field_id)).all()
        assert [v.version for v in versions] == [1] and run.field_version_id == versions[0].id
    with sqlite3.connect(f"{folder}/research.sqlite") as store:
        roles = {role for (role,) in store.execute("select role from calls")}
    assert "plan" not in roles


def test_migration_0004_up_and_down(pg_url, pg_engine):
    name = f"k_{uuid.uuid4().hex[:10]}"
    with pg_engine.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
        connection.execute(sa.text(f'create database "{name}"'))
    url = sa.engine.make_url(pg_url).set(database=name).render_as_string(hide_password=False)
    try:
        upgrade(url, "0004")
        engine = sa.create_engine(url)
        columns = {c["name"] for c in sa.inspect(engine).get_columns("field_versions")}
        assert {"description", "keywords", "query_override"} <= columns
        from alembic import command

        from research_agent.web.db.migrate import alembic_config

        command.downgrade(alembic_config(url), "0003")
        columns = {c["name"] for c in sa.inspect(engine).get_columns("field_versions")}
        assert not {"description", "keywords", "query_override"} & columns
        upgrade(url, "0004")
        engine.dispose()
    finally:
        with pg_engine.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
            connection.execute(sa.text(f'drop database "{name}" with (force)'))
