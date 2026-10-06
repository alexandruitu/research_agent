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


def groups(client, run_id, **params):
    r = client.get(f"/api/v1/runs/{run_id}/papers/groups", params=params)
    assert r.status_code == 200, r.text
    return r.json()


def test_quality_groups_list_the_four_main_groups_with_counts_and_rules(sign_in, imported):
    viewer, _ = sign_in("viewer")
    run = imported["eval"]
    body = groups(viewer, run)
    keys = [g["key"] for g in body]
    assert keys[:4] == ["read_first", "worth_a_look", "has_problems", "not_relevant"]
    assert all(g["rule"] and g["label"] for g in body)
    assert sum(g["count"] for g in body) == page(viewer, run)["total"]
    for g in body:
        assert page(viewer, run, group=g["key"])["total"] == g["count"]
    # the fifth group is listed only when it has papers
    assert ("not_reviewed" in keys) == any(g["key"] == "not_reviewed" and g["count"] for g in body)
    # filters narrow the counts
    dropped = {g["key"]: g["count"] for g in groups(viewer, run, decision="exclude")}
    assert dropped["worth_a_look"] == 0 and dropped["not_relevant"] > 0


def test_other_dimensions_count_like_the_group_filter(sign_in, imported):
    viewer, _ = sign_in("viewer")
    for run in ("eval", "research"):
        total = page(viewer, imported[run])["total"]
        for by in ("year", "decided_by", "library", "source"):
            body = groups(viewer, imported[run], by=by)
            assert body and all(g["count"] > 0 and g["rule"] for g in body), by
            if by != "source":  # a paper found by several sources is in each of their groups
                assert sum(g["count"] for g in body) == total, by
            for g in body:
                assert page(viewer, imported[run], group_by=by, group=g["key"])["total"] == g["count"], (
                    by,
                    g,
                )
    assert {g["key"] for g in groups(viewer, imported["eval"], by="library")} == {"not_saved"}
    assert {g["key"] for g in groups(viewer, imported["eval"], by="source")} == {"none"}
    assert "demo" in {g["key"] for g in groups(viewer, imported["research"], by="source")}
    by_criterion = {g["key"] for g in groups(viewer, imported["eval"], by="decided_by")}
    assert {"kept", "topic_match"} <= by_criterion


def test_groups_need_a_real_run_and_a_known_dimension(sign_in, imported):
    viewer, _ = sign_in("viewer")
    missing = viewer.get("/api/v1/runs/00000000-0000-0000-0000-000000000000/papers/groups")
    assert missing.status_code == 404
    assert viewer.get(f"/api/v1/runs/{imported['eval']}/papers/groups", params={"by": "x"}).status_code == 422
