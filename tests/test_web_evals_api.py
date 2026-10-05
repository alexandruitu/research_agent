"""Evals API: start (202 job), list with kind/status/chips/headline, detail, compare, estimate."""


from eval_helpers import panel_gold
from web_fixtures import make_ablation_eval, make_panel_eval

from research_agent.eval.gold import write_gold
from research_agent.web.db.models import GoldSet, Job
from research_agent.web.importer.evals import import_eval_run

API = "/api/v1"


def gold_row(db, settings, name="panel-toy"):
    gold = write_gold(panel_gold(name=name), settings.gold_dir / f"{name}.json")
    row = GoldSet(
        name=name, citation="c", sha256=gold.content_sha256, path=str(settings.gold_dir / f"{name}.json")
    )
    db.add(row)
    db.commit()
    return row


def test_start_a_panel_eval_queues_an_eval_run_job(sign_in, db, settings):
    member, csrf = sign_in("member")
    gold = gold_row(db, settings)
    body = {"kind": "panel", "mode": "demo", "gold_set_id": str(gold.id), "sample": 6, "seed": 2}
    r = member.post(f"{API}/evals", json=body, headers=csrf)
    assert r.status_code == 202, r.text
    job = r.json()
    assert job["kind"] == "eval_run" and job["status"] == "queued" and job["run_id"] is None
    payload = db.get(Job, job["id"]).payload
    assert payload["kind"] == "panel" and payload["sample"] == 6 and payload["review"]["panel"]
    assert payload["gold_path"].endswith("panel-toy.json") and payload["folder"].startswith("panel-")
    listed = member.get(f"{API}/evals").json()
    assert listed[0]["id"] is None and listed[0]["status"] == "queued" and listed[0]["job"]["id"] == job["id"]
    assert listed[0]["kind"] == "panel"


def test_start_validation(sign_in, db, settings):
    member, csrf = sign_in("member")
    gold = gold_row(db, settings)
    nil = "00000000-0000-0000-0000-000000000000"
    cases = [
        ({"kind": "screening", "gold_set_id": nil}, 404, "not_found"),
        ({"kind": "panel"}, 422, "validation_error"),
        ({"kind": "panel", "gold_set_id": str(gold.id), "run_id": nil}, 422, "validation_error"),
        ({"kind": "panel", "gold_set_id": str(gold.id), "sample": 0}, 422, "validation_error"),
        ({"kind": "ablation", "panel_eval_id": nil}, 404, "not_found"),
        ({"kind": "human", "rating_sample_id": nil}, 404, "not_found"),
        ({"kind": "nope"}, 422, "validation_error"),
    ]
    for body, status, code in cases:
        r = member.post(f"{API}/evals", json=body, headers=csrf)
        assert (r.status_code, r.json()["code"]) == (status, code), (body, r.text)
    (settings.gold_dir / "panel-toy.json").write_text(
        (settings.gold_dir / "panel-toy.json").read_text().replace("Paper 1 title", "Edited")
    )
    r = member.post(f"{API}/evals", json={"kind": "screening", "gold_set_id": str(gold.id)}, headers=csrf)
    assert r.status_code == 422 and r.json()["code"] == "gold_file_changed"


def test_demo_needs_the_deployment_switch(sign_in, db, settings, app):
    from dataclasses import replace

    app.state.settings = replace(settings, allow_demo=False)
    from research_agent.web.api.deps import get_settings

    app.dependency_overrides[get_settings] = lambda: app.state.settings
    member, csrf = sign_in("member")
    gold = gold_row(db, settings)
    r = member.post(
        f"{API}/evals", json={"kind": "panel", "gold_set_id": str(gold.id), "mode": "demo"}, headers=csrf
    )
    assert r.status_code == 422 and "demo" in r.json()["message"]


def imported_reports(db, tmp_path, second_reviewers=("methodologist", "clinician")):
    panel, _gold = make_panel_eval(tmp_path)
    first = import_eval_run(db, panel).report_id
    other, _gold = make_panel_eval(tmp_path, name="panel-b", reviewers=second_reviewers, sample=6)
    second = import_eval_run(db, other).report_id
    ablation = import_eval_run(db, make_ablation_eval(tmp_path, panel)).report_id
    db.commit()
    return first, second, ablation


