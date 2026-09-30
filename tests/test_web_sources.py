"""Sources from the registry: metadata, key status from the worker, key-gated enabling, checks for every source."""

import json
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
import sqlalchemy as sa

from research_agent.schemas import FULLTEXT_SOURCES, SEARCH_SOURCES
from research_agent.sources import REGISTRY
from research_agent.storage import Store
from research_agent.web.checks import check_source_keys, source_check
from research_agent.web.db.models import SourceRow
from research_agent.web.worker import Worker

API = "/api/v1"


def by_name(client):
    return {r["name"]: r for r in client.get(f"{API}/sources").json()}


def test_sources_carry_registry_metadata_and_the_key_status(sign_in, db):
    viewer, _ = sign_in("viewer")
    rows = by_name(viewer)
    ieee = rows["ieee"]
    assert ieee["label"] == "IEEE Xplore" and ieee["group"] == "publishers" and ieee["auth"] == "required"
    assert ieee["env"] == ["IEEE_API_KEY"] and "search" in ieee["capabilities"] and ieee["covers"]
    assert ieee["key_present"] is False and ieee["key_accepted"] is None and ieee["key_checked_at"] is None
    assert rows["scopus"]["env"] == ["ELSEVIER_API_KEY", "ELSEVIER_INSTTOKEN"]
    assert rows["unpaywall"]["capabilities"] == ["fulltext"]
    pubmed = rows["pubmed"]
    assert pubmed["rps"] == REGISTRY["pubmed"].rps == pubmed["rps_in_use"] == 3
    row = db.get(SourceRow, "pubmed")
    row.key_present, row.key_accepted, row.key_detail = True, True, "accepted"
    row.key_checked_at = datetime.now(UTC)
    db.commit()
    pubmed = by_name(viewer)["pubmed"]
    assert pubmed["key_present"] is True and pubmed["key_accepted"] is True and pubmed["key_checked_at"]
    assert pubmed["rps_in_use"] == REGISTRY["pubmed"].rps_keyed == 10


def test_enabling_a_source_whose_required_key_is_missing_is_refused(sign_in, db):
    admin, csrf = sign_in("admin")
    r = admin.patch(f"{API}/sources/ieee", json={"enabled": True}, headers=csrf)
    assert r.status_code == 422 and r.json()["code"] == "key_missing"
    assert "Set IEEE_API_KEY in the worker environment first" in r.json()["message"]
    assert admin.patch(f"{API}/sources/ieee", json={"max_results": 50}, headers=csrf).status_code == 200
    for name in ("pubmed", "crossref", "semantic_scholar"):  # optional or no key
        assert admin.patch(f"{API}/sources/{name}", json={"enabled": True}, headers=csrf).status_code == 200
    row = db.get(SourceRow, "ieee")
    row.key_present = True
    db.commit()
    r = admin.patch(f"{API}/sources/ieee", json={"enabled": True}, headers=csrf)
    assert r.status_code == 200 and r.json()["enabled"] is True
    assert (
        admin.patch(f"{API}/sources/ieee", json={"enabled": False}, headers=csrf).json()["enabled"] is False
    )


def test_a_source_without_search_has_no_connection_test(sign_in):
    admin, csrf = sign_in("admin")
    for name in ("unpaywall", "sciencedirect"):
        r = admin.post(f"{API}/sources/{name}/check", headers=csrf)
        assert r.status_code == 422 and r.json()["code"] == "not_searchable"


# ---- worker: per-source key status and connection checks (all HTTP mocked, sentinel keys) -----------------


FIXTURES = Path(__file__).parent / "fixtures"
KEYS = {
    "CORE_API_KEY": "core-SENTINEL-4f1c9a7e",
    "IEEE_API_KEY": "ieee-SENTINEL-8b2d5e10",
    "ELSEVIER_API_KEY": "els-SENTINEL-77aa01",
}


@pytest.fixture
def no_backoff(monkeypatch):
    monkeypatch.setattr("research_agent.connectors.time.sleep", lambda s: None)


def mock(answers):
    """host -> (status, json body); unknown hosts fail the test loudly."""
    seen = []

    def handler(request):
        seen.append(str(request.url))
        status, body = answers[request.url.host]
        return httpx.Response(status, json=body)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    client.seen = seen
    return client


def core_ok():
    return 200, json.loads((FIXTURES / "core_search.json").read_text())


def test_source_key_rows_say_present_accepted_or_missing_and_never_a_value(tmp_path, no_backoff):
    env = {
        "CORE_API_KEY": KEYS["CORE_API_KEY"],
        "IEEE_API_KEY": KEYS["IEEE_API_KEY"],
        "ELSEVIER_API_KEY": KEYS["ELSEVIER_API_KEY"],
    }  # no ELSEVIER_INSTTOKEN
    with pytest.MonkeyPatch.context() as mp:
        for name, value in env.items():
            mp.setenv(name, value)
        client = mock({"api.core.ac.uk": core_ok(), "ieeexploreapi.ieee.org": (403, {"error": "no"})})
        rows = {r["name"]: r for r in check_source_keys(env, Store(tmp_path), http_client=client)}
    assert set(rows) == set(REGISTRY)
    assert rows["europepmc"] == {
        "name": "europepmc",
        "key_present": True,
        "key_accepted": None,
        "detail": "no key needed",
    }
    assert rows["core"]["key_present"] is True and rows["core"]["key_accepted"] is True
    assert rows["ieee"]["key_accepted"] is None and rows["ieee"]["detail"] == "check failed"
    assert rows["scopus"]["key_present"] is False and rows["scopus"]["detail"] == "ELSEVIER_INSTTOKEN not set"
    assert rows["springer"]["detail"] == "SPRINGER_API_KEY not set"
    assert rows["pubmed"]["key_present"] is False and "lower rate limit" in rows["pubmed"]["detail"]
    assert all("api.core.ac.uk" in u or "ieee" in u for u in client.seen)  # nothing else was called
    assert not any(v in str(rows) for v in KEYS.values())


