"""Settings → My keys / My models / My usage, and the worker's use of a user's keys. No network: every model
call and HTTP check is stubbed."""

import json
import logging
from dataclasses import replace
from pathlib import Path

import pytest
import sqlalchemy as sa
from conftest import TEST_SECRETS_KEY
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker
from test_web_worker import FakeProcess

from research_agent.agents import Evaluator, cache_key
from research_agent.connectors import digest
from research_agent.schemas import Screen
from research_agent.storage import Store
from research_agent.web import keyring, usersecrets
from research_agent.web.auth import create_user
from research_agent.web.db.models import Job, Run, UserSecret, WorkerStatus
from research_agent.web.importer.common import get_or_create_field
from research_agent.web.jobs import enqueue
from research_agent.web.runner import child_environment, clear_job_secrets, redact
from research_agent.web.settings import load_settings
from research_agent.web.worker import Worker

API = "/api/v1"
SENTINEL = "sk-ant-SENTINEL-user-key-7f3a9c"
TOPIC = "retrieval augmented generation"


def test_a_key_is_encrypted_and_only_the_worker_side_decrypts_it(sign_in, db, settings, users):
    member, csrf = sign_in("member")
    r = member.put(f"{API}/me/keys/anthropic", json={"key": SENTINEL}, headers=csrf)
    assert r.status_code == 200
    assert r.json()["saved"] and r.json()["last4"] == SENTINEL[-4:] and SENTINEL not in r.text
    row = db.scalar(select(UserSecret).where(UserSecret.user_id == users["member"].id))
    assert SENTINEL not in row.ciphertext and row.last4 == SENTINEL[-4:]
    try:
        assert keyring.decrypt_keys(db, settings, users["member"].id) == {"anthropic": SENTINEL}
    finally:
        clear_job_secrets()
    # the API side never imports the decrypting module
    import research_agent.web.usersecrets as api_side
    from research_agent.web.api.routers import me

    assert "keyring" not in vars(me) and "Fernet(" in Path(api_side.__file__).read_text()
    assert ".decrypt(" not in Path(api_side.__file__).read_text()


def test_a_key_never_appears_in_a_response_or_a_log(sign_in, caplog):
    caplog.set_level(logging.DEBUG)
    member, csrf = sign_in("member")
    seen = [member.put(f"{API}/me/keys/openai", json={"key": SENTINEL}, headers=csrf).text]
    seen.append(member.get(f"{API}/me/keys").text)
    seen.append(member.put(f"{API}/me/keys/openai", json={"key": SENTINEL + " x"}, headers=csrf).text)
    seen.append(member.put(f"{API}/me/keys/openai", json={"key": "x" * 2000}, headers=csrf).text)
    seen.append(member.get(f"{API}/me/models").text)
    seen.append(member.post(f"{API}/me/keys/openai/check", headers=csrf).text)
    assert all(SENTINEL not in text for text in seen)
    assert SENTINEL not in caplog.text
    keys = {k["provider"]: k for k in member.get(f"{API}/me/keys").json()}
    assert set(keys) == set(usersecrets.PROVIDERS) and keys["openai"]["last4"] == SENTINEL[-4:]
    assert member.delete(f"{API}/me/keys/openai", headers=csrf).status_code == 204
    assert member.delete(f"{API}/me/keys/openai", headers=csrf).status_code == 404
    assert not {k["provider"]: k for k in member.get(f"{API}/me/keys").json()}["openai"]["saved"]


def test_keys_cannot_be_saved_without_the_master_key(app, sign_in, settings):
    app.state.settings = replace(settings, secrets_key=None)
    member, csrf = sign_in("member")
    r = member.put(f"{API}/me/keys/anthropic", json={"key": SENTINEL}, headers=csrf)
    assert r.status_code == 503 and r.json()["code"] == "secrets_unavailable"


