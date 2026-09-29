"""Worker checks: source connection check and criteria test (Jev only). All HTTP is mocked."""

import uuid

import httpx
import pytest
import sqlalchemy as sa
from eval_helpers import jev_criteria_client, row
from test_web_field_runs import API, DRAFT, new_field

from research_agent.criteria import decide_jev
from research_agent.storage import Store
from research_agent.web.checks import criteria_test, demo_probabilities, source_check
from research_agent.web.db.models import Job, Paper
from research_agent.web.worker import Worker


def europepmc_client(rows, status=200):
    def handler(request):
        if status != 200:
            return httpx.Response(status)
        return httpx.Response(
            200, json={"resultList": {"result": rows[: int(request.url.params["pageSize"])]}}
        )

    return httpx.Client(transport=httpx.MockTransport(handler))


@pytest.fixture
def no_backoff(monkeypatch):
    monkeypatch.setattr("research_agent.connectors.time.sleep", lambda s: None)


def test_source_check_reports_ok_and_timing(tmp_path):
    result = source_check("europepmc", Store(tmp_path), http_client=europepmc_client([row(1), row(2)]))
    assert result["ok"] is True and result["count"] == 1 and result["error"] is None and result["ms"] >= 0


def test_source_check_reports_a_failing_source_by_name_only(tmp_path, no_backoff):
    result = source_check("europepmc", Store(tmp_path), http_client=europepmc_client([], status=503))
    assert result == {"ok": False, "ms": result["ms"], "count": 0, "error": "SourceUnavailable: europepmc"}


def test_a_source_check_job_updates_the_source_row(world, no_backoff):
    settings, factory, sign_in = world
    admin, csrf = sign_in("admin")
    member, member_csrf = sign_in("member")
    assert member.post(f"{API}/sources/europepmc/check", headers=member_csrf).status_code == 403
    assert admin.post(f"{API}/sources/pubmed/check", headers=csrf).status_code == 404
    r = admin.post(f"{API}/sources/europepmc/check", headers=csrf)
    assert r.status_code == 202 and r.json()["kind"] == "source_check" and r.json()["run_id"] is None
    Worker(settings, factory, sleep=lambda s: None, http_client=europepmc_client([row(1)])).tick()
    job = admin.get(f"{API}/jobs/{r.json()['id']}").json()
    assert job["status"] == "done" and job["progress"]["result"]["ok"] is True
    source = admin.get(f"{API}/sources").json()[0]
    assert source["last_check_ok"] is True and source["last_check_ms"] >= 0 and source["last_check_at"]
    assert source["last_check_error"] is None

    r = admin.post(f"{API}/sources/europepmc/check", headers=csrf)
    Worker(settings, factory, sleep=lambda s: None, http_client=europepmc_client([], 500)).tick()
    assert admin.get(f"{API}/jobs/{r.json()['id']}").json()["progress"]["result"]["ok"] is False
    source = admin.get(f"{API}/sources").json()[0]
    assert source["last_check_ok"] is False and source["last_check_error"] == "SourceUnavailable: europepmc"


DOMAIN = {
    "schema": 1,
    "topic": "deep learning CT-FFR",
    "criteria": {
        "include": [{"key": "i1", "text": "Uses deep learning."}],
        "exclude": [{"key": "e1", "text": "Is a review."}],
    },
    "sources": [{"name": "europepmc", "max_results": 100}],
}


def probability(index, key):
    """Paper 1: kept; 2: dropped by i1; 3: dropped by e1; others: to the LLM."""
    table = {1: {"i1": 0.95, "e1": 0.05}, 2: {"i1": 0.01, "e1": 0.05}, 3: {"i1": 0.9, "e1": 0.99}}
    return table.get(index, {}).get(key, 0.5)


def test_criteria_test_screens_at_most_20_papers_with_the_pipelines_rule(tmp_path):
    rows = [row(i) for i in range(1, 26)] + [row(26, abstract="")]
    jev = jev_criteria_client(probability)
    result = criteria_test(
        DOMAIN, Store(tmp_path), api_key="k", jev_client=jev, http_client=europepmc_client(rows)
    )
    papers = {p["source_id"]: p for p in result["papers"]}
    assert len(papers) == 20 and len(jev.calls) == 20
    assert papers["MED:1"]["decision"] == "include" and papers["MED:1"]["decided_by"] is None
    assert (papers["MED:2"]["decision"], papers["MED:2"]["decided_by"]) == ("exclude", "i1")
    assert (papers["MED:3"]["decision"], papers["MED:3"]["decided_by"]) == ("exclude", "e1")
    assert papers["MED:4"]["decision"] == "escalate" and papers["MED:4"]["probabilities"] == {
        "i1": 0.5,
        "e1": 0.5,
    }
    assert papers["MED:1"]["sources"] == ["europepmc"]
    for p in result["papers"]:
        assert (p["decision"], p["decided_by"]) == decide_jev(
            p["probabilities"], result_criteria(result), result["thresholds"]
        )
    assert result["summary"] == {"total": 20, "kept": 1, "dropped": 2, "to_llm": 17, "not_screened": 0}
    assert result["model_version"] == "jev-1.13.0" and result["mode"] == "live"
    assert [c["key"] for c in result["criteria"]] == ["i1", "e1"]


