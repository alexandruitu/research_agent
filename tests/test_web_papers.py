import pytest
from sqlalchemy import delete, select

from research_agent.web.db.models import EvidenceClaim, Paper


def table(client, run_id, **params):
    return client.get(f"/api/v1/runs/{run_id}/papers", params=params)


def rows_by_source(response):
    return {r["paper"]["source_id"]: r for r in response.json()["items"]}


def test_needs_a_session_and_a_real_run(client, sign_in, imported):
    assert table(client, imported["eval"]).status_code == 401
    viewer, _ = sign_in("viewer")
    assert table(viewer, "00000000-0000-0000-0000-000000000000").status_code == 404


def test_eval_run_rows_carry_every_stage_cell(sign_in, imported):
    viewer, _ = sign_in("viewer")
    body = table(viewer, imported["eval"], page_size=50).json()
    assert body["total"] == 12 and body["page"] == 1 and len(body["items"]) == 12
    rows = {r["paper"]["source_id"]: r for r in body["items"]}
    lost = rows["MED:3"]  # Jev p=0.03: auto-dropped although the SR included it
    assert lost["in_sr"] is True and lost["found_by"] == "query"
    assert lost["screen"] == {
        "tier": "jev",
        "decision": "exclude",
        "jev_decision": "exclude",
        "llm_decision": "include",
        "criteria": {"topic_match": 0.03},
    }
    # Every SR positive is in the agreement sample, whatever the screen decided: its downstream data is shown.
    assert lost["extract"] == {"claims": 1, "quotes_verified": True} and lost["reviews"]["a"] == "include"
    assert lost["rank"] is None  # eval runs are never ranked
    dropped = rows["MED:5"]  # dropped by Jev, outside the agreement sample: not applicable
    assert dropped["in_sr"] is False
    assert dropped["extract"] is None and dropped["reviews"] is None and dropped["rank"] is None
    escalated = rows["MED:2"]
    assert escalated["screen"]["tier"] == "llm" and escalated["screen"]["jev_decision"] == "escalate"
    assert (
        rows["MED:10"]["extract"] is None
    )  # kept, outside the agreement sample: not applicable, not missing
    assert rows["MED:10"]["reviews"] is None


def test_agreement_sample_rows_show_claims_and_reviews(sign_in, imported):
    viewer, _ = sign_in("viewer")
    row = rows_by_source(table(viewer, imported["eval"]))["MED:1"]
    assert row["extract"] == {"claims": 1, "quotes_verified": True}
    assert row["reviews"] == {"a": "include", "b": "include", "adjudicated": True, "adjudicator": "include"}


def test_research_run_rows_and_the_missing_versus_not_applicable_distinction(sign_in, imported, db):
    viewer, _ = sign_in("viewer")
    body = table(viewer, imported["research"]).json()
    assert body["total"] == 6
    row = rows_by_source(table(viewer, imported["research"]))["demo:1"]
    assert row["in_sr"] is None and row["found_by"] == "query"
    assert (
        row["extract"]["claims"] == 1
        and row["reviews"]["adjudicated"] is True
        and row["rank"]["position"] >= 1
    )
    paper = db.scalar(select(Paper).where(Paper.source_id == "demo:2"))
    db.execute(delete(EvidenceClaim).where(EvidenceClaim.paper_id == paper.id))
    db.commit()
    gone = rows_by_source(table(viewer, imported["research"]))["demo:2"]
    assert gone["extract"] == {"missing": True}  # expected in a research run, not there: hatched, not a dash


@pytest.mark.parametrize(
    "params,expected",
    [
        ({"decision": "exclude"}, 6),
        ({"decision": "include"}, 6),
        ({"tier": "jev"}, 7),
        ({"tier": "llm"}, 5),
        ({"escalated": "true"}, 5),
        ({"escalated": "false"}, 7),
        ({"in_sr": "true"}, 4),
        ({"in_sr": "false"}, 8),
        ({"criterion": "topic_match", "p_min": 0.9}, 3),
        ({"criterion": "topic_match", "p_max": 0.05}, 4),
        ({"criterion": "topic_match", "p_min": 0.4, "p_max": 0.6}, 5),
    ],
)
def test_filters(sign_in, imported, params, expected):
    viewer, _ = sign_in("viewer")
    assert table(viewer, imported["eval"], **params).json()["total"] == expected