def test_the_worker_redacts_a_users_key_and_forgets_it_after_the_job(db, settings, users):
    usersecrets.save_secret(db, settings, users["member"].id, "xai", SENTINEL)
    db.flush()
    keyring.decrypt_keys(db, settings, users["member"].id)
    assert redact(f"boom {SENTINEL}") == "boom ***"
    clear_job_secrets()
    assert SENTINEL in redact(f"boom {SENTINEL}")


# --- preflight -------------------------------------------------------------------------------------------------


def _field(member, csrf):
    draft = {
        "name": "Keys field",
        "topic": TOPIC,
        "include": [{"text": "The study uses machine learning."}],
        "exclude": [],
        "sources": ["europepmc"],
        "years": {"from": 2018, "to": None},
    }
    r = member.post(f"{API}/fields", json=draft, headers=csrf)
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _worker_model(db, model="anthropic:claude-sonnet-5"):
    for role in ("plan", "screen", "screen_criteria", "extract", "review_a", "adjudicate"):
        db.merge(WorkerStatus(role=role, provider=model.split(":")[0], model=model, key_present=False))
    db.commit()


def test_a_live_run_is_blocked_until_the_user_adds_the_needed_key(sign_in, db, settings, users):
    _worker_model(db)
    member, csrf = sign_in("member")
    field = _field(member, csrf)
    r = member.post(f"{API}/runs", json={"field_id": field, "max_papers": 3, "mode": "live"}, headers=csrf)
    assert r.status_code == 422 and r.json()["code"] == "key_missing", r.text
    assert r.json()["message"] == "Add your Anthropic (Claude) key in Settings → My keys"
    assert db.scalar(select(sa.func.count()).select_from(Job)) == 0
    demo = member.post(f"{API}/runs", json={"field_id": field, "max_papers": 3, "mode": "demo"}, headers=csrf)
    assert demo.status_code == 202  # demo runs need no key
    member.put(f"{API}/me/keys/anthropic", json={"key": SENTINEL}, headers=csrf)
    r = member.post(f"{API}/runs", json={"field_id": field, "max_papers": 3, "mode": "live"}, headers=csrf)
    assert r.status_code == 202 and SENTINEL not in json.dumps(db.get(Job, r.json()["job"]["id"]).payload)


def test_development_mode_lets_the_workers_own_keys_stand_in(app, sign_in, db, settings):
    _worker_model(db)
    db.execute(sa.update(WorkerStatus).values(key_present=True))
    db.commit()
    member, csrf = sign_in("member")
    field = _field(member, csrf)
    body = {"field_id": field, "max_papers": 3, "mode": "live"}
    assert member.post(f"{API}/runs", json=body, headers=csrf).status_code == 422  # not dev: no fallback
    app.state.settings = replace(settings, dev_mode=True)
    assert member.post(f"{API}/runs", json=body, headers=csrf).status_code == 202


# --- the worker: env injection ---------------------------------------------------------------------------------


@pytest.fixture
def worker_env(fresh_db_url, tmp_path):
    def make(dev=False):
        return load_settings(
            {
                "RESEARCH_WEB_DATABASE_URL": fresh_db_url,
                "RESEARCH_RUNS_DIR": str(tmp_path / "runs"),
                "RESEARCH_EVALS_DIR": str(tmp_path / "evals"),
                "RESEARCH_GOLD_DIR": str(tmp_path / "gold"),
                "RESEARCH_WEB_PROGRESS_POLL_SECONDS": "0.01",
                "RESEARCH_SECRETS_KEY": TEST_SECRETS_KEY,
                "RESEARCH_WEB_DEV_MODE": "true" if dev else "false",
            }
        )

    engine = sa.create_engine(fresh_db_url)
    yield make, sessionmaker(engine, expire_on_commit=False)
    engine.dispose()


REVIEW = {"models": {"screen": "anthropic:claude-sonnet-5"}, "panel": [], "editor": {}}