def result_criteria(result):
    return {
        kind: [{"key": c["key"], "text": c["text"]} for c in result["criteria"] if c["kind"] == kind]
        for kind in ("include", "exclude")
    }


def test_papers_without_an_abstract_are_listed_but_not_screened(tmp_path):
    rows = [row(1), row(2, abstract="")]
    jev = jev_criteria_client(probability)
    result = criteria_test(
        DOMAIN, Store(tmp_path), api_key="k", jev_client=jev, http_client=europepmc_client(rows)
    )
    assert [p["decision"] for p in result["papers"]] == ["include", "not_screened"]
    assert len(jev.calls) == 1 and result["summary"]["not_screened"] == 1


def test_live_criteria_test_needs_the_jev_key(tmp_path):
    with pytest.raises(ValueError, match="TYPESAFE_API_KEY is not set in the worker"):
        criteria_test(DOMAIN, Store(tmp_path), api_key=None, http_client=europepmc_client([row(1)]))


def test_demo_probabilities_are_stable_and_offline():
    paper = {"id": "demo:1"}
    assert demo_probabilities(DOMAIN, paper) == demo_probabilities(DOMAIN, paper)
    assert set(demo_probabilities(DOMAIN, paper)) == {"i1", "e1"}


def test_a_draft_is_tested_through_the_api_and_the_worker_without_writing_papers(world):
    settings, factory, sign_in = world
    field_id = new_field(sign_in)
    member, csrf = sign_in("member")
    draft = {k: DRAFT[k] for k in ("name", "topic", "sources", "years", "exclude")}
    draft["include"] = [{"text": "An unsaved criterion."}]
    r = member.post(f"{API}/fields/{field_id}/test", json={"draft": draft, "mode": "demo"}, headers=csrf)
    assert r.status_code == 202 and r.json()["kind"] == "criteria_test"
    with factory() as db:
        payload = db.get(Job, uuid.UUID(r.json()["id"])).payload
    assert (
        payload["version"] is None
        and payload["domain"]["criteria"]["include"][0]["text"] == "An unsaved criterion."
    )
    assert payload["domain"]["field"] is None
    Worker(settings, factory, sleep=lambda s: None).tick()
    job = member.get(f"{API}/jobs/{r.json()['id']}").json()
    assert job["status"] == "done", job["error"]
    result = job["progress"]["result"]
    assert (
        result["mode"] == "demo" and result["model_version"] == "demo-jev" and result["field_id"] == field_id
    )
    assert result["criteria"][0] == {"key": "i1", "kind": "include", "text": "An unsaved criterion."}
    assert result["summary"]["total"] == len(result["papers"]) > 0
    with factory() as db:
        assert db.scalar(sa.select(sa.func.count()).select_from(Paper)) == 0

    saved = member.post(f"{API}/fields/{field_id}/test", json={"mode": "demo"}, headers=csrf)
    with factory() as db:
        assert db.get(Job, uuid.UUID(saved.json()["id"])).payload["version"] == 1


def test_a_live_test_without_the_key_fails_with_a_clear_message(world, monkeypatch):
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    settings, factory, sign_in = world
    field_id = new_field(sign_in)
    member, csrf = sign_in("member")
    r = member.post(f"{API}/fields/{field_id}/test", json={}, headers=csrf)
    Worker(settings, factory, sleep=lambda s: None, http_client=europepmc_client([row(1)])).tick()
    job = member.get(f"{API}/jobs/{r.json()['id']}").json()
    assert (
        job["status"] == "failed" and job["error"] == "ValueError: TYPESAFE_API_KEY is not set in the worker"
    )


def test_criteria_tests_refuse_archived_and_legacy_fields(world):
    _settings, factory, sign_in = world
    from research_agent.web.importer.common import get_or_create_field

    with factory() as db:
        legacy_id = str(get_or_create_field(db, "retrieval augmented generation").id)
        db.commit()
    member, csrf = sign_in("member")
    r = member.post(f"{API}/fields/{legacy_id}/test", json={}, headers=csrf)
    assert r.status_code == 422 and r.json()["code"] == "no_criteria"
    field_id = new_field(sign_in)
    admin, admin_csrf = sign_in("admin")
    admin.post(f"{API}/fields/{field_id}/archive", headers=admin_csrf)
    assert member.post(f"{API}/fields/{field_id}/test", json={}, headers=csrf).status_code == 409
    only_arxiv = new_field(sign_in, sources=["arxiv"])
    r = member.post(f"{API}/fields/{only_arxiv}/test", json={}, headers=csrf)
    assert r.status_code == 422 and r.json()["code"] == "no_enabled_source"


