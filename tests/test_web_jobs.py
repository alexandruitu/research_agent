import threading
import time
from datetime import timedelta

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import sessionmaker

from research_agent.web.auth import create_user, utcnow
from research_agent.web.db.models import Job
from research_agent.web.jobs import claim, complete, enqueue, fail, heartbeat, requeue_stale, set_progress


@pytest.fixture
def factory(fresh_db_url):
    engine = sa.create_engine(fresh_db_url)
    yield sessionmaker(engine, expire_on_commit=False)
    engine.dispose()


@pytest.fixture
def user_ids(factory):
    with factory() as db:
        ids = [
            create_user(
                db, email=f"u{i}@example.org", name="U", role="member", password="correct horse battery"
            ).id
            for i in range(2)
        ]
        db.commit()
    return ids


def test_enqueue_is_idempotent_per_user_and_key(factory, user_ids):
    with factory() as db:
        first, created = enqueue(db, "research", {"a": 1}, user_ids[0], "key-1")
        db.commit()
        again, created_again = enqueue(db, "research", {"a": 2}, user_ids[0], "key-1")
        other, created_other = enqueue(db, "research", {"a": 3}, user_ids[1], "key-1")
        db.commit()
        assert created and not created_again and again.id == first.id and again.payload == {"a": 1}
        assert created_other and other.id != first.id
        assert db.scalar(sa.select(sa.func.count()).select_from(Job)) == 2


def test_claim_takes_the_oldest_queued_job_and_marks_it_running(factory, user_ids):
    with factory() as db:
        older, _ = enqueue(db, "research", {"n": 1}, user_ids[0])
        db.commit()
        newer, _ = enqueue(db, "research", {"n": 2}, user_ids[0])
        db.commit()
        job = claim(db, "worker-a")
        db.commit()
        assert job.id == older.id and job.status == "running" and job.locked_by == "worker-a"
        assert job.attempts == 1 and job.heartbeat_at is not None
        assert claim(db, "worker-b").id == newer.id
        db.commit()
        assert claim(db, "worker-c") is None


def test_two_workers_never_claim_the_same_job(factory, user_ids):
    with factory() as db:
        for i in range(4):
            enqueue(db, "research", {"n": i}, user_ids[0])
        db.commit()
    claimed, lock = [], threading.Lock()

    def worker(name):
        for _ in range(2):
            with factory() as db:
                job = claim(db, name)
                time.sleep(0.15)  # hold the row lock so the other worker must skip it
                db.commit()
                with lock:
                    claimed.append(job.id)

    threads = [threading.Thread(target=worker, args=(n,)) for n in ("w1", "w2")]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert len(claimed) == 4 and len(set(claimed)) == 4


def test_progress_heartbeat_complete_and_fail(factory, user_ids):
    with factory() as db:
        job, _ = enqueue(db, "research", {}, user_ids[0])
        db.commit()  # separate transactions: distinct created_at, so claim order is defined
        other, _ = enqueue(db, "research", {}, user_ids[0])
        db.commit()
        assert claim(db, "w").id == job.id
        assert set_progress(db, job, {"stages": {"plan": "completed"}}, worker_id="w") is True
        assert heartbeat(db, job, worker_id="w") is True
        assert job.progress == {"stages": {"plan": "completed"}}
        assert complete(db, job, {"result": "ok"}, worker_id="w") is True
        assert job.status == "done" and job.progress == {"result": "ok"} and job.locked_by is None
        assert claim(db, "w").id == other.id
        assert fail(db, other, "boom", worker_id="w") is True
        assert other.status == "failed" and other.error == "boom" and other.locked_by is None
        db.commit()
    with factory() as check:
        assert check.get(Job, job.id).progress == {"result": "ok"} and check.get(Job, job.id).status == "done"
        assert check.get(Job, other.id).error == "boom"


def test_a_worker_that_lost_its_job_changes_nothing(factory, user_ids):
    """Worker A's job is requeued as stale and claimed by worker B: A's late updates are no-ops."""
    now = utcnow()
    with factory() as a:
        job, _ = enqueue(a, "research", {}, user_ids[0])
        a.commit()
        claim(a, "worker-a", now=now - timedelta(minutes=10))
        a.commit()
        with factory() as b:
            requeue_stale(b, stale_after_seconds=120, max_attempts=3, now=now)
            b.commit()
            claimed = claim(b, "worker-b", now=now)
            b.commit()
            assert claimed.id == job.id and claimed.locked_by == "worker-b"
        assert set_progress(a, job, {"stages": {"x": "failed"}}, worker_id="worker-a") is False
        assert heartbeat(a, job, now=now + timedelta(minutes=5), worker_id="worker-a") is False
        assert complete(a, job, {"result": "stolen"}, worker_id="worker-a") is False
        assert fail(a, job, "late failure", worker_id="worker-a") is False
        a.commit()
    with factory() as check:
        row = check.get(Job, job.id)
        assert (row.status, row.locked_by, row.error, row.progress) == ("running", "worker-b", None, {})
        assert row.heartbeat_at == now and row.attempts == 2
        # a job that is not running cannot be completed or failed by anyone
        assert complete(check, row, worker_id="worker-b") is True
        assert fail(check, row, "after done", worker_id="worker-b") is False
        check.commit()
        assert check.get(Job, job.id).status == "done"