def test_decision_filters_agree_with_the_run_counts_when_some_papers_were_never_screened(
    sign_in, db, tmp_path
):
    from web_fixtures import make_eval_run

    from research_agent.web.importer.evals import import_eval_run

    # Papers 1, 9 and 10 have no abstract: rows with tier "rule" (decision "uncertain"), never screened.
    folder, _gold, _report = make_eval_run(tmp_path, name="noabs", no_abstract=(1, 9, 10))
    run_id = import_eval_run(db, folder).run_id
    db.commit()
    viewer, _ = sign_in("viewer")
    counts = viewer.get(f"/api/v1/runs/{run_id}").json()["counts"]

    def total(**params):
        return table(viewer, run_id, **params).json()["total"]

    assert total() == 12 and total(tier="rule") == 3
    assert total(decision="exclude") == counts["dropped"]
    assert total(decision="include") + total(decision="uncertain") == counts["kept"]


def test_sorting_and_paging(sign_in, imported):
    viewer, _ = sign_in("viewer")
    by_title = [r["paper"]["title"] for r in table(viewer, imported["eval"]).json()["items"]]
    assert by_title == sorted(by_title, key=str.lower)
    top = table(viewer, imported["eval"], sort="criterion:topic_match", direction="desc").json()["items"][0]
    assert top["paper"]["source_id"] == "MED:1"
    third = table(viewer, imported["eval"], page_size=5, page=3).json()
    assert (
        third["total"] == 12 and len(third["items"]) == 2 and third["page"] == 3 and third["page_size"] == 5
    )
    ranked = table(viewer, imported["research"], sort="score", direction="desc").json()["items"]
    assert ranked[0]["rank"]["position"] == 1


@pytest.mark.parametrize(
    "params",
    [
        {"page_size": 201},
        {"page": 0},
        {"page": 10**19},  # would overflow the SQL offset
        {"sort": "drop table"},
        {"decision": "maybe"},
        {"tier": "x"},
        {"p_min": 0.5},  # a probability bound without the criterion it applies to
        {"p_max": 0.5},
        {"criterion": "topic_match", "p_min": 0.7, "p_max": 0.3},
    ],
)
def test_bad_parameters_are_rejected(sign_in, imported, params):
    viewer, _ = sign_in("viewer")
    r = table(viewer, imported["eval"], **params)
    assert r.status_code == 422 and r.json()["code"] == "validation_error"


def _eval_run_with_gaps(db, tmp_path, drops):
    from web_fixtures import drop_call, make_eval_run

    from research_agent.web.importer.evals import import_eval_run

    folder, _gold, _report = make_eval_run(tmp_path, name="gaps")
    for role, pid in drops:
        drop_call(folder, role, pid)
    run_id = import_eval_run(db, folder).run_id
    db.commit()
    return run_id


def test_eval_sample_papers_with_a_missing_extraction_show_missing_not_applicable(sign_in, db, tmp_path):
    run_id = _eval_run_with_gaps(db, tmp_path, [("extract", "MED:1")])
    viewer, _ = sign_in("viewer")
    rows = rows_by_source(table(viewer, run_id))
    assert rows["MED:1"]["extract"] == {"missing": True}  # in the agreement sample: expected, absent
    assert rows["MED:1"]["reviews"]["adjudicated"] is True
    assert rows["MED:10"]["extract"] is None  # outside the sample: not applicable


def test_an_expected_adjudication_without_its_row_is_missing(sign_in, db, tmp_path):
    run_id = _eval_run_with_gaps(db, tmp_path, [("adjudicate", "MED:1")])
    viewer, _ = sign_in("viewer")
    assert rows_by_source(table(viewer, run_id))["MED:1"]["reviews"] == {"missing": True}


def test_a_research_row_with_only_one_reviewer_is_missing(sign_in, imported, db):
    from research_agent.web.db.models import Review

    paper = db.scalar(select(Paper).where(Paper.source_id == "demo:2"))
    db.execute(delete(Review).where(Review.paper_id == paper.id, Review.role == "b"))
    db.commit()
    viewer, _ = sign_in("viewer")
    assert rows_by_source(table(viewer, imported["research"]))["demo:2"]["reviews"] == {"missing": True}


def test_quotes_verified_is_computed_against_the_stored_abstract(sign_in, imported, db):
    paper = db.scalar(select(Paper).where(Paper.source_id == "demo:3"))
    claim = db.scalar(select(EvidenceClaim).where(EvidenceClaim.paper_id == paper.id))
    claim.quote = "a sentence the abstract never contained"
    db.commit()
    viewer, _ = sign_in("viewer")
    rows = rows_by_source(table(viewer, imported["research"]))
    assert rows["demo:3"]["extract"] == {"claims": 1, "quotes_verified": False}
    assert rows["demo:1"]["extract"] == {"claims": 1, "quotes_verified": True}


def test_the_in_sr_filter_needs_a_gold_set(sign_in, imported):
    viewer, _ = sign_in("viewer")
    for value in ("true", "false"):
        r = table(viewer, imported["research"], in_sr=value)
        assert r.status_code == 422 and r.json()["code"] == "validation_error"
        assert "gold set" in r.json()["message"]
