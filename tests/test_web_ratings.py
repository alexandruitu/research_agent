"""Rating samples and blind human reference ratings, through to a recomputed `human` eval report."""

import json

from eval_job_helpers import forbid_models, in_process
from web_fixtures import make_panel_eval

from research_agent.web.db.models import EvalReport, Job
from research_agent.web.evals import stratified_sample
from research_agent.web.importer.evals import import_eval_run
from research_agent.web.worker import Worker

API = "/api/v1"
MODEL_TEXT = ("SIMULATED review", "Synthetic fixture exercises the checklist", '"verdict"', '"answers"')


def panel_report(settings, factory, sample=6):
    folder, _gold = make_panel_eval(settings.evals_dir.parent, sample=sample)
    with factory() as db:
        report = import_eval_run(db, folder).report_id
        db.commit()
    return report, folder


def answers(next_paper, answer="yes"):
    return [
        {"reviewer": r["key"], "item": i["key"], "answer": answer, "quote": ""}
        for r in next_paper["reviewers"]
        for i in r["items"]
    ]


def assert_blind(response):
    assert not any(text in response.text for text in MODEL_TEXT), response.text


def test_stratified_sample_is_seeded_and_spreads_over_scores():
    papers = {f"p{i}": {"score": i / 10} for i in range(10)} | {"none": {"score": None}}
    picks = stratified_sample(papers, 3, seed=4)
    assert picks == stratified_sample(papers, 3, seed=4) and len(set(picks)) == 3
    scores = [papers[p]["score"] for p in picks]
    assert scores[0] < 0.4 and scores[2] is None or scores[2] >= 0.7
    assert stratified_sample(papers, 50, 0)[-1] == "none" and len(stratified_sample(papers, 50, 0)) == 11


def test_the_rating_flow_is_blind_until_submitted_and_recomputes_a_human_report(world, monkeypatch):
    settings, factory, sign_in = world
    forbid_models(monkeypatch)
    report, folder = panel_report(settings, factory)
    admin, admin_csrf = sign_in("admin")
    member, csrf = sign_in("member")

    assert member.post(f"{API}/evals/{report}/rating-samples", json={}, headers=csrf).status_code == 403
    r = admin.post(f"{API}/evals/{report}/rating-samples", json={"size": 3, "seed": 1}, headers=admin_csrf)
    assert r.status_code == 201, r.text
    sample = r.json()
    assert sample["size"] == 3 and len(sample["papers"]) == 3 and sample["raters_needed"] == 2
    assert sample["complete_papers"] == 0 and sample["latest_human_eval_id"] is None
    assert_blind(r)
    sid = sample["id"]

    nxt = member.get(f"{API}/rating-samples/{sid}/next")
    assert_blind(nxt)
    data = nxt.json()
    assert data["done"] is False and data["position"] == 0 and data["total"] == 3
    paper = data["paper"]
    assert paper["paper_id"] == sample["papers"][0]["paper_id"] and paper["text"]["content"].startswith(
        "Abstract"
    )
    assert [r["key"] for r in data["reviewers"]] == ["methodologist", "clinician", "statistician"]
    assert data["reviewers"][0]["items"][1] == {"key": "m1", "text": "methodologist item one."}

    pid = paper["paper_id"]
    reveal = member.get(f"{API}/rating-samples/{sid}/papers/{pid}/reveal")
    assert reveal.status_code == 409 and reveal.json()["code"] == "not_rated"
    assert_blind(reveal)

    partial = {"paper_id": pid, "answers": answers(data)[:-1]}
    assert member.post(f"{API}/rating-samples/{sid}/ratings", json=partial, headers=csrf).status_code == 422
    other = {"paper_id": "MED:999", "answers": answers(data)}
    assert member.post(f"{API}/rating-samples/{sid}/ratings", json=other, headers=csrf).status_code == 404
    body = {"paper_id": pid, "answers": answers(data)}
    assert member.post(f"{API}/rating-samples/{sid}/ratings", json=body).status_code == 403  # no CSRF
    r = member.post(f"{API}/rating-samples/{sid}/ratings", json=body, headers=csrf)
    assert r.status_code == 201, r.text
    assert r.json()["saved"] == 6 and r.json()["job"]["kind"] == "eval_run"
    again = member.post(f"{API}/rating-samples/{sid}/ratings", json=body, headers=csrf)
    assert again.status_code == 409 and again.json()["code"] == "already_rated"

    reveal = member.get(f"{API}/rating-samples/{sid}/papers/{pid}/reveal").json()
    shared = next(i for i in reveal["items"] if i["reviewer"] == "methodologist" and i["item"] == "shared")
    assert shared["mine"] == {"answer": "yes", "quote": "", "section": ""} and shared["model"]["answer"] == "yes"
    assert reveal["compared"] == 6 and reveal["agreed"] == sum(i["agree"] for i in reveal["items"])
    assert member.get(f"{API}/rating-samples/{sid}/next").json()["paper"]["paper_id"] != pid

    # A second rater on the same paper: the queued recompute is reused, not duplicated.
    admin_next = admin.get(f"{API}/rating-samples/{sid}/next").json()
    assert admin_next["paper"]["paper_id"] != pid  # fewest raters first
    r = admin.post(
        f"{API}/rating-samples/{sid}/ratings",
        json={"paper_id": pid, "answers": answers(data, "no")},
        headers=admin_csrf,
    )
    assert r.status_code == 201 and r.json()["job"] is None
    progress = admin.get(f"{API}/rating-samples/{sid}").json()
    assert progress["complete_papers"] == 1 and progress["my_rated"] == 1

    worker = Worker(settings, factory, sleep=lambda s: None, spawn_eval=in_process())
    assert worker.tick()
    with factory() as db:
        job = db.query(Job).filter(Job.kind == "eval_run").one()
        assert job.status == "done", job.error
        human = db.get(EvalReport, job.progress["result"]["eval_id"])
        assert human.kind == "human" and str(human.parent_id) == str(report)
        assert human.config["rating_sample_id"] == sid and human.metrics["human"]["units"] == 6
        assert len(human.metrics["human"]["raters"]) == 2
    written = json.loads((folder / "human_ratings.json").read_text())
    assert written["schema"] == 1 and len(written["ratings"]) == 12
    assert {r["rater"] for r in written["ratings"]} <= {str(u) for u in _user_ids(factory)}
    assert not (folder / "metrics.json").read_text().count('"human"')  # the panel report is unchanged
    progress = member.get(f"{API}/rating-samples/{sid}").json()
    assert progress["latest_human_eval_id"] == str(human.id)
    listed = member.get(f"{API}/evals?kind=human").json()
    head = listed[0]["headline"]
    assert head["human_units"] == 6 and head["human_raters"] == 2 and 0 <= head["human_accuracy"] <= 1


def _user_ids(factory):
    from research_agent.web.db.models import User

    with factory() as db:
        return [u.id for u in db.query(User)]


def test_a_sample_needs_a_panel_report(world):
    settings, factory, sign_in = world
    report, _folder = panel_report(settings, factory, sample=4)
    admin, csrf = sign_in("admin")
    nil = "00000000-0000-0000-0000-000000000000"
    assert admin.post(f"{API}/evals/{nil}/rating-samples", json={}, headers=csrf).status_code == 404
    assert admin.get(f"{API}/rating-samples/{nil}").status_code == 404
    r = admin.post(f"{API}/evals/{report}/rating-samples", json={"size": 0}, headers=csrf)
    assert r.status_code == 422
