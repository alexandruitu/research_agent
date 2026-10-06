"""Partial search in the web app: required sources on field versions, warnings on imported runs."""

import uuid

import sqlalchemy as sa
from alembic import command

from research_agent import runner
from research_agent.connectors import DemoConnector, MultiSource, SourceUnavailable
from research_agent.runner import run_research
from research_agent.schemas import Contract, DomainSpec
from research_agent.web import fields as svc
from research_agent.web.api.routers.runs import _run_out
from research_agent.web.api.schemas import RunOut
from research_agent.web.db.migrate import alembic_config, upgrade
from research_agent.web.db.models import Field, Run
from research_agent.web.importer.research import import_research_run

API = "/api/v1"
DRAFT = {
    "name": "ML CT-FFR",
    "topic": "machine learning estimation of CT-derived fractional flow reserve",
    "include": [{"text": "The study uses machine learning."}],
    "exclude": [{"text": "The paper is a review without original results."}],
    "sources": ["europepmc", "openalex"],
    "years": {"from": 2018, "to": None},
    "note": "first draft",
}
DOMAIN = {
    "schema": 1,
    "topic": "deep learning CT-FFR",
    "criteria": {"include": [{"key": "i1", "text": "Uses deep learning."}], "exclude": []},
    "sources": [{"name": "europepmc", "max_results": 5}, {"name": "semantic_scholar", "max_results": 5}],
}


class Down:
    name = "semantic_scholar"

    def search(self, query, limit, raw=False):
        raise SourceUnavailable("semantic_scholar", reason="rate limited (HTTP 429)")


def test_a_field_version_stores_its_required_sources(sign_in):
    member, csrf = sign_in("member")
    r = member.post(f"{API}/fields", json={**DRAFT, "required_sources": ["europepmc"]}, headers=csrf)
    assert r.status_code == 201, r.text
    assert r.json()["current"]["required_sources"] == ["europepmc"]
    plain = member.post(f"{API}/fields", json={**DRAFT, "name": "Other"}, headers=csrf)
    assert plain.json()["current"]["required_sources"] == []


def test_a_required_source_must_be_selected(sign_in):
    member, csrf = sign_in("member")
    r = member.post(f"{API}/fields", json={**DRAFT, "required_sources": ["arxiv"]}, headers=csrf)
    assert r.status_code == 422


def test_the_domain_marks_required_sources_only(db):
    field = Field(name="f", topic="deep learning CT-FFR")
    db.add(field)
    db.flush()
    domain = svc.build_domain(
        db,
        field,
        None,
        topic=field.topic,
        include=["Uses deep learning."],
        exclude=[],
        names=["europepmc", "openalex"],
        years={"from": None, "to": None},
        required=["europepmc"],
    )
    flags = {s["name"]: s.get("required", False) for s in domain["sources"]}
    assert flags.pop("europepmc") is True and not any(flags.values())  # openalex: off unless enabled


def test_an_imported_run_carries_its_search_warnings(db, tmp_path, monkeypatch):
    spec = DomainSpec.model_validate(DOMAIN)
    monkeypatch.setattr(
        runner,
        "make_connector",
        lambda c, store: MultiSource([(DemoConnector(store, source="europepmc"), 5), (Down(), 5)]),
    )
    folder = tmp_path / "run"
    run_research(folder, Contract(topic=spec.topic, domain=spec, max_papers=2))
    run = db.get(Run, import_research_run(db, folder).run_id)
    (warning,) = run.search_warnings
    assert warning["source"] == "semantic_scholar" and warning["reason"] == "rate limited (HTTP 429)"
    out = _run_out(db, run, RunOut, names={})
    assert (
        out.search_warnings[0].source == "semantic_scholar" and "S2_API_KEY" in out.search_warnings[0].detail
    )


def test_a_legacy_run_has_no_search_record(db, tmp_path):
    folder = tmp_path / "run"
    run_research(folder, Contract(topic="retrieval augmented generation", max_papers=1))
    run = db.get(Run, import_research_run(db, folder).run_id)
    assert run.search_warnings is None and _run_out(db, run, RunOut, names={}).search_warnings is None


def test_migration_adds_and_drops_the_column(pg_url, pg_engine):
    name = f"r_{uuid.uuid4().hex[:10]}"
    with pg_engine.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
        connection.execute(sa.text(f'create database "{name}"'))
    url = sa.engine.make_url(pg_url).set(database=name).render_as_string(hide_password=False)
    try:
        upgrade(url)
        engine = sa.create_engine(url)
        assert "search_warnings" in {c["name"] for c in sa.inspect(engine).get_columns("runs")}
        engine.dispose()
        command.downgrade(alembic_config(url), "0008")
        engine = sa.create_engine(url)
        assert "search_warnings" not in {c["name"] for c in sa.inspect(engine).get_columns("runs")}
        engine.dispose()
    finally:
        with pg_engine.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
            connection.execute(sa.text(f'drop database "{name}" with (force)'))