def _queue_live(factory, settings, key=None):
    with factory() as db:
        user = create_user(
            db, email="k@example.org", name="K", role="member", password="correct horse battery"
        )
        if key:
            usersecrets.save_secret(db, settings, user.id, "anthropic", key)
        field = get_or_create_field(db, TOPIC, user.id)
        run = Run(field_id=field.id, kind="research", status="queued", manifest={}, created_by=user.id)
        db.add(run)
        db.flush()
        run.folder = str(settings.runs_dir / run.id.hex)
        payload = {"run_id": str(run.id), "field_id": str(field.id), "topic": TOPIC, "max_papers": 3}
        payload |= {"mode": "live", "resume": False, "review": REVIEW}
        job, _ = enqueue(db, "research", payload, user.id)
        db.commit()
        return job.id, run.id, user.id


def test_the_child_gets_the_users_key_and_namespace_through_its_environment_only(worker_env, monkeypatch):
    make, factory = worker_env
    settings = make()
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-company-key-must-not-leak")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-company-openai-must-not-leak")
    job_id, run_id, user_id = _queue_live(factory, settings, key=SENTINEL)
    seen = {}

    def spawn(spec, env, log):
        seen.update(env)
        Path(spec.run_dir).mkdir(parents=True, exist_ok=True)
        (Path(spec.run_dir) / "progress.json").write_text(
            json.dumps({"status": "failed", "error_type": "AuthError", "message": f"bad key {SENTINEL}"})
        )
        return FakeProcess(1)

    Worker(settings, factory, spawn=spawn, sleep=lambda s: None).tick()
    assert seen["ANTHROPIC_API_KEY"] == SENTINEL and "OPENAI_API_KEY" not in seen
    assert seen["RESEARCH_CACHE_NAMESPACE"] == str(user_id)
    with factory() as db:
        job, run = db.get(Job, job_id), db.get(Run, run_id)
        stored = json.dumps([job.payload, job.progress, job.error, run.error, run.manifest])
        assert SENTINEL not in stored and "***" in job.error
    run_dir = settings.runs_dir / run_id.hex
    assert all(SENTINEL not in p.read_text() for p in run_dir.rglob("*.json") if p.name != "progress.json")


def test_the_worker_blocks_a_run_whose_user_has_no_key(worker_env, monkeypatch):
    make, factory = worker_env
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-company-key-must-not-leak")
    settings = make()
    job_id, _run_id, _ = _queue_live(factory, settings)
    spawned = []
    Worker(settings, factory, spawn=lambda *a: spawned.append(a), sleep=lambda s: None).tick()
    with factory() as db:
        assert db.get(Job, job_id).error == "Add your Anthropic (Claude) key in Settings → My keys"
    assert not spawned


def test_development_mode_keeps_the_env_keys_for_the_child(worker_env, monkeypatch):
    make, factory = worker_env
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-dev-env-key-1234")
    settings = make(dev=True)
    _queue_live(factory, settings)
    seen = {}

    def spawn(spec, env, log):
        seen.update(env)
        return FakeProcess(1)

    Worker(settings, factory, spawn=spawn, sleep=lambda s: None).tick()
    assert seen["ANTHROPIC_API_KEY"] == "sk-dev-env-key-1234"


def test_job_environment_drops_provider_keys_outside_development_mode(monkeypatch):
    monkeypatch.setenv("GOOGLE_API_KEY", "company-google")
    base = child_environment()
    assert "GOOGLE_API_KEY" not in keyring.job_environment(base, {}, None, dev_mode=False)
    assert keyring.job_environment(base, {}, None, dev_mode=True)["GOOGLE_API_KEY"] == "company-google"
    env = keyring.job_environment(base, {"google_genai": "mine"}, "u1", dev_mode=True)
    assert env["GOOGLE_API_KEY"] == "mine" and env["RESEARCH_CACHE_NAMESPACE"] == "u1"


