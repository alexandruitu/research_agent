from sqlalchemy import select

from research_agent.web.db.models import Paper, PaperReview


def page(client, run_id, **params):
    r = client.get(f"/api/v1/runs/{run_id}/papers", params={"page_size": 50, **params})
    assert r.status_code == 200, r.text
    return r.json()


def rows(client, run_id, **params):
    return {x["paper"]["source_id"]: x for x in page(client, run_id, **params)["items"]}


def review(db, run_id, source_id, verdict, flags):
    """A panel review of one paper (the demo research run is a legacy A/B run otherwise)."""
    paper = db.scalar(select(Paper).where(Paper.source_id == source_id))
    db.add(
        PaperReview(
            run_id=run_id,
            paper_id=paper.id,
            text_source="abstract",
            editor_verdict=verdict,
            red_flag_count=flags,
            score=50.0,
        )
    )
    db.commit()


def legacy_verdict(reviews):
    if not reviews or "missing" in reviews:
        return None
    if reviews["adjudicator"]:
        return reviews["adjudicator"]
    return reviews["a"] if reviews["a"] == reviews["b"] else "uncertain"


def test_legacy_rows_are_grouped_by_their_a_b_verdicts(sign_in, imported):
    viewer, _ = sign_in("viewer")
    for run in ("eval", "research"):
        for row in rows(viewer, imported[run]).values():
            screen = row["screen"]
            verdict = legacy_verdict(row["reviews"])
            if screen["decision"] == "exclude" and screen["tier"] != "rule":
                expected = "not_relevant"
            elif verdict == "exclude":
                expected = "has_problems"
            elif verdict in ("include", "uncertain"):
                expected = "worth_a_look"  # red flags were never checked: never "read first"
            else:
                expected = "not_reviewed"
            assert row["group"] == expected, row["paper"]["source_id"]
    groups = {r["group"] for r in rows(viewer, imported["eval"]).values()}
    assert {"not_relevant", "worth_a_look"} <= groups and "read_first" not in groups


def test_panel_rows_use_the_editor_verdict_and_red_flags(sign_in, imported, db):
    viewer, _ = sign_in("viewer")
    kept = [s for s, r in rows(viewer, imported["research"]).items() if r["screen"]["decision"] != "exclude"]
    cases = [
        ("include", 0, "read_first"),
        ("include", 1, "worth_a_look"),
        ("uncertain", 1, "worth_a_look"),
        ("include", 2, "has_problems"),
        ("exclude", 0, "has_problems"),
        (None, 0, "not_reviewed"),
    ]
    assert len(kept) >= len(cases)
    for source_id, (verdict, flags, _) in zip(kept, cases, strict=False):
        review(db, imported["research"], source_id, verdict, flags)
    got = rows(viewer, imported["research"])
    for source_id, (_, _, expected) in zip(kept, cases, strict=False):
        assert got[source_id]["group"] == expected, (source_id, expected)


def test_filtering_on_one_quality_group(sign_in, imported):
    viewer, _ = sign_in("viewer")
    run = imported["eval"]
    dropped = page(viewer, run, group="not_relevant")
    assert dropped["total"] == page(viewer, run, decision="exclude")["total"] > 0
    assert {r["group"] for r in dropped["items"]} == {"not_relevant"}
    look = page(viewer, run, group_by="quality", group="worth_a_look")
    assert look["total"] > 0 and {r["group"] for r in look["items"]} == {"worth_a_look"}


def test_a_bad_group_is_refused(sign_in, imported):
    viewer, _ = sign_in("viewer")
    r = viewer.get(f"/api/v1/runs/{imported['eval']}/papers", params={"group": "DROP TABLE"})
    assert r.status_code == 422
    r = viewer.get(f"/api/v1/runs/{imported['eval']}/papers", params={"group_by": "colour"})
    assert r.status_code == 422