def test_the_worker_records_source_key_status_and_never_a_key(world, monkeypatch, caplog, no_backoff):
    settings, factory, sign_in = world
    monkeypatch.setenv("CORE_API_KEY", KEYS["CORE_API_KEY"])
    client = mock({"api.core.ac.uk": core_ok()})
    worker = Worker(settings, factory, sleep=lambda s: None, http_client=client, key_check=True)
    worker.run_forever(stop=lambda: True)
    member, _ = sign_in("member")
    r = member.get("/api/v1/sources")
    rows = {row["name"]: row for row in r.json()}
    assert rows["core"]["key_present"] is True and rows["core"]["key_accepted"] is True
    assert rows["core"]["key_detail"] == "accepted" and rows["core"]["key_checked_at"]
    assert rows["ieee"]["key_present"] is False and rows["europepmc"]["key_present"] is True
    with factory() as db:
        stored = str([tuple(row) for row in db.execute(sa.text("select * from sources"))])
    assert KEYS["CORE_API_KEY"] not in r.text + stored + caplog.text


def test_a_broken_source_key_check_does_not_stop_the_worker(world, monkeypatch, caplog):
    settings, factory, _ = world
    monkeypatch.setenv("CORE_API_KEY", KEYS["CORE_API_KEY"])

    def explode(*args, **kwargs):
        raise RuntimeError(f"bad {KEYS['CORE_API_KEY']}")

    monkeypatch.setattr("research_agent.web.worker.check_source_keys", explode)
    assert Worker(settings, factory, key_check=True).check_source_keys() is None
    assert "source key check failed" in caplog.text and KEYS["CORE_API_KEY"] not in caplog.text


def test_source_check_works_for_a_new_source_and_names_a_missing_key(tmp_path, monkeypatch, no_backoff):
    monkeypatch.delenv("CORE_API_KEY", raising=False)
    result = source_check("core", Store(tmp_path), http_client=mock({}))
    assert result["ok"] is False and result["error"] == "core: set CORE_API_KEY in the worker environment"
    monkeypatch.setenv("CORE_API_KEY", KEYS["CORE_API_KEY"])
    result = source_check("core", Store(tmp_path), http_client=mock({"api.core.ac.uk": core_ok()}))
    assert result["ok"] is True and result["count"] == 1


def test_a_source_check_job_runs_for_a_new_source(world, monkeypatch, no_backoff):
    settings, factory, sign_in = world
    monkeypatch.setenv("CORE_API_KEY", KEYS["CORE_API_KEY"])
    admin, csrf = sign_in("admin")
    r = admin.post("/api/v1/sources/core/check", headers=csrf)
    assert r.status_code == 202
    Worker(settings, factory, sleep=lambda s: None, http_client=mock({"api.core.ac.uk": core_ok()})).tick()
    assert admin.get(f"/api/v1/jobs/{r.json()['id']}").json()["progress"]["result"]["ok"] is True
    assert by_name(admin)["core"]["last_check_ok"] is True


def test_the_elsevier_institution_token_is_redacted(monkeypatch):
    from research_agent.web.runner import redact

    monkeypatch.setenv("ELSEVIER_INSTTOKEN", "inst-SENTINEL-0123456789")
    assert redact("x inst-SENTINEL-0123456789 y") == "x *** y"


# ---- field drafts and review settings accept the registry's names ------------------------------------------


DRAFT = {
    "name": "Every source",
    "topic": "deep learning for coronary CT angiography",
    "include": [{"text": "Uses deep learning."}],
    "exclude": [],
    "years": {"from": 2018, "to": None},
}


def test_a_field_may_search_every_source_with_per_source_overrides(sign_in):
    member, csrf = sign_in("member")
    body = DRAFT | {
        "sources": list(SEARCH_SOURCES),
        "keywords": {"all": ["coronary"], "any": ["deep learning"], "none": []},
        "query_override": {"pubmed": "coronary[tiab]", "scopus": "TITLE-ABS-KEY(coronary)"},
    }
    r = member.post(f"{API}/fields", json=body, headers=csrf)
    assert r.status_code == 201, r.text
    current = r.json()["current"]
    assert current["sources"] == list(SEARCH_SOURCES)
    assert current["query_override"]["pubmed"] == "coronary[tiab]"
    bad = body | {"query_override": {"openalex": "a, b"}}
    assert member.post(f"{API}/fields", json=bad, headers=csrf).status_code == 422
    assert member.post(f"{API}/fields", json=body | {"sources": ["scholar"]}, headers=csrf).status_code == 422


def test_review_settings_take_every_resolver_in_any_order(sign_in):
    admin, csrf = sign_in("admin")
    current = admin.get(f"{API}/settings/review").json()["current"]
    keys = ("models", "screening", "fulltext", "default_panel", "editor")
    order = list(reversed(FULLTEXT_SOURCES))
    body = {k: current[k] for k in keys} | {"base_version": current["version"], "note": "order"}
    body["fulltext"] = {**current["fulltext"], "sources": order, "contact": "team@example.org"}
    r = admin.post(f"{API}/settings/review", json=body, headers=csrf)
    assert r.status_code == 201, r.text
    assert r.json()["current"]["fulltext"]["sources"] == order
    body["base_version"] = r.json()["current"]["version"]
    body["fulltext"] = {**body["fulltext"], "sources": ["core", "core"]}
    assert admin.post(f"{API}/settings/review", json=body, headers=csrf).status_code == 422
