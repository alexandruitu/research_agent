import json
import uuid

import pytest


def get(client, path, **params):
    return client.get(f"/api/v1{path}", params=params)


@pytest.mark.parametrize("path", ["/fields", "/runs", "/stages", "/evals"])
def test_read_endpoints_need_a_session(client, path):
    r = get(client, path)
    assert r.status_code == 401 and r.json()["code"] == "unauthorized"


def test_fields_list_with_latest_criteria(sign_in, imported):
    client, _ = sign_in("viewer")
    fields = get(client, "/fields").json()
    assert {f["topic"] for f in fields} == {"retrieval augmented generation", "deep learning CT-FFR"}
    for f in fields:
        assert [c["key"] for c in f["criteria"]] == ["topic_match"] and f["criteria"][0]["version"] == 1
    assert get(client, f"/fields/{fields[0]['id']}").json()["id"] == fields[0]["id"]
    assert get(client, f"/fields/{uuid.uuid4()}").status_code == 404


def test_runs_list_filter_and_detail_counts(sign_in, imported):
    client, _ = sign_in("viewer")
    runs = get(client, "/runs").json()
    assert {r["kind"] for r in runs} == {"research", "eval"}
    assert {r["kind"]: r["paper_count"] for r in runs} == {"research": 6, "eval": 12}
    assert [r["kind"] for r in get(client, "/runs", kind="eval").json()] == ["eval"]
    detail = get(client, f"/runs/{imported['eval']}").json()
    assert detail["gold_set_name"] == "toy" and detail["status"] == "done"
    counts = detail["counts"]
    assert counts == {
        "screened": 12,
        "kept": imported["report"]["strategies"]["cascade"]["kept"],  # the UI number equals the report number
        "dropped": 12 - imported["report"]["strategies"]["cascade"]["kept"],
        "escalated": 5,
        "in_sr": 4,
    }
    assert get(client, f"/runs/{uuid.uuid4()}").status_code == 404
    assert get(client, "/runs/not-a-uuid").status_code == 422


def test_run_counts_leave_out_candidates_that_were_never_screened(sign_in, db, tmp_path):
    """Gold candidates without an abstract are stored as `rule` rows ("not screened"); on real gold sets
    (mlffrct-2024: 162 candidates, 151 screened) the counts must still equal the report's."""
    from web_fixtures import make_eval_run

    from research_agent.web.importer.evals import import_eval_run

    # Paper 1 is SR-included, 9 is auto-included by Jev, 10 would be escalated: none has an abstract.
    folder, _gold, report = make_eval_run(tmp_path, name="noabs", no_abstract=(1, 9, 10))
    run_id = import_eval_run(db, folder).run_id
    db.commit()
    client, _ = sign_in("viewer")
    detail = get(client, f"/runs/{run_id}").json()
    assert detail["paper_count"] == 12  # every candidate is still a row of the paper table
    cascade, c = report["strategies"]["cascade"], report["counts"]
    assert c["screened"] == 9 and c["positives_screened"] == 3 and c["positives_no_abstract"] == 1
    assert detail["counts"] == {
        "screened": c["screened"],
        "kept": cascade["kept"],
        "dropped": c["screened"] - cascade["kept"],
        "escalated": cascade["escalated"],
        # `in_sr` counts every SR-included paper in the run (what the "in the SR" filter shows), including
        # the one that was never screened; the report's `positives_screened` is only the recall denominator.
        "in_sr": c["positives_screened"] + c["positives_no_abstract"],
    }


def test_stages_are_computed_from_the_imported_eval_data(sign_in, imported):
    client, _ = sign_in("viewer")
    stages = {s["id"]: s for s in get(client, "/stages").json()}
    assert stages["topic"]["status"] == "input"
    assert stages["search"]["status"] == "measured" and stages["search"]["headline"] == "recall 4/4"
    assert stages["screen"]["status"] == "measured" and stages["screen"]["headline"] == "recall 3/4"
    assert stages["adjudicate"]["status"] == "measured" and stages["adjudicate"]["headline"] == "fired 6 of 6"
    assert stages["plan"]["status"] == "unmeasured"
    assert stages["rank"]["status"] == "unmeasured" and stages["rank"]["limits"]


def test_stages_without_eval_data_are_never_green(sign_in):
    client, _ = sign_in("viewer")
    assert {s["status"] for s in get(client, "/stages").json()} == {"input", "unmeasured"}


def test_evals_list_and_detail_equal_the_stored_report(sign_in, imported, tmp_path):
    client, _ = sign_in("viewer")
    (summary,) = get(client, "/evals").json()
    assert summary["gold_set"]["name"] == "toy" and summary["run_id"] == str(imported["eval"])
    head = summary["headline"]
    assert head["cascade_recall"] == {"k": 3, "n": 4} and head["retrieval_recall"] == {"k": 4, "n": 4}
    assert head["recommended"] is not None and head["screened"] == 12
    detail = get(client, f"/evals/{summary['id']}").json()
    assert detail["metrics"] == json.loads((tmp_path / "evals" / "toy" / "metrics.json").read_text())
    assert detail["agreement"]["n"] == 6
    assert get(client, f"/evals/{uuid.uuid4()}").status_code == 404
