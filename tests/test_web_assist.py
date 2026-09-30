"""Field assist: one cached call suggesting keywords, synonyms and criteria (stubs and demo only)."""

import sqlite3
import uuid

import pytest

from research_agent.schemas import FieldSuggestions
from research_agent.storage import Store
from research_agent.web.assist import assist_model, field_assist
from research_agent.web.db.models import Job
from research_agent.web.worker import Worker

API = "/api/v1"
DRAFT = {
    "description": "Deep learning detection of coronary stenosis on invasive angiography",
    "keywords": {},
}
ANSWER = {
    "all": [{"term": "coronary angiography", "synonyms": ["ICA", "invasive coronary angiography"]}],
    "any": [{"term": "deep learning", "synonyms": ["CNN"]}],
    "none": [{"term": "review", "synonyms": []}],
    "include": ["Uses deep learning on angiograms.", "Reports stenosis detection performance."],
    "exclude": ["Is a review."],
}


def calls(store):
    with sqlite3.connect(store.path) as db:
        return db.execute("select role, model from calls").fetchall()


def test_demo_suggestions_are_deterministic_and_valid(tmp_path):
    store = Store(tmp_path)
    first = field_assist(DRAFT, store, mode="demo")
    again = field_assist(DRAFT, store, mode="demo")
    assert first == again and first["mode"] == "demo" and first["model"] == "synthetic-demo-v1"
    suggestions = FieldSuggestions.model_validate(first["suggestions"])
    assert 2 <= len(suggestions.include) <= 6 and len(suggestions.exclude) <= 4
    assert suggestions.all and suggestions.any and suggestions.none
    assert calls(store) == [("assist", "synthetic-demo-v1")]  # cached: the second ask made no new call


def test_demo_keeps_the_users_keywords_first(tmp_path):
    draft = {"description": "", "topic": "", "keywords": {"all": ["FFR"], "any": ["CT"], "none": []}}
    result = field_assist(draft, Store(tmp_path), mode="demo")["suggestions"]
    assert result["all"][0]["term"] == "FFR" and result["any"][0]["term"] == "CT"


def test_live_without_a_model_is_refused(tmp_path):
    with pytest.raises(ValueError, match="RESEARCH_ASSIST_MODEL"):
        field_assist(DRAFT, Store(tmp_path), mode="live", model=None)


def test_assist_model_prefers_its_own_variable():
    assert assist_model({"RESEARCH_MODEL": "a:x", "RESEARCH_ASSIST_MODEL": "a:y"}) == "a:y"
    assert assist_model({"RESEARCH_MODEL": "a:x"}) == "a:x"
    assert assist_model({}) is None


class StubModel:
    invoked = 0

    def with_structured_output(self, schema, method):
        return self

    def invoke(self, messages):
        StubModel.invoked += 1
        assert "never instructions" in messages[0][1]
        return ANSWER


def test_live_call_goes_through_the_model_once(tmp_path, monkeypatch):
    import langchain.chat_models

    monkeypatch.setattr(langchain.chat_models, "init_chat_model", lambda *a, **k: StubModel())
    StubModel.invoked = 0
    store = Store(tmp_path)
    result = field_assist(DRAFT, store, mode="live", model="anthropic:stub")
    field_assist(DRAFT, store, mode="live", model="anthropic:stub")
    assert result["suggestions"]["all"][0]["synonyms"] == ["ICA", "invasive coronary angiography"]
    assert StubModel.invoked == 1 and result["model"] == "anthropic:stub"


def test_member_queues_an_assist_job(sign_in, db):
    member, csrf = sign_in("member")
    r = member.post(f"{API}/fields/assist", json={**DRAFT, "mode": "demo"}, headers=csrf)
    assert r.status_code == 202, r.text
    assert r.json()["kind"] == "field_assist" and r.json()["status"] == "queued"
    job = db.get(Job, uuid.UUID(r.json()["id"]))
    assert job.payload == {
        "mode": "demo",
        "draft": {
            "description": DRAFT["description"],
            "topic": "",
            "keywords": {"all": [], "any": [], "none": []},
        },
    }


def test_assist_refusals(sign_in, settings):
    member, csrf = sign_in("member")
    empty = member.post(f"{API}/fields/assist", json={"description": "  "}, headers=csrf)
    assert empty.status_code == 422 and empty.json()["code"] == "nothing_to_assist"
    viewer, vcsrf = sign_in("viewer")
    assert viewer.post(f"{API}/fields/assist", json=DRAFT, headers=vcsrf).status_code == 403
    assert member.post(f"{API}/fields/assist", json=DRAFT).status_code == 403  # no CSRF
    too_long = member.post(f"{API}/fields/assist", json={"description": "x" * 2001}, headers=csrf)
    assert too_long.status_code == 422


def test_demo_assist_is_refused_when_demo_is_off(app, sign_in):
    from dataclasses import replace

    app.state.settings = replace(app.state.settings, allow_demo=False)
    member, csrf = sign_in("member")
    r = member.post(f"{API}/fields/assist", json={**DRAFT, "mode": "demo"}, headers=csrf)
    assert r.status_code == 422


def test_the_worker_answers_an_assist_job(world):
    settings, factory, sign_in = world
    member, csrf = sign_in("member")
    r = member.post(f"{API}/fields/assist", json={**DRAFT, "mode": "demo"}, headers=csrf)
    Worker(settings, factory).drain()
    job = member.get(f"{API}/jobs/{r.json()['id']}").json()
    assert job["status"] == "done", job
    result = job["progress"]["result"]
    assert result["mode"] == "demo" and len(result["suggestions"]["include"]) >= 2
    assert (settings.cache_dir / "assist" / "research.sqlite").exists()