def test_stale_running_jobs_are_requeued_until_attempts_run_out(factory, user_ids):
    now = utcnow()
    with factory() as db:
        fresh, _ = enqueue(db, "research", {"k": "fresh"}, user_ids[0])
        stale, _ = enqueue(db, "research", {"k": "stale"}, user_ids[0])
        spent, _ = enqueue(db, "research", {"k": "spent"}, user_ids[0])
        for job, beat, attempts in (
            (fresh, now, 1),
            (stale, now - timedelta(minutes=10), 1),
            (spent, now - timedelta(minutes=10), 3),
        ):
            job.status, job.heartbeat_at, job.attempts, job.locked_by = (
                "running",
                beat,
                attempts,
                "dead-worker",
            )
        db.commit()
        changed = requeue_stale(db, stale_after_seconds=120, max_attempts=3, now=now)
        db.commit()
        assert {j.payload["k"] for j in changed} == {"stale", "spent"}
        assert (fresh.status, stale.status, spent.status) == ("running", "queued", "failed")
        assert stale.locked_by is None and "stopped responding" in spent.error


def test_claim_and_requeue_count_attempts_from_the_database_not_a_stale_session(factory, user_ids):
    """A long-lived session that still holds an old copy of the job must not reset its attempt count."""
    now = utcnow()
    with factory() as holder:
        job, _ = enqueue(holder, "research", {}, user_ids[0])
        holder.commit()  # expire_on_commit=False: holder keeps attempts == 0 in memory
        for _ in range(3):  # three other workers claim it and die; each time it is requeued
            with factory() as other:
                claim(other, "dying-worker", now=now - timedelta(minutes=10))
                other.commit()
            with factory() as other:
                requeue_stale(other, stale_after_seconds=120, max_attempts=5, now=now)
                other.commit()
        assert job.attempts == 0  # the stale in-memory copy
        claimed = claim(holder, "late-worker", now=now - timedelta(minutes=10))
        holder.commit()
        assert claimed.id == job.id and claimed.attempts == 4
        [spent] = requeue_stale(holder, stale_after_seconds=120, max_attempts=4, now=now)
        holder.commit()
        assert spent.status == "failed"
    with factory() as check:
        assert check.get(Job, job.id).attempts == 4 and check.get(Job, job.id).status == "failed"


def research_job_with_run(db, user_id, run_status="running"):
    """A research job whose payload points at a run, as `POST /runs` makes them."""
    from research_agent.web.db.models import Run
    from research_agent.web.importer.common import get_or_create_field

    field = get_or_create_field(db, "a topic", user_id)
    run = Run(field_id=field.id, kind="research", status=run_status, manifest={}, created_by=user_id)
    db.add(run)
    db.flush()
    job, _ = enqueue(db, "research", {"run_id": str(run.id)}, user_id)
    return job, run


def test_requeue_stale_moves_the_run_with_its_job(factory, user_ids):
    """A requeued job's run is queued again; a job that runs out of attempts fails its run too."""
    from research_agent.web.db.models import Run

    now = utcnow()
    with factory() as db:
        again, again_run = research_job_with_run(db, user_ids[0])
        spent, spent_run = research_job_with_run(db, user_ids[0])
        for job, attempts in ((again, 1), (spent, 3)):
            job.status, job.attempts, job.locked_by = "running", attempts, "dead-worker"
            job.heartbeat_at = now - timedelta(minutes=10)
        db.commit()
        requeue_stale(db, stale_after_seconds=120, max_attempts=3, now=now)
        db.commit()
    with factory() as check:
        assert check.get(Job, again.id).status == "queued" and check.get(Run, again_run.id).status == "queued"
        job, run = check.get(Job, spent.id), check.get(Run, spent_run.id)
        assert job.status == run.status == "failed" and run.error == job.error
        assert "stopped responding" in run.error


def test_release_gives_the_job_back_without_counting_an_attempt(factory, user_ids):
    from research_agent.web.db.models import Run
    from research_agent.web.jobs import release

    with factory() as db:
        job, run = research_job_with_run(db, user_ids[0], run_status="queued")
        db.commit()
        assert claim(db, "w").id == job.id and job.attempts == 1
        run.status = "running"
        db.commit()
        assert release(db, job, worker_id="someone-else") is False
        assert release(db, job, worker_id="w") is True
        db.commit()
    with factory() as check:
        row = check.get(Job, job.id)
        assert (row.status, row.locked_by, row.attempts) == ("queued", None, 0)
        assert check.get(Run, run.id).status == "queued"


def test_heartbeats_use_the_database_clock(factory, user_ids):
    """Every worker stamps and compares heartbeats with PostgreSQL's clock, not its own."""
    with factory() as db:
        enqueue(db, "import", {}, user_ids[0])
        db.commit()
        job = claim(db, "w")
        assert job.heartbeat_at == db.scalar(sa.select(sa.func.now()))  # same transaction: same now()
        db.commit()
        assert heartbeat(db, job, worker_id="w") is True
        assert job.heartbeat_at == db.scalar(sa.select(sa.func.now()))
        db.commit()


def test_a_worker_with_a_fast_clock_does_not_steal_a_live_job(factory, user_ids, monkeypatch):
    import research_agent.web.jobs as jobs_module

    with factory() as db:
        enqueue(db, "import", {}, user_ids[0])
        db.commit()
        job = claim(db, "w")
        db.commit()
    monkeypatch.setattr(  # a host whose clock runs an hour fast
        jobs_module, "utcnow", lambda: utcnow() + timedelta(hours=1), raising=False
    )
    with factory() as db:
        assert requeue_stale(db, stale_after_seconds=120, max_attempts=3) == []
        db.commit()
        assert db.get(Job, job.id).status == "running"
