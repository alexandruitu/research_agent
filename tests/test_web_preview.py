"""Field preview: the draft's queries against its sources, counts and first titles, no model."""

import json
import uuid
from pathlib import Path

import httpx

from research_agent.storage import Store
from research_agent.web.db.models import Job, SourceRow
from research_agent.web.preview import field_preview
from research_agent.web.worker import Worker

API = "/api/v1"
FIXTURES = Path(__file__).parent / "fixtures"
BODY = {"keywords": {"all": ["coronary angiography"], "any": ["deep learning"]}, "sources": ["europepmc"]}


def client_for(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_preview_reports_count_query_and_first_papers(tmp_path, monkeypatch):
    monkeypatch.setattr("research_agent.connectors.time.sleep", lambda _s: None)
    epmc = json.loads((FIXTURES / "europepmc_total.json").read_text())

    def handler(request):
        if "ebi.ac.uk" in request.url.host:
            return httpx.Response(200, json=epmc)
        return httpx.Response(503)

    payload = {
        "mode": "live",
        "years": {"from": 2020, "to": None},
        "sources": [{"name": "europepmc"}, {"name": "openalex", "contact": "a@b.org"}],
        "queries": {"europepmc": "TITLE_ABS:x", "openalex": "x"},
    }
    result = field_preview(payload, Store(tmp_path), http_client=client_for(handler))
    europepmc, openalex = result["sources"]
    assert europepmc["count"] == 258 and len(europepmc["papers"]) == 2 and europepmc["error"] is None
    assert europepmc["query"] == "TITLE_ABS:x"
    assert europepmc["effective_query"] == "(TITLE_ABS:x) AND (PUB_YEAR:[2020 TO 9999])"
    assert set(europepmc["papers"][0]) == {"id", "title", "year"}
    assert (
        openalex["error"] == "SourceUnavailable: openalex — server error (HTTP 503)"
        and openalex["count"] is None
    )
    assert result["years"] == {"from": 2020, "to": None}


def test_demo_preview_is_offline(tmp_path):
    payload = {"mode": "demo", "sources": [{"name": "arxiv"}], "queries": {"arxiv": "abs:x"}}
    row = field_preview(payload, Store(tmp_path))["sources"][0]
    assert row["count"] == 10 and len(row["papers"]) == 10 and row["effective_query"] == "abs:x"


def test_member_queues_a_preview_with_built_queries(sign_in, db):
    db.get(SourceRow, "openalex").enabled = True
    db.commit()
    member, csrf = sign_in("member")
    body = BODY | {"sources": ["europepmc", "openalex", "arxiv"], "query_override": {"openalex": "custom"}}
    r = member.post(f"{API}/fields/preview", json=body | {"mode": "demo"}, headers=csrf)
    assert r.status_code == 202, r.text
    assert r.json()["kind"] == "field_preview"
    payload = db.get(Job, uuid.UUID(r.json()["id"])).payload
    assert [s["name"] for s in payload["sources"]] == ["europepmc", "openalex"]  # arXiv is disabled
    assert payload["queries"] == {
        "europepmc": 'TITLE_ABS:"coronary angiography" AND TITLE_ABS:"deep learning"',
        "openalex": "custom",
    }


def test_preview_refusals(sign_in):
    member, csrf = sign_in("member")
    none_only = member.post(f"{API}/fields/preview", json=BODY | {"keywords": {"none": ["x"]}}, headers=csrf)
    assert none_only.status_code == 422
    empty = member.post(f"{API}/fields/preview", json=BODY | {"keywords": None}, headers=csrf)
    assert empty.status_code == 422 and empty.json()["code"] == "no_keywords"
    disabled = member.post(f"{API}/fields/preview", json=BODY | {"sources": ["arxiv"]}, headers=csrf)
    assert disabled.status_code == 422 and disabled.json()["code"] == "no_enabled_source"
    viewer, vcsrf = sign_in("viewer")
    assert viewer.post(f"{API}/fields/preview", json=BODY, headers=vcsrf).status_code == 403


def test_previews_are_rate_limited_per_user(sign_in, db, settings, app):
    from dataclasses import replace

    app.state.settings = replace(settings, max_active_jobs_per_user=20)
    member, csrf = sign_in("member")
    statuses = []
    for _ in range(11):
        r = member.post(f"{API}/fields/preview", json=BODY | {"mode": "demo"}, headers=csrf)
        statuses.append(r.status_code)
        for job in db.query(Job).filter(Job.kind == "field_preview"):
            job.status = "done"  # keep the active-jobs cap out of the way
        db.commit()
    assert statuses[:10] == [202] * 10
    assert statuses[10] == 429 and r.json()["code"] == "rate_limited"


def test_the_worker_answers_a_preview(world):
    settings, factory, sign_in = world
    member, csrf = sign_in("member")
    r = member.post(f"{API}/fields/preview", json=BODY | {"mode": "demo"}, headers=csrf)
    assert r.status_code == 202, r.text
    Worker(settings, factory).drain()
    job = member.get(f"{API}/jobs/{r.json()['id']}").json()
    assert job["status"] == "done", job
    (row,) = job["progress"]["result"]["sources"]
    assert row["source"] == "europepmc" and row["count"] == 10 and len(row["papers"]) == 10