def test_a_key_test_runs_in_the_worker_and_records_the_result(worker_env):
    import httpx

    make, factory = worker_env
    settings = make()
    calls = []

    def handler(request):
        calls.append(request.headers.get("authorization"))
        return httpx.Response(401)

    with factory() as db:
        user = create_user(
            db, email="t@example.org", name="T", role="member", password="correct horse battery"
        )
        usersecrets.save_secret(db, settings, user.id, "openai", SENTINEL)
        job, _ = enqueue(db, "secret_check", {"provider": "openai"}, user.id)
        db.commit()
        job_id, user_id = job.id, user.id
    client = httpx.Client(transport=httpx.MockTransport(handler))
    Worker(settings, factory, http_client=client, sleep=lambda s: None).tick()
    assert calls == [f"Bearer {SENTINEL}"]
    with factory() as db:
        job = db.get(Job, job_id)
        row = db.scalar(select(UserSecret).where(UserSecret.user_id == user_id))
        assert (
            job.status == "done"
            and job.progress["result"]["ok"] is False
            and SENTINEL not in json.dumps(job.progress)
        )
        assert row.check_ok is False and row.checked_at is not None


# --- cache namespaces ------------------------------------------------------------------------------------------


def test_the_cache_key_includes_the_user_and_the_legacy_key_is_unchanged():
    inputs = {"payload": {"a": 1}}
    legacy = digest({"model": "m", "role": "screen", "version": "v", "inputs": inputs})
    assert cache_key("m", "screen", "v", inputs) == legacy
    assert cache_key("m", "screen", "v", inputs, "user-1") not in (
        legacy,
        cache_key("m", "screen", "v", inputs, "u2"),
    )


def test_two_users_never_share_a_cached_answer(tmp_path):
    store = Store(tmp_path)
    payload = {"topic": "t", "paper": {"id": "p", "title": "x", "abstract": "y"}}
    Evaluator(store, "demo", namespace="u1").ask("screen", Screen, payload)
    offline = Evaluator(store, "demo", offline=True, namespace="u2")
    with pytest.raises(Exception, match="not in cache"):
        offline.ask("screen", Screen, payload)
    assert Evaluator(store, "demo", offline=True, namespace="u1").ask("screen", Screen, payload)


def _call_keys_match(run_dir, namespace):
    import sqlite3

    with sqlite3.connect(Path(run_dir) / "research.sqlite") as connection:
        rows = connection.execute("select key, role, model, prompt_version, input from calls").fetchall()
    assert rows
    return all(cache_key(m, role, v, json.loads(i), namespace) == k for k, role, m, v, i in rows)


def test_new_runs_use_the_users_namespace_and_old_runs_resume_from_the_legacy_one(tmp_path, monkeypatch):
    from research_agent.runner import run_research
    from research_agent.schemas import Contract

    contract = Contract(topic=TOPIC, mode="demo", max_papers=3)
    monkeypatch.setenv("RESEARCH_CACHE_NAMESPACE", "user-42")
    run_research(tmp_path / "new", contract=contract)
    manifest = json.loads((tmp_path / "new" / "manifest.json").read_text())
    assert manifest["cache_namespace"] == "user-42" and _call_keys_match(tmp_path / "new", "user-42")
    monkeypatch.delenv("RESEARCH_CACHE_NAMESPACE")
    run_research(tmp_path / "old", contract=contract, stop_after="screen")  # an old (legacy) run, unfinished
    assert "cache_namespace" not in json.loads((tmp_path / "old" / "manifest.json").read_text())
    monkeypatch.setenv("RESEARCH_CACHE_NAMESPACE", "user-42")  # the web worker resumes it for a user
    run_research(tmp_path / "old", resume=True)
    assert "cache_namespace" not in json.loads((tmp_path / "old" / "manifest.json").read_text())
    assert _call_keys_match(tmp_path / "old", None)


