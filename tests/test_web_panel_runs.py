"""Panel runs: review.json frozen at start, written by the worker with the uploads, imported, and shown."""

import json
import uuid

import sqlalchemy as sa

from research_agent.panel import DEFAULT_PANEL
from research_agent.schemas import Contract, ReviewSpec, read_review
from research_agent.web.db.models import Job, Paper, Run, RunReviewer
from research_agent.web.runner import RunSpec, build_command
from research_agent.web.worker import REVIEW_REQUEST, Worker

API = "/api/v1"
TOPIC = "retrieval augmented generation"
PDF = b"%PDF-1.4\n%%EOF\n"


class Done:
    returncode = 0

    def poll(self):
        return 0


def legacy_field(factory):
    from research_agent.web.importer.common import get_or_create_field

    with factory() as db:
        field_id = str(get_or_create_field(db, TOPIC).id)
        db.commit()
    return field_id


def start(sign_in, field_id, role="member"):
    client, csrf = sign_in(role)
    body = {"field_id": field_id, "max_papers": 3, "mode": "demo"}
    r = client.post(f"{API}/runs", json=body, headers=csrf)
    assert r.status_code == 202, r.text
    return r.json()


def capture_spawn(captured):
    def spawn(spec, env, log):
        captured.append(spec)
        return Done()

    return spawn


def test_start_freezes_the_current_settings_and_default_panel(world):
    _settings, factory, sign_in = world
    started = start(sign_in, legacy_field(factory))
    with factory() as db:
        run = db.get(Run, uuid.UUID(started["run_id"]))
        job = db.get(Job, uuid.UUID(started["job"]["id"]))
        review = run.manifest["review_request"]
        assert job.payload["review"] == review and run.settings_version_id is not None
        links = db.scalars(sa.select(RunReviewer).where(RunReviewer.run_id == run.id)).all()
        assert [link.position for link in links] == [0, 1, 2]
    spec = ReviewSpec.model_validate(review)  # the pipeline's own validation
    assert [(r.key, r.version) for r in spec.panel] == [(r["key"], 1) for r in DEFAULT_PANEL]
    assert review["fulltext"] == {"sources": ["pmc_oa", "upload"], "contact": None, "max_chars": 60000}
    assert review["screening"]["keep_min"] == 0.8 and review["schema"] == 1
    member, _ = sign_in("member")
    assert member.get(f"{API}/runs/{started['run_id']}").json()["settings_version"] == 1

    admin, csrf = sign_in("admin")
    reviewer = admin.get(f"{API}/reviewers/statistician").json()["current"]
    save = {k: reviewer[k] for k in ("name", "perspective", "model", "items")}
    save |= {"model": "openai:gpt-x", "base_version": 1, "note": "model"}
    assert admin.post(f"{API}/reviewers/statistician/versions", json=save, headers=csrf).status_code == 201
    settings = admin.get(f"{API}/settings/review").json()["current"]
    change = {k: settings[k] for k in ("models", "screening", "fulltext", "editor")}
    change |= {"default_panel": ["statistician"], "base_version": 1, "note": ""}
    assert admin.post(f"{API}/settings/review", json=change, headers=csrf).status_code == 201
    started = start(sign_in, legacy_field(factory))
    with factory() as db:
        review = db.get(Run, uuid.UUID(started["run_id"])).manifest["review_request"]
    assert [(r["key"], r["version"], r["model"]) for r in review["panel"]] == [
        ("statistician", 2, "openai:gpt-x")
    ]
    assert member.get(f"{API}/reviewers/statistician/versions/2").json()["run_count"] == 1
    assert member.get(f"{API}/settings/review").json()["current"]["run_count"] == 1


def test_the_worker_writes_review_json_and_the_uploads(world, monkeypatch):
    settings, factory, sign_in = world
    started = start(sign_in, legacy_field(factory))
    with factory() as db:
        paper = Paper(source_id="MED:7", title="t", abstract="a")
        db.add(paper)
        db.commit()
        paper_id = paper.id
    member, csrf = sign_in("member")
    r = member.post(f"{API}/papers/{paper_id}/files", files={"file": ("p.pdf", PDF)}, headers=csrf)
    assert r.status_code == 201, r.text
    captured = []
    monkeypatch.setattr("research_agent.web.worker.import_research_run", lambda *a, **k: None)
    Worker(settings, factory, spawn=capture_spawn(captured), sleep=lambda s: None).tick()
    [spec] = captured
    assert spec.resume is False and spec.review_file == spec.run_dir / REVIEW_REQUEST
    with factory() as db:
        request = db.get(Run, uuid.UUID(started["run_id"])).manifest["review_request"]
    assert json.loads(spec.review_file.read_text()) == request
    assert read_review(spec.review_file).panel[0].key == "methodologist"
    command = build_command(spec)
    assert command[command.index("--review") + 1] == str(spec.review_file)
    assert command[-2:] == ["--", TOPIC]
    assert (spec.run_dir / "uploads" / "MED_7.pdf").read_bytes() == PDF


