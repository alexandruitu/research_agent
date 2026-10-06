"""Cancelling a research run: a queued job is cancelled at once; a running one is stopped by its worker."""

from datetime import timedelta

from test_web_worker import FakeProcess, env, queue_run  # noqa: F401 -- `env` is a fixture

from research_agent.web.auth import utcnow
from research_agent.web.db.models import Job, Run
from research_agent.web.jobs import claim, request_cancel, requeue_stale
from research_agent.web.worker import Worker


def test_a_queued_run_is_cancelled_at_once_and_never_claimed(env):  # noqa: F811
    settings, factory, _ = env
    job_id, run_id, _ = queue_run(factory, settings)
    with factory() as db:
        assert request_cancel(db, run_id) == "cancelled"
        db.commit()
    with factory() as db:
        job, run = db.get(Job, job_id), db.get(Run, run_id)
        assert job.status == "cancelled" and run.status == "cancelled" and run.finished_at is not None
        assert claim(db, "w1") is None
        assert request_cancel(db, run_id) is None  # nothing active any more


def test_a_running_run_is_stopped_by_its_worker_and_stays_resumable(env):  # noqa: F811
    settings, factory, _ = env
    job_id, run_id, folder = queue_run(factory, settings)
    child = FakeProcess(0, polls=10_000)

    def spawn(spec, env_, log):
        spec.run_dir.mkdir(parents=True, exist_ok=True)
        (spec.run_dir / "manifest.json").write_text("{}")  # the checkpoint the pipeline would have saved
        return child

    polls = {"n": 0}

    def sleep(_seconds):
        polls["n"] += 1
        if polls["n"] == 2:  # the user presses Cancel while the run is going
            with factory() as other:
                assert request_cancel(other, run_id) == "requested"
                other.commit()

    Worker(settings, factory, spawn=spawn, sleep=sleep).tick()
    assert child.terminated
    with factory() as db:
        job, run = db.get(Job, job_id), db.get(Run, run_id)
        assert job.status == "cancelled" and job.locked_by is None
        assert run.status == "cancelled" and run.error is None and run.finished_at is not None
        assert run.started_at is not None
    assert (folder / "manifest.json").exists()


def test_a_stale_job_with_a_cancel_request_is_cancelled_not_requeued(env):  # noqa: F811
    settings, factory, _ = env
    job_id, run_id, _ = queue_run(factory, settings)
    with factory() as db:
        claim(db, "w1", now=utcnow() - timedelta(hours=1))
        assert request_cancel(db, run_id) == "requested"
        requeue_stale(db, 60, 3)
        db.commit()
        assert db.get(Job, job_id).status == "cancelled" and db.get(Run, run_id).status == "cancelled"
