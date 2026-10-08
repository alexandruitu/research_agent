"""Field alerts: API and role guards, seen set, scheduler (fake clock), digests, failures and the daily budget."""

import json
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import sqlalchemy as sa

from research_agent.runner import run_research
from research_agent.schemas import Contract, read_domain, read_review
from research_agent.web import alerts as svc
from research_agent.web.auth import create_user
from research_agent.web.db.models import (
    Alert,
    AppSettings,
    Digest,
    Job,
    LibraryItem,
    Paper,
    Run,
    Screening,
)
from research_agent.web.papers import PaperQuery, _filtered
from research_agent.web.worker import Worker

API = "/api/v1"
PASSWORD = "correct horse battery"
DRAFT = {
    "name": "ML CT-FFR",
    "topic": "machine learning estimation of CT-derived fractional flow reserve",
    "include": [{"text": "The study uses machine learning."}],
    "exclude": [{"text": "The paper is a review without original results."}],
    "sources": ["europepmc"],
    "years": {"from": 2018, "to": None},
}
NOW = datetime(2026, 10, 8, 12, 0, tzinfo=UTC)


class Done:
    def __init__(self, code=0):
        self.returncode = code

    def poll(self):
        return self.returncode


def pipeline_spawn(spec, env, log):
    """The real pipeline in demo mode, in-process, with the domain, review and seen requests."""
    domain = read_domain(spec.domain_file)
    review = read_review(spec.review_file) if spec.review_file else None
    contract = Contract(
        topic=domain.topic, domain=domain, review=review, mode=spec.mode, max_papers=spec.max_papers
    )
    run_research(
        spec.run_dir,
        contract=contract,
        domain_file=spec.domain_file,
        review_file=spec.review_file,
        seen_file=spec.seen_file,
    )
    return Done()


def failing_spawn(spec, env, log):
    spec.run_dir.mkdir(parents=True, exist_ok=True)
    (spec.run_dir / "progress.json").write_text(
        json.dumps(
            {"status": "failed", "stages": {"discover": "failed"}, "error_type": "X", "message": "boom"}
        )
    )
    return Done(1)


def add_user(factory, role, email):
    with factory() as db:
        create_user(db, email=email, name=email, role=role, password=PASSWORD)
        db.commit()


def new_field(sign_in, name="ML CT-FFR"):
    member, csrf = sign_in("member")
    r = member.post(f"{API}/fields", json={**DRAFT, "name": name}, headers=csrf)
    assert r.status_code == 201, r.text
    return r.json()["id"]


def put_alert(sign_in, field_id, role="member", **body):
    client, csrf = sign_in(role)
    return client.put(f"{API}/fields/{field_id}/alert", json=body, headers=csrf)


def alert_of(db, field_id):
    return db.scalar(sa.select(Alert).where(Alert.field_id == uuid.UUID(field_id)))


def test_get_put_alert_and_role_guards(world):
    _settings, factory, sign_in = world
    add_user(factory, "viewer", "viewer@example.org")
    add_user(factory, "member", "member2@example.org")
    field_id = new_field(sign_in)
    viewer, vcsrf = sign_in("viewer")
    body = viewer.get(f"{API}/fields/{field_id}/alert").json()
    assert body["exists"] is False and body["enabled"] is False and body["max_new"] == 50
    assert viewer.put(f"{API}/fields/{field_id}/alert", json={}, headers=vcsrf).status_code == 403

    r = put_alert(sign_in, field_id, cadence="daily", hour=6, max_new=20, min_group="read_first")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["exists"] and body["enabled"] and body["subscribed"] and body["subscriber_count"] == 1
    assert body["cadence"] == "daily" and body["next_run_at"] and body["can_edit"]
    assert body["effective_max_new"] == 12  # the deployment's max papers per run
    assert put_alert(sign_in, field_id, role="member2").status_code == 403  # not the creator
    assert put_alert(sign_in, field_id, role="admin", enabled=False).json()["next_run_at"] is None
    assert put_alert(sign_in, field_id, max_new=500).status_code == 422

    member2, csrf2 = sign_in("member2")
    alert_id = body["id"]
    assert member2.post(f"{API}/alerts/{alert_id}/subscription", headers=csrf2).json()["subscribed"]
    assert member2.get(f"{API}/fields/{field_id}/alert").json()["subscriber_count"] == 2
    assert viewer.post(f"{API}/alerts/{alert_id}/subscription", headers=vcsrf).status_code == 403
    assert not member2.delete(f"{API}/alerts/{alert_id}/subscription", headers=csrf2).json()["subscribed"]
    assert viewer.post(f"{API}/fields/{field_id}/alert/run-now", json={}, headers=vcsrf).status_code == 403
    assert viewer.get(f"{API}/digests?scope=all").status_code == 403