def test_list_and_detail_carry_kind_chips_and_headline(sign_in, db, tmp_path):
    first, _second, ablation = imported_reports(db, tmp_path)
    viewer, _ = sign_in("viewer")
    listed = {e["id"]: e for e in viewer.get(f"{API}/evals").json()}
    panel = listed[str(first)]
    assert panel["kind"] == "panel" and panel["status"] == "done" and panel["job"] is None
    assert panel["gold_set"]["name"] == "panel-toy" and panel["gold_set"]["built_in_app"] is False
    assert "3 reviewers" in panel["chips"] and "n=4 seed 1" in panel["chips"] and "demo" in panel["chips"]
    head = panel["headline"]
    assert head["papers"] == 4 and head["reviewers"] == 3 and head["raw_agreement"] == 1.0
    assert head["same_family"] is True and head["sr_auc"] == 0.5 and head["retrieval_recall"] is None
    abl = listed[str(ablation)]
    assert abl["parent_id"] == str(first) and abl["headline"]["summary"].startswith("Going from 2 to 3")
    assert [e["kind"] for e in viewer.get(f"{API}/evals?kind=ablation").json()] == ["ablation"]

    detail = viewer.get(f"{API}/evals/{first}").json()
    assert detail["kind"] == "panel" and detail["metrics"]["panel"]["n"] == 4
    assert detail["config"]["source"]["gold_path"] == "panel-toy.json"  # no server paths
    assert detail["children"] == [{"id": str(ablation), "kind": "ablation", "created_at": abl["created_at"]}]
    assert detail["rating_sample_ids"] == []


def test_compare_aligns_two_panel_reports_and_refuses_mixed_kinds(sign_in, db, tmp_path):
    first, second, ablation = imported_reports(db, tmp_path)
    viewer, _ = sign_in("viewer")
    r = viewer.get(f"{API}/evals/compare?ids={first},{second}")
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["family"] == "panel" and [x["id"] for x in data["reports"]] == [str(first), str(second)]
    rows = {row["key"]: row for row in data["metrics"]}
    assert rows["panel.n"]["values"] == [4, 6] and rows["panel.n"]["differs"] is True
    assert rows["panel.statistician.model"]["values"] == ["synthetic-demo-v1", None]
    config = {row["key"]: row for row in data["config"]}
    assert config["sample.n"]["values"] == [4, 6] and config["mode"]["differs"] is False
    for query, code in (
        (f"{first}", "validation_error"),
        (f"{first},{second},{ablation},{first}x", "validation_error"),
        (f"{first},{ablation}", "mixed_kinds"),
    ):
        r = viewer.get(f"{API}/evals/compare?ids={query}")
        assert r.status_code == 422 and r.json()["code"] == code, query
    assert (
        viewer.get(f"{API}/evals/compare?ids={first},00000000-0000-0000-0000-000000000000").status_code == 404
    )


def test_estimate_counts_calls_and_prices_known_models(sign_in, db, settings, tmp_path):
    member, csrf = sign_in("member")
    gold = gold_row(db, settings)
    body = {"kind": "panel", "gold_set_id": str(gold.id), "sample": 4, "mode": "demo"}
    r = member.post(f"{API}/evals/estimate", json=body, headers=csrf)
    assert r.status_code == 200, r.text
    data = r.json()
    reviewers = [line for line in data["lines"] if line["role"].startswith("review:")]
    editor = [line for line in data["lines"] if line["role"] == "editor"]
    assert all(line["calls"] == 4 for line in reviewers) and editor[0]["calls"] == 4
    assert data["calls"] == 4 * (len(reviewers) + 1) and data["input_tokens"] == data["input_chars"] // 4
    assert data["cost_usd"] is None  # no model configured: no price
    assert db.query(Job).count() == 0  # an estimate starts nothing

    first, _second, _abl = imported_reports(db, tmp_path)
    r = member.post(
        f"{API}/evals/estimate",
        json={"kind": "ablation", "panel_eval_id": str(first), "rerun_editor": True},
        headers=csrf,
    )
    data = r.json()
    assert data["calls"] == 4 * (2**3 - 2) and data["lines"][0]["role"] == "editor"
    offline = member.post(
        f"{API}/evals/estimate", json={"kind": "ablation", "panel_eval_id": str(first)}, headers=csrf
    )
    assert offline.json()["calls"] == 0 and offline.json()["cost_usd"] == 0


def test_price_table():
    from research_agent.web.evals import price

    assert price("anthropic:claude-sonnet-5", 4_000_000, 0) == 3.0
    assert price("google_genai:gemini-2.5-flash", 0, 1_000_000) == 2.5
    assert price("openai:gpt-x", 10, 10) is None