def test_resume_carries_the_review_request(world):
    settings, factory, sign_in = world
    run_id = uuid.UUID(start(sign_in, legacy_field(factory))["run_id"])
    with factory() as db:
        run = db.get(Run, run_id)
        run.status = "failed"
        for job in db.scalars(sa.select(Job)):
            job.status = "failed"
        db.commit()
    member, csrf = sign_in("member")
    r = member.post(f"{API}/runs/{run_id}/resume", headers=csrf)
    with factory() as db:
        job = db.get(Job, uuid.UUID(r.json()["job"]["id"]))
        assert job.payload["review"] == db.get(Run, run_id).manifest["review_request"]
    captured = []
    Worker(settings, factory, spawn=capture_spawn(captured), sleep=lambda s: None).tick()
    assert captured[0].review_file.name == REVIEW_REQUEST  # no manifest yet: start again


def test_build_command_never_combines_review_with_resume(tmp_path):
    spec = RunSpec(
        topic=TOPIC,
        max_papers=3,
        mode="demo",
        jev=False,
        resume=True,
        run_dir=tmp_path,
        review_file=None,
    )
    assert "--review" not in build_command(spec)


def test_contract_accepts_the_web_review(world):
    _settings, factory, sign_in = world
    started = start(sign_in, legacy_field(factory))
    with factory() as db:
        review = db.get(Run, uuid.UUID(started["run_id"])).manifest["review_request"]
    Contract(topic=TOPIC, review=ReviewSpec.model_validate(review))


def pipeline_spawn(spec, env, log):
    """The real pipeline in demo mode, in-process (as the child would run it), with the review request."""
    from research_agent.runner import run_research

    review = read_review(spec.review_file)
    contract = Contract(topic=spec.topic, review=review, mode=spec.mode, max_papers=spec.max_papers)
    run_research(spec.run_dir, contract=contract, review_file=spec.review_file)
    return Done()


def make_panel_run(directory, review=None, red_flag=False):
    """A demo panel run folder (optionally with a red flag written into its report, as demo answers have none)."""
    from research_agent.panel import default_review
    from research_agent.runner import run_research

    spec = ReviewSpec.model_validate(review or default_review())
    run_research(directory, contract=Contract(topic=TOPIC, mode="demo", max_papers=3, review=spec))
    if red_flag:
        path = directory / "report.json"
        data = json.loads(path.read_text())
        entry = data["state"]["review"]["demo:2"]
        answer = entry["reviews"]["methodologist"]["answers"][0]
        entry["red_flags"] = [
            {
                "text": "Data were partitioned at patient level.",
                "source": "CLAIM 2020 #21",
                "raised_by": [{"reviewer": "methodologist", "item": answer["key"], **answer}],
            }
        ]
        path.write_text(json.dumps(data))
    return directory


def counts(db, run_id):
    from research_agent.web.db.models import PanelReport, PaperReview, RedFlag

    reviews = db.scalars(sa.select(PaperReview).where(PaperReview.run_id == run_id)).all()
    ids = [r.id for r in reviews]
    reports = db.scalars(sa.select(PanelReport).where(PanelReport.paper_review_id.in_(ids))).all()
    flags = db.scalars(sa.select(RedFlag).where(RedFlag.paper_review_id.in_(ids))).all()
    return reviews, reports, flags


def test_a_panel_run_through_the_worker_imports_its_reviews(world):
    settings, factory, sign_in = world
    started = start(sign_in, legacy_field(factory))
    Worker(settings, factory, spawn=pipeline_spawn, sleep=lambda s: None).tick()
    run_id = uuid.UUID(started["run_id"])
    with factory() as db:
        run = db.get(Run, run_id)
        assert run.status == "done", run.error
        reviews, reports, flags = counts(db, run_id)
        assert len(reviews) == 3 and len(reports) == 9 and flags == []
        first = max(reviews, key=lambda r: r.score or 0)
        assert first.text_source == "abstract" and first.editor_verdict and first.editor_call_key
        assert all(r.call_key and r.reviewer_version_id for r in reports)
        assert {r.reviewer_key for r in reports} == {"methodologist", "clinician", "statistician"}
        from research_agent.web.db.models import ReviewerVersion, SettingsVersion

        # linked at start: no imported versions were made
        assert db.scalar(sa.select(sa.func.count()).select_from(SettingsVersion)) == 1
        assert db.scalar(sa.select(sa.func.count()).select_from(ReviewerVersion)) == 3