def test_seen_records_are_finished_runs_of_the_field_and_the_library(world):
    _settings, factory, sign_in = world
    field_id, other_id = uuid.UUID(new_field(sign_in)), uuid.UUID(new_field(sign_in, "Other"))
    with factory() as db:
        papers = [Paper(source_id=f"MED:{n}", doi=f"10.1/{n}", title=f"T{n}", year=2026) for n in range(5)]
        db.add_all(papers)
        runs = [
            Run(field_id=field_id, kind="research", status="done", manifest={}),
            Run(field_id=field_id, kind="research", status="failed", manifest={}),
            Run(field_id=other_id, kind="research", status="done", manifest={}),
        ]
        db.add_all(runs)
        db.flush()
        for run, p in zip(runs, papers, strict=False):
            db.add(Screening(run_id=run.id, paper_id=p.id, tier="llm", decision="include"))
        db.add(LibraryItem(paper_id=papers[3].id, snapshot={}))
        db.commit()
        got = {r["source_id"] for r in svc.seen_records(db, field_id)}
    assert got == {"MED:0", "MED:3"}  # done run of this field + library; not failed runs or other fields


def run_now(sign_in, field_id, role="member"):
    client, csrf = sign_in(role)
    r = client.post(f"{API}/fields/{field_id}/alert/run-now", json={"mode": "demo"}, headers=csrf)
    assert r.status_code == 202, r.text
    return uuid.UUID(r.json()["run_id"])


def test_an_alert_run_skips_seen_papers_and_builds_a_digest(world):
    settings, factory, sign_in = world
    field_id = new_field(sign_in)
    put_alert(sign_in, field_id, min_group="worth_a_look", max_new=50)
    worker = Worker(settings, factory, spawn=pipeline_spawn, sleep=lambda s: None)
    first = run_now(sign_in, field_id)
    with factory() as db:
        run = db.get(Run, first)
        assert run.trigger == "alert"
        this_year = datetime.now(UTC).astimezone().year
        assert run.manifest["domain_request"]["years"] == {"from": this_year - 1, "to": this_year}
    assert worker.tick() is True
    with factory() as db:
        run = db.get(Run, first)
        assert run.status == "done", run.error
        digest = db.scalar(sa.select(Digest).where(Digest.run_id == first))
        counts = digest.counts
        assert (
            digest.status == "done" and counts["already_seen"] == 0 and counts["new"] == counts["found"] > 0
        )
        assert counts["in_digest"] == len(digest.items)
        assert (Path(run.folder) / "seen.json").exists()
        # the group filter equals the Papers rules (quality_expr) for this run
        groups = {str(r[1].id): r[-1] for r in db.execute(_filtered(run, PaperQuery())[0]).all()}
        for min_group, wanted in svc.MIN_GROUPS.items():
            items = svc.digest_items(db, run, min_group)
            assert {i["paper_id"] for i in items} == {p for p, g in groups.items() if g in wanted}
            assert all(i["why"] and i["group"] in wanted for i in items)
    member, _ = sign_in("member")
    listed = {r["id"]: r for r in member.get(f"{API}/runs").json()}
    assert listed[str(first)]["trigger"] == "alert"

    second = run_now(sign_in, field_id)
    assert worker.tick() is True
    with factory() as db:
        digest = db.scalar(sa.select(Digest).where(Digest.run_id == second))
        assert digest.counts["new"] == 0 and digest.counts["already_seen"] == digest.counts["found"]
        assert digest.items == [] and db.get(Run, second).status == "done"


def test_failed_alert_runs_produce_failed_digests_and_pause_after_three(world):
    settings, factory, sign_in = world
    field_id = new_field(sign_in)
    put_alert(sign_in, field_id)
    worker = Worker(settings, factory, spawn=failing_spawn, sleep=lambda s: None)
    for n in range(3):
        run_now(sign_in, field_id)
        worker.tick()
        with factory() as db:
            alert = alert_of(db, field_id)
            assert alert.failures == n + 1 and alert.enabled is (n < 2)
    with factory() as db:
        digests = db.scalars(sa.select(Digest)).all()
        assert [d.status for d in digests] == ["failed"] * 3 and all("boom" in d.reason for d in digests)
        assert "Paused after 3 failed runs" in alert_of(db, field_id).paused_reason
    member, _ = sign_in("member")
    body = member.get(f"{API}/fields/{field_id}/alert").json()
    assert body["enabled"] is False and body["paused_reason"]
    turned_on = put_alert(sign_in, field_id, enabled=True).json()
    assert turned_on["paused_reason"] is None and turned_on["failures"] == 0 and turned_on["next_run_at"]


def make_due(factory, field_id, when):
    with factory() as db:
        alert = alert_of(db, field_id)
        alert.next_run_at = when
        db.commit()
        return alert.id


def jobs(db):
    return db.scalars(sa.select(Job).where(Job.kind == "research")).all()