# --- providers -------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("model", "provider", "argument"),
    [
        ("openai:gpt-5", "openai", "api_key"),
        ("xai:grok-4", "xai", "api_key"),
        ("google_genai:gemini-2.5-pro", "google_genai", "google_api_key"),
    ],
)
def test_openai_and_xai_go_through_init_chat_model_with_the_users_key(
    tmp_path, monkeypatch, model, provider, argument
):
    from langchain import chat_models

    seen = {}

    class Fake:
        def with_structured_output(self, schema, method):
            seen["method"] = method
            return self

        def invoke(self, messages):
            return {"decision": "include", "reason": "ok"}

    def fake_init(model_id, **kwargs):
        seen["model"], seen["kwargs"] = model_id, kwargs
        return Fake()

    monkeypatch.setattr(chat_models, "init_chat_model", fake_init)
    evaluator = Evaluator(
        Store(tmp_path), "live", {"screen": model}, namespace="u", api_keys={provider: "k-1"}
    )
    evaluator.ask("screen", Screen, {"topic": "t", "paper": {"id": "p", "title": "x", "abstract": "y"}})
    assert seen["model"] == model and seen["kwargs"][argument] == "k-1" and seen["method"] == "json_schema"


def test_new_providers_are_named_and_priced_as_estimates():
    from research_agent.web.evals import price
    from research_agent.web.runs import provider_of

    assert provider_of("openai:gpt-5") == "openai" and provider_of("xai:grok-4") == "xai"
    assert provider_of("gpt-5-mini") == "openai" and provider_of("grok-4") == "xai"
    assert price("openai:gpt-5", 4000, 1000) is not None and price("xai:grok-4-fast", 4000, 0) is not None


# --- models per user -------------------------------------------------------------------------------------------


def test_a_model_can_be_chosen_only_from_a_provider_with_a_key_and_is_frozen_into_the_run(sign_in, db):
    member, csrf = sign_in("member")
    state = member.get(f"{API}/me/models").json()
    roles = {r["role"]: r for r in state["roles"]}
    assert {"plan", "screen", "extract", "editor", "reader"} <= set(roles)
    assert any(r.startswith("review:") for r in roles)
    assert not any(o["available"] for o in state["options"])
    put = lambda models: member.put(f"{API}/me/models", json={"models": models}, headers=csrf)
    r = put({"screen": "openai:gpt-5"})
    assert r.status_code == 422 and r.json()["message"] == "Add your OpenAI (GPT) key in Settings → My keys"
    assert put({"nope": "openai:gpt-5"}).status_code == 422
    member.put(f"{API}/me/keys/openai", json={"key": SENTINEL}, headers=csrf)
    assert put({"screen": "openai:made-up"}).status_code == 422
    reviewer = next(r for r in roles if r.startswith("review:"))
    r = put({"screen": "openai:gpt-5", reviewer: "openai:gpt-5-mini", "editor": "openai:gpt-5", "plan": None})
    assert r.status_code == 200, r.text
    mine = {x["role"]: x for x in r.json()["roles"]}
    assert mine["screen"]["effective"] == "openai:gpt-5" and mine["plan"]["choice"] is None
    field = _field(member, csrf)
    run = member.post(f"{API}/runs", json={"field_id": field, "max_papers": 3, "mode": "demo"}, headers=csrf)
    review = db.get(Run, run.json()["run_id"]).manifest["review_request"]
    assert review["models"]["screen"] == "openai:gpt-5" and review["editor"]["model"] == "openai:gpt-5"
    assert (
        next(p for p in review["panel"] if f"review:{p['key']}" == reviewer)["model"] == "openai:gpt-5-mini"
    )


# --- usage -----------------------------------------------------------------------------------------------------