SENTINELS = {
    "ANTHROPIC_API_KEY": "sk-ant-SENTINEL-keycheck-1234567890",
    "OPENAI_API_KEY": "sk-openai-SENTINEL-keycheck-1234567890",
    "TYPESAFE_API_KEY": "ts-SENTINEL-keycheck-1234567890",
}


def provider_client(answers):
    """Mock provider APIs: `answers` maps host -> status (or an exception class to raise)."""
    seen = []

    def handler(request):
        seen.append((request.url.host, dict(request.headers)))
        answer = answers[request.url.host]
        if isinstance(answer, type):
            raise answer("boom", request=request)
        return httpx.Response(answer, json={"data": []})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    client.seen = seen
    return client


def test_check_keys_reports_presence_and_acceptance_per_role():
    from research_agent.web.checks import check_keys

    env = {"RESEARCH_MODEL": "anthropic:model-x", "RESEARCH_REVIEWER_B_MODEL": "openai:gpt-x", **SENTINELS}
    client = provider_client({"api.anthropic.com": 200, "api.openai.com": 401})
    rows = {r["role"]: r for r in check_keys(env, client)}
    assert rows["screen"] == {
        "role": "screen",
        "provider": "anthropic",
        "model": "anthropic:model-x",
        "key_present": True,
        "key_accepted": True,
        "detail": "accepted",
    }
    assert rows["review_b"]["key_accepted"] is False and rows["review_b"]["detail"] == "rejected (401)"
    assert rows["jev"] == {
        "role": "jev",
        "provider": "typesafe",
        "model": "jev-latest",
        "key_present": True,
        "key_accepted": None,
        "detail": "not checked",
    }
    assert sorted(host for host, _ in client.seen) == ["api.anthropic.com", "api.openai.com"]  # once each
    assert dict(client.seen)["api.anthropic.com"]["x-api-key"] == SENTINELS["ANTHROPIC_API_KEY"]
    assert not any(value in str(rows) for value in SENTINELS.values())


def test_missing_keys_and_models_send_nothing():
    from research_agent.web.checks import check_keys

    client = provider_client({})
    rows = {r["role"]: r for r in check_keys({"RESEARCH_MODEL": "anthropic:m"}, client)}
    assert rows["screen"]["key_present"] is False and rows["screen"]["detail"] == "key missing"
    assert rows["jev"]["detail"] == "key missing" and client.seen == []
    rows = {r["role"]: r for r in check_keys({}, client)}
    assert rows["screen"]["model"] is None and rows["screen"]["detail"] == "no model configured"


def test_a_failed_check_is_not_a_rejection():
    from research_agent.web.checks import check_keys

    env = {"RESEARCH_MODEL": "anthropic:m", "ANTHROPIC_API_KEY": SENTINELS["ANTHROPIC_API_KEY"]}
    rows = check_keys(env, provider_client({"api.anthropic.com": httpx.ConnectError}))
    assert {(r["key_accepted"], r["detail"]) for r in rows if r["provider"] == "anthropic"} == {
        (None, "check failed")
    }
    rows = check_keys(env, provider_client({"api.anthropic.com": 529}))
    assert {r["detail"] for r in rows if r["provider"] == "anthropic"} == {"check failed (HTTP 529)"}


def test_the_worker_records_the_key_status_and_never_a_key(world, monkeypatch, caplog):
    settings, factory, sign_in = world
    monkeypatch.setenv("RESEARCH_MODEL", "anthropic:model-x")
    for name, value in SENTINELS.items():
        monkeypatch.setenv(name, value)
    client = provider_client({"api.anthropic.com": 401})
    worker = Worker(settings, factory, sleep=lambda s: None, http_client=client, key_check=True)
    worker.run_forever(stop=lambda: True)  # the check runs once at start, before the first poll
    member, _ = sign_in("member")
    r = member.get(f"{API}/workers/status")
    rows = {row["role"]: row for row in r.json()}
    assert rows["screen"]["key_present"] is True and rows["screen"]["key_accepted"] is False
    assert rows["screen"]["worker_id"] == worker.worker_id and rows["jev"]["detail"] == "not checked"
    with factory() as db:
        stored = str([tuple(row) for row in db.execute(sa.text("select * from worker_status"))])
    for value in SENTINELS.values():
        assert value not in r.text and value not in stored and value not in caplog.text


def test_the_worker_survives_a_broken_key_check(world, monkeypatch, caplog):
    settings, factory, _ = world
    sentinel = SENTINELS["ANTHROPIC_API_KEY"]
    monkeypatch.setenv("ANTHROPIC_API_KEY", sentinel)

    def explode(env, client):
        raise RuntimeError(f"bad {sentinel}")

    monkeypatch.setattr("research_agent.web.worker.check_keys", explode)
    assert Worker(settings, factory, key_check=True).check_keys() is None
    assert "key check failed" in caplog.text and sentinel not in caplog.text