def test_the_scheduler_is_idempotent_and_runs_a_missed_slot_once(world):
    settings, factory, sign_in = world
    field_id = new_field(sign_in)
    put_alert(sign_in, field_id, cadence="weekly", weekday=0, hour=7)
    slot = NOW - timedelta(weeks=3)  # three missed weeks (server off)
    make_due(factory, field_id, slot)
    worker = Worker(settings, factory, spawn=failing_spawn, sleep=lambda s: None, clock=lambda: NOW)
    for _ in range(2):  # two ticks at the same moment
        with factory() as db:
            worker.schedule_alerts(db)
    with factory() as db:
        [job] = jobs(db)
        alert = alert_of(db, field_id)
        assert job.idempotency_key == f"alert:{alert.id}:{slot.isoformat()}"
        assert job.payload["alert_id"] == str(alert.id)
        assert NOW < alert.next_run_at <= NOW + timedelta(days=7)  # once, no backlog
        local = alert.next_run_at.astimezone()
        assert (local.weekday(), local.hour, local.minute) == (0, 7, 0)
    make_due(factory, field_id, slot)  # e.g. a second worker that read the old slot
    with factory() as db:
        assert svc.schedule_due(db, settings, NOW) == []  # same key: the same job, no second run
        db.commit()
        assert len(jobs(db)) == 1 and db.scalar(sa.select(sa.func.count()).select_from(Run)) == 1


def test_next_slot_daily_and_weekly():
    after = datetime(2026, 10, 8, 9, 30).astimezone()  # a Thursday, server local time

    def wall(*args):
        return svc.next_slot(*args, after).strftime("%Y-%m-%d %H:%M")

    assert wall("daily", 0, 10) == "2026-10-08 10:00"
    assert wall("daily", 0, 9) == "2026-10-09 09:00"
    assert wall("weekly", 0, 7) == "2026-10-12 07:00"
    assert wall("weekly", 3, 9) == "2026-10-15 09:00"


def test_the_daily_budget_defers_extra_alerts_to_the_next_day(world):
    settings, factory, sign_in = world
    fields = [new_field(sign_in, f"F{n}") for n in range(2)]
    for field_id in fields:
        put_alert(sign_in, field_id, cadence="daily", hour=7)
        make_due(factory, field_id, NOW - timedelta(hours=1))
    with factory() as db:
        db.get(AppSettings, 1).alerts_max_runs_per_day = 1
        db.commit()
        started = svc.schedule_due(db, settings, NOW)
        db.commit()
        assert len(started) == 1 and len(jobs(db)) == 1
        waiting = next(alert_of(db, f) for f in fields if alert_of(db, f).id not in started)
        assert waiting.deferred_at is not None
        local = waiting.next_run_at.astimezone()
        assert local.date() == (NOW.astimezone() + timedelta(days=1)).date() and local.hour == 7
        assert svc.schedule_due(db, settings, NOW) == []  # nothing due any more today
    later = NOW + timedelta(days=1, hours=12)
    with factory() as db:
        waiting = db.get(Alert, waiting.id)
        waiting.next_run_at = later - timedelta(minutes=1)
        db.commit()
        assert svc.schedule_due(db, settings, later) == [waiting.id]  # a new day, a new budget
        db.commit()
        job = next(j for j in jobs(db) if j.payload["alert_id"] == str(waiting.id))
        assert job.payload["deferred"] is True and db.get(Alert, waiting.id).deferred_at is None


def test_digests_inbox_unread_counts_and_reads(world):
    _settings, factory, sign_in = world
    add_user(factory, "member", "member2@example.org")
    field_id = new_field(sign_in)
    alert_id = put_alert(sign_in, field_id).json()["id"]
    with factory() as db:
        alert = db.get(Alert, uuid.UUID(alert_id))
        svc.record_failure(db, alert, None, "no source")
        db.add(Digest(alert_id=alert.id, status="done", counts={"new": 0}, items=[]))
        db.commit()
    member, csrf = sign_in("member")
    body = member.get(f"{API}/digests").json()
    assert body["unread"] == 2 and len(body["digests"]) == 2
    assert body["digests"][0]["field_name"] == "ML CT-FFR"
    digest_id = body["digests"][0]["id"]
    assert member.post(f"{API}/digests/{digest_id}/read", headers=csrf).json()["read"] is True
    body = member.get(f"{API}/digests?unread=1").json()
    assert body["unread"] == 1 and [d["id"] for d in body["digests"]] != [digest_id]
    assert member.get(f"{API}/digests/{digest_id}").json()["read"] is True

    other, _ = sign_in("member2")  # does not follow the alert
    assert other.get(f"{API}/digests").json() == {"unread": 0, "digests": []}
    admin, _ = sign_in("admin")
    assert len(admin.get(f"{API}/digests?scope=all").json()["digests"]) == 2