def test_my_usage_sums_a_users_calls_and_cost_per_month(sign_in, db, settings, users):
    from datetime import UTC, datetime

    field = get_or_create_field(db, TOPIC, users["member"].id)
    for month, model in (
        ("2026-09-10", "anthropic:claude-sonnet-5"),
        ("2026-10-02", "xai:grok-4"),
        ("2026-10-20", "made-up"),
    ):
        run = Run(
            field_id=field.id, kind="research", status="done", manifest={}, created_by=users["member"].id
        )
        run.created_at = datetime.fromisoformat(month).replace(tzinfo=UTC)
        db.add(run)
        db.flush()
        folder = settings.runs_dir / run.id.hex
        run.folder = str(folder)
        store = Store(folder)
        for n in range(2):
            store.record(f"{run.id}-{n}", "screen", model, "v", {"x": "a" * 4000}, {"y": "b" * 400})
    other = Run(field_id=field.id, kind="research", status="done", manifest={}, created_by=users["admin"].id)
    db.add(other)
    db.commit()
    member, _ = sign_in("member")
    usage = member.get(f"{API}/me/usage").json()
    assert usage["estimate"] is True and [m["month"] for m in usage["months"]] == ["2026-10", "2026-09"]
    october, september = usage["months"]
    assert october["runs"] == 2 and october["calls"] == 4 and october["unpriced_models"] == ["made-up"]
    assert september["calls"] == 2 and september["cost_usd"] > 0


# --- signup ----------------------------------------------------------------------------------------------------


def _domains(sign_in, domains):
    admin, csrf = sign_in("admin")
    r = admin.patch(f"{API}/settings", json={"signup_domains": domains}, headers=csrf)
    assert r.status_code == 200, r.text
    return r.json()["signup_domains"]


def test_signup_is_off_until_an_admin_lists_domains(client, sign_in):
    assert client.get(f"{API}/auth/signup").json() == {"open": False}
    body = {"email": "new@company.example", "name": "New", "password": "a long enough password"}
    r = client.post(f"{API}/auth/signup", json=body)
    assert r.status_code == 403 and r.json()["code"] == "signup_closed"
    assert _domains(sign_in, ["@Company.Example", "company.example"]) == ["company.example"]
    assert client.get(f"{API}/auth/signup").json() == {"open": True}
    admin, csrf = sign_in("admin")
    assert (
        admin.patch(f"{API}/settings", json={"signup_domains": ["not a domain"]}, headers=csrf).status_code
        == 422
    )


def test_signup_creates_a_member_and_answers_the_same_for_a_taken_email(app, client, sign_in, db):
    from research_agent.web.db.models import User

    _domains(sign_in, ["company.example"])
    body = {"email": "New@Company.example", "name": " New Person ", "password": "a long enough password"}
    first = client.post(f"{API}/auth/signup", json=body)
    again = client.post(f"{API}/auth/signup", json={**body, "password": "another long password"})
    assert first.status_code == again.status_code == 202 and first.json() == again.json()
    user = db.scalar(select(User).where(User.email == "new@company.example"))
    assert user.role == "member" and user.active and user.name == "New Person"
    login = client.post(
        f"{API}/auth/login", json={"email": "new@company.example", "password": body["password"]}
    )
    assert login.status_code == 200
    wrong = client.post(f"{API}/auth/signup", json={**body, "email": "x@other.example"})
    assert (
        wrong.status_code == 422
        and wrong.json()["message"] == "Use your work email address to create an account."
    )
    weak = client.post(f"{API}/auth/signup", json={**body, "email": "y@company.example", "password": "short"})
    assert weak.status_code == 422 and "12 characters" in weak.json()["message"]


def test_signup_and_login_are_rate_limited_per_ip(app, client, sign_in):
    _domains(sign_in, ["company.example"])
    statuses = [
        client.post(
            f"{API}/auth/signup",
            json={"email": f"u{n}@company.example", "name": "U", "password": "a long enough password"},
        ).status_code
        for n in range(7)
    ]
    assert statuses[:5] == [202] * 5 and statuses[5:] == [429, 429]
    failures = [
        client.post(
            f"{API}/auth/login", json={"email": f"nobody{n}@x.example", "password": "wrong"}
        ).status_code
        for n in range(31)
    ]
    assert failures[:30] == [401] * 30 and failures[30] == 429
