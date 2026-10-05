"""Gold sets API: list (usable flag, counts) and build from an SR spec (job gold_build)."""

from eval_helpers import europepmc, panel_gold, row

from research_agent.eval.gold import write_gold
from research_agent.web.db.models import GoldSet, Job
from research_agent.web.worker import Worker

API = "/api/v1"
BODY = {
    "name": "toy-sr",
    "citation": "Test et al. 2026",
    "topic": "deep learning CT-FFR",
    "query": "ctffr",
    "included": [{"doi": "10.1000/p1"}, {"doi": "10.1000/p2"}],
    "sr_reference": "10.1000/the-sr",
}


def test_list_marks_usable_gold_sets(sign_in, db, settings):
    gold = write_gold(panel_gold(), settings.gold_dir / "panel-toy.json")
    db.add(GoldSet(name="panel-toy", citation="c", sha256=gold.content_sha256))  # found by name
    db.add(GoldSet(name="gone", citation="c", sha256="x"))
    db.commit()
    viewer, _ = sign_in("viewer")
    rows = {g["name"]: g for g in viewer.get(f"{API}/gold-sets").json()}
    assert rows["panel-toy"]["usable"] is True and rows["gone"]["usable"] is False
    assert rows["panel-toy"]["candidates"] is None and rows["panel-toy"]["built_in_app"] is False


def test_build_validation_and_name_clash(sign_in, db, settings):
    member, csrf = sign_in("member")
    for bad in ({**BODY, "name": "../x"}, {**BODY, "included": []}, {**BODY, "query": "x"}):
        assert member.post(f"{API}/gold-sets", json=bad, headers=csrf).status_code == 422
    db.add(GoldSet(name="toy-sr", citation="c", sha256="x"))
    db.commit()
    r = member.post(f"{API}/gold-sets", json=BODY, headers=csrf)
    assert r.status_code == 409 and r.json()["code"] == "name_taken"


def test_build_through_the_worker(world):
    settings, factory, sign_in = world
    member, csrf = sign_in("member")
    r = member.post(f"{API}/gold-sets", json=BODY, headers=csrf)
    assert r.status_code == 202 and r.json()["kind"] == "gold_build"
    client = europepmc({"*": [row(i) for i in range(1, 5)]})
    assert Worker(settings, factory, sleep=lambda s: None, http_client=client).tick()
    job = member.get(f"{API}/jobs/{r.json()['id']}").json()
    assert job["status"] == "done" and job["progress"]["result"]["positives"] == 2
    listed = member.get(f"{API}/gold-sets").json()
    assert listed[0]["name"] == "toy-sr" and listed[0]["usable"] is True and listed[0]["built_in_app"] is True
    with factory() as db:
        assert db.get(Job, r.json()["id"]).payload["sr_reference"] == "10.1000/the-sr"