def test_import_links_by_content_and_reimport_is_unchanged(db, tmp_path):
    from research_agent.panel import default_review
    from research_agent.web.db.models import ReviewerVersion, SettingsVersion
    from research_agent.web.importer.research import import_research_run

    folder = make_panel_run(tmp_path / "runs" / "p1", red_flag=True)
    result = import_research_run(db, folder)
    assert result.status == "created"
    run = db.get(Run, result.run_id)
    settings_row = db.get(SettingsVersion, run.settings_version_id)
    assert settings_row.version == 1 and not settings_row.imported  # same content as the seed
    reviews, reports, flags = counts(db, run.id)
    assert (len(reviews), len(reports), len(flags)) == (3, 9, 1)
    flagged = [r for r in reviews if r.red_flag_count]
    assert len(flagged) == 1 and flags[0].source == "CLAIM 2020 #21"
    assert flags[0].raised_by[0]["reviewer"] == "methodologist"
    assert import_research_run(db, folder).status == "unchanged"

    review = default_review(contact="team@example.org")
    review["panel"][0]["items"][0]["text"] = "A changed item text."
    review["panel"] = review["panel"][:1] + [dict(review["panel"][1], key="newcomer", name="Newcomer")]
    other = import_research_run(db, make_panel_run(tmp_path / "runs" / "p2", review=review))
    run = db.get(Run, other.run_id)
    settings_row = db.get(SettingsVersion, run.settings_version_id)
    assert settings_row.imported and settings_row.version == 2 and settings_row.note == "imported"
    assert settings_row.default_panel == ["methodologist", "newcomer"]
    notes = dict(
        db.execute(
            sa.select(ReviewerVersion.name, ReviewerVersion.note).where(ReviewerVersion.version > 1)
        ).all()
    )
    assert notes == {"Methodologist": "imported"}
    from research_agent.web.review import current_settings, get_profile

    assert current_settings(db).version == 1  # an imported version never becomes current
    assert get_profile(db, "newcomer").current_version == 1
    assert get_profile(db, "methodologist").current_version == 1


def test_paper_table_and_drawer_show_the_panel(db, tmp_path, sign_in, settings):
    from research_agent.web.importer.research import import_research_run

    run_id = import_research_run(db, make_panel_run(settings.runs_dir / "p1", red_flag=True)).run_id
    db.commit()
    viewer, _ = sign_in("viewer")
    page = viewer.get(f"{API}/runs/{run_id}/papers?sort=score&direction=desc").json()
    rows = page["items"]
    assert page["total"] == 3
    scores = [r["score"] for r in rows]
    assert scores == sorted(scores, reverse=True) and all(s is not None for s in scores)
    assert all(r["text_source"] == "abstract" and 0 <= r["coverage"] <= 1 for r in rows)
    assert sorted(r["red_flag_count"] for r in rows) == [0, 0, 1]
    flagged = viewer.get(f"{API}/runs/{run_id}/papers?has_red_flags=true").json()["items"]
    assert [r["paper"]["source_id"] for r in flagged] == ["demo:2"]
    clean = viewer.get(f"{API}/runs/{run_id}/papers?has_red_flags=false").json()["items"]
    assert sorted(r["paper"]["source_id"] for r in clean) == ["demo:1", "demo:3"]

    paper_id = flagged[0]["paper"]["id"]
    member, csrf = sign_in("member")
    upload = member.post(f"{API}/papers/{paper_id}/files", files={"file": ("p.pdf", PDF)}, headers=csrf)
    assert upload.status_code == 201
    drawer = viewer.get(f"{API}/runs/{run_id}/papers/{paper_id}").json()
    panel = drawer["panel"]
    assert panel["text_source"] == "abstract" and panel["red_flag_count"] == 1
    assert panel["text_reason"] == "pmc_oa: no PMCID; upload: no uploaded PDF"
    assert panel["editor"]["verdict"] and panel["editor"]["call_key"]
    assert [r["key"] for r in panel["reviews"]] == ["methodologist", "clinician", "statistician"]
    first = panel["reviews"][0]["answers"][0]
    item = DEFAULT_PANEL[0]["items"][0]
    assert (first["key"], first["text"], first["source"], first["weight"]) == (
        item["key"],
        item["text"],
        item["source"],
        item["weight"],
    )
    assert panel["red_flags"][0]["raised_by"][0]["reviewer"] == "methodologist"
    [listed] = drawer["files"]
    assert listed["filename"] == "p.pdf" and listed["can_delete"] is False  # the viewer did not upload it
    call = member.get(f"{API}/runs/{run_id}/calls/{panel['reviews'][0]['call_key']}").json()
    assert call["role"] == "review:methodologist"


def test_legacy_runs_have_no_panel(sign_in, imported):
    viewer, _ = sign_in("viewer")
    rows = viewer.get(f"{API}/runs/{imported['research']}/papers").json()["items"]
    assert all(r["score"] is None and r["red_flag_count"] is None for r in rows)
    paper_id = rows[0]["paper"]["id"]
    drawer = viewer.get(f"{API}/runs/{imported['research']}/papers/{paper_id}").json()
    assert drawer["panel"] is None and drawer["files"] == []
