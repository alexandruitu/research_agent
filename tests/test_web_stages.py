from research_agent.web.stages import evaluate_stages, format_headline, load_catalog, lookup, merge_metrics

METRICS = {
    "retrieval_recall": {"k": 15, "n": 16, "value": 0.9375},
    "strategies": {"cascade": {"recall": {"k": 15, "n": 16}}},
    "agreement": {
        "n": 36,
        "verdict": {"kappa": 0.9453},
        "same_family": True,
        "adjudication_rate": {"k": 1, "n": 36},
    },
}


def by_id(stages):
    return {s["id"]: s for s in stages}


def test_catalog_loads_with_every_stage_of_the_pipeline(settings):
    ids = [s["id"] for s in load_catalog(settings.stages_path)]
    assert ids == ["topic", "plan", "search", "dedup", "screen", "extract", "reviewers", "adjudicate", "rank"]


def test_lookup_and_headline_formatting():
    assert lookup(METRICS, "strategies.cascade.recall.k") == 15
    assert lookup(METRICS, "agreement.nope") is None
    assert format_headline("recall {retrieval_recall.k}/{retrieval_recall.n}", METRICS) == "recall 15/16"
    assert format_headline("kappa {agreement.verdict.kappa:.2f}", METRICS) == "kappa 0.95"
    assert format_headline("kappa {agreement.missing:.2f}", METRICS) is None


def test_status_is_computed_from_measurements(settings):
    stages = by_id(evaluate_stages(load_catalog(settings.stages_path), METRICS))
    assert stages["topic"]["status"] == "input"
    assert stages["search"]["status"] == "measured" and stages["search"]["headline"] == "recall 15/16"
    assert stages["screen"]["status"] == "measured" and stages["screen"]["headline"] == "recall 15/16"
    assert stages["extract"]["status"] == "measured"
    assert stages["reviewers"]["status"] == "caveat" and "one model family" in stages["reviewers"]["caveat"]
    assert stages["adjudicate"]["headline"] == "fired 1 of 36"
    assert stages["plan"]["status"] == "unmeasured" and stages["plan"]["headline"] is None
    assert stages["rank"]["status"] == "unmeasured" and stages["dedup"]["status"] == "unmeasured"


def test_without_any_eval_data_nothing_is_green(settings):
    stages = evaluate_stages(load_catalog(settings.stages_path), {})
    assert {s["status"] for s in stages} == {"input", "unmeasured"}


def test_a_stage_turns_green_only_when_its_metric_exists(settings):
    partial = {"retrieval_recall": {"k": 3, "n": 4}}
    stages = by_id(evaluate_stages(load_catalog(settings.stages_path), partial))
    assert stages["search"]["status"] == "measured" and stages["screen"]["status"] == "unmeasured"


def test_reviewers_without_the_family_flag_are_plain_measured(settings):
    metrics = {**METRICS, "agreement": {**METRICS["agreement"], "same_family": False}}
    assert (
        by_id(evaluate_stages(load_catalog(settings.stages_path), metrics))["reviewers"]["status"]
        == "measured"
    )


def test_merge_takes_each_key_from_the_newest_report_that_has_it():
    newest = {"retrieval_recall": {"k": 1, "n": 2}, "strategies": {"x": 1}}
    older = {"retrieval_recall": {"k": 9, "n": 9}, "agreement": {"n": 5}}
    merged = merge_metrics([newest, older])
    assert (
        merged["retrieval_recall"]["k"] == 1
        and merged["agreement"]["n"] == 5
        and merged["strategies"] == {"x": 1}
    )


PANEL = {
    "n": 20,
    "verdicts": {"fleiss": {"kappa": 0.61, "agreement": 0.85}},
    "model_families": {"single_family": True},
}


def test_reviewers_read_the_newest_panel_eval_first(settings):
    catalog = load_catalog(settings.stages_path)
    stages = by_id(evaluate_stages(catalog, {**METRICS, "panel": PANEL}))
    assert stages["reviewers"]["headline"] == "Fleiss kappa 0.61 on 20 papers"
    assert stages["reviewers"]["status"] == "caveat" and stages["reviewers"]["caveat"] == "one model family"
    two = {**PANEL, "model_families": {"single_family": False}}
    assert by_id(evaluate_stages(catalog, {"panel": two}))["reviewers"]["status"] == "measured"


def test_an_undefined_panel_kappa_falls_back_to_raw_agreement(settings):
    panel = {**PANEL, "verdicts": {"fleiss": {"kappa": None, "agreement": 1.0}}}
    stage = by_id(evaluate_stages(load_catalog(settings.stages_path), {"panel": panel}))["reviewers"]
    assert stage["headline"] == "verdict agreement 100% on 20 papers" and stage["status"] == "caveat"


def test_the_stages_route_uses_the_newest_panel_report(sign_in, db, tmp_path):
    from web_fixtures import make_panel_eval

    from research_agent.web.importer.evals import import_eval_run

    folder, _gold = make_panel_eval(tmp_path)
    import_eval_run(db, folder)
    db.commit()
    viewer, _ = sign_in("viewer")
    stages = by_id(viewer.get("/api/v1/stages").json())
    assert stages["reviewers"]["headline"] == "verdict agreement 100% on 4 papers"
    assert stages["reviewers"]["caveat"] == "one model family"
