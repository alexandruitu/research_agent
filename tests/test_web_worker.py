import itertools
import json
import time
from dataclasses import replace
from datetime import timedelta
from pathlib import Path

import pytest
import sqlalchemy as sa
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker
from web_fixtures import make_demo_run, make_eval_run

from research_agent.web.auth import create_user, utcnow
from research_agent.web.db.models import Job, Paper, Run, Screening
from research_agent.web.importer.common import get_or_create_field
from research_agent.web.jobs import claim, enqueue, requeue_stale
from research_agent.web.settings import load_settings
from research_agent.web.worker import Worker

TOPIC = "retrieval augmented generation"


class FakeProcess:
    """Stands in for the pipeline child: finishes after `polls` polls with `code`."""

    def __init__(self, code, polls=1, on_poll=None):
        self.code, self.polls, self.on_poll, self.returncode = code, polls, on_poll, None
        self.terminated = self.killed = False

    def poll(self):
        if self.returncode is not None:
            return self.returncode
        if self.on_poll:
            self.on_poll()
        self.polls -= 1
        if self.polls <= 0:
            self.returncode = self.code
            return self.code
        return None

    def terminate(self):
        self.terminated, self.returncode = True, -15

    def kill(self):
        self.killed, self.returncode = True, -9

    def wait(self, timeout=None):
        return self.returncode


@pytest.fixture
def env(fresh_db_url, tmp_path):
    settings = load_settings(
        {
            "RESEARCH_WEB_DATABASE_URL": fresh_db_url,
            "RESEARCH_RUNS_DIR": str(tmp_path / "runs"),
            "RESEARCH_EVALS_DIR": str(tmp_path / "evals"),
            "RESEARCH_GOLD_DIR": str(tmp_path / "gold"),
            "RESEARCH_WEB_ALLOW_DEMO": "true",
            "RESEARCH_WEB_WORKER_POLL_SECONDS": "0.01",
            "RESEARCH_WEB_PROGRESS_POLL_SECONDS": "0.01",
        }
    )
    engine = sa.create_engine(fresh_db_url)
    factory = sessionmaker(engine, expire_on_commit=False)
    yield settings, factory, tmp_path
    engine.dispose()


def queue_run(factory, settings, max_papers=3, mode="demo", existing_dir=None):
    """A queued research run + job, as `POST /runs` will create them."""
    with factory() as db:
        user = create_user(
            db, email="m@example.org", name="M", role="member", password="correct horse battery"
        )
        field = get_or_create_field(db, TOPIC, user.id)
        run = Run(field_id=field.id, kind="research", status="queued", manifest={}, created_by=user.id)
        db.add(run)
        db.flush()
        run.folder = str(existing_dir or settings.runs_dir / run.id.hex)
        payload = {
            "run_id": str(run.id),
            "field_id": str(field.id),
            "topic": TOPIC,
            "max_papers": max_papers,
            "mode": mode,
            "resume": False,
        }
        job, _ = enqueue(db, "research", payload, user.id)
        db.commit()
        return job.id, run.id, Path(run.folder)


def demo_spawn(spec, env_, log):
    make_demo_run(spec.run_dir, topic=spec.topic, max_papers=spec.max_papers)
    return FakeProcess(0)


def test_a_finished_run_is_imported_and_the_job_completes(env):
    settings, factory, _ = env
    job_id, run_id, _folder = queue_run(factory, settings)
    worker = Worker(settings, factory, spawn=demo_spawn, sleep=lambda s: None)
    assert worker.tick() is True
    with factory() as db:
        job, run = db.get(Job, job_id), db.get(Run, run_id)
        assert job.status == "done" and job.locked_by is None and job.attempts == 1
        assert run.status == "done" and run.error is None and run.manifest["prompt_version"]
        assert (
            db.scalar(select(sa.func.count()).select_from(Screening).where(Screening.run_id == run_id)) == 3
        )
    assert worker.tick() is False  # nothing left to do


def test_a_failed_run_records_a_safe_message_and_keeps_the_checkpoint(env):
    settings, factory, _ = env
    job_id, run_id, folder = queue_run(factory, settings)

    def failing_spawn(spec, env_, log):
        spec.run_dir.mkdir(parents=True, exist_ok=True)
        (spec.run_dir / "manifest.json").write_text("{}")
        (spec.run_dir / "progress.json").write_text(
            json.dumps(
                {
                    "status": "failed",
                    "stages": {"plan": "completed", "screen": "failed"},
                    "error_type": "ValidationError",
                    "message": "Etapa nu s-a încheiat.",
                }
            )
        )
        Path(log).write_text("Traceback ... sk-ant-SHOULD-NEVER-REACH-THE-DATABASE")
        return FakeProcess(1)

    Worker(settings, factory, spawn=failing_spawn, sleep=lambda s: None).tick()
    with factory() as db:
        job, run = db.get(Job, job_id), db.get(Run, run_id)
        assert job.status == "failed" and run.status == "failed"
        assert job.error == run.error == "failed at stage 'screen': ValidationError: Etapa nu s-a încheiat."
        assert "sk-ant" not in job.error and (folder / "manifest.json").exists()
        assert job.progress["stages"]["screen"] == "failed"


def test_an_exception_fails_the_job_with_a_sanitized_message(env, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-SECRET-VALUE-123")
    settings, factory, _ = env
    job_id, run_id, _folder = queue_run(factory, settings)

    def exploding_spawn(spec, env_, log):
        raise RuntimeError("cannot start, key sk-ant-SECRET-VALUE-123")

    Worker(settings, factory, spawn=exploding_spawn, sleep=lambda s: None).tick()
    with factory() as db:
        job, run = db.get(Job, job_id), db.get(Run, run_id)
        assert job.status == "failed" and run.status == "failed"
        assert "SECRET" not in job.error and job.error.startswith("RuntimeError:")


def test_progress_is_mirrored_with_a_heartbeat_on_every_poll(env):
    settings, factory, _ = env
    job_id, _run_id, _folder = queue_run(factory, settings)
    seen = []

    def spawn(spec, env_, log):
        spec.run_dir.mkdir(parents=True, exist_ok=True)
        (spec.run_dir / "progress.json").write_text(
            json.dumps({"status": "running", "stages": {"plan": "running"}, "updated_at": "t1"})
        )

        def on_poll():
            with factory() as db:
                job = db.get(Job, job_id)
                seen.append((job.status, dict(job.progress), job.heartbeat_at))

        return FakeProcess(1, polls=3, on_poll=on_poll)

    start = utcnow()
    ticks = itertools.count()
    clock = lambda: start + timedelta(seconds=next(ticks))
    Worker(settings, factory, spawn=spawn, sleep=lambda s: None, clock=clock).tick()
    assert len(seen) == 3 and all(status == "running" for status, _, _ in seen)
    assert seen[-1][1]["stages"] == {"plan": "running"}
    beats = [beat for _, _, beat in seen]
    assert all(a < b for a, b in itertools.pairwise(beats)), beats  # a new heartbeat on every poll


def test_a_run_folder_that_already_has_a_manifest_is_resumed(env):
    settings, factory, _ = env
    partial = settings.runs_dir / "partial"
    partial.mkdir(parents=True)
    (partial / "manifest.json").write_text("{}")
    queue_run(factory, settings, existing_dir=partial)
    captured = []

    def spawn(spec, env_, log):
        captured.append(spec)
        return FakeProcess(1)

    Worker(settings, factory, spawn=spawn, sleep=lambda s: None).tick()
    assert captured[0].resume is True


def test_stale_jobs_are_requeued_and_run_again(env):
    settings, factory, _ = env
    job_id, _run_id, _folder = queue_run(factory, settings)
    with factory() as db:
        job = db.get(Job, job_id)
        job.status, job.attempts, job.locked_by = "running", 1, "dead-worker"
        job.heartbeat_at = utcnow() - timedelta(minutes=10)
        db.commit()
    Worker(settings, factory, spawn=demo_spawn, sleep=lambda s: None).tick()
    with factory() as db:
        job = db.get(Job, job_id)
        assert job.status == "done" and job.attempts == 2


def test_an_import_job_imports_a_folder_addressed_by_name(env):
    settings, factory, tmp_path = env
    make_demo_run(settings.runs_dir / "demo")
    make_eval_run(tmp_path)  # evals/toy + gold/toy.json under the configured roots
    with factory() as db:
        user = create_user(
            db, email="a@example.org", name="A", role="admin", password="correct horse battery"
        )
        db.commit()
        for payload in (
            {"kind": "research", "name": "demo"},
            {"kind": "eval", "name": "toy"},
            {"kind": "research", "name": "../evals/toy"},  # a hostile name
        ):
            enqueue(db, "import", payload, user.id)
            db.commit()  # one transaction each: created_at (and so claim order) differs
    worker = Worker(settings, factory, sleep=lambda s: None)
    while worker.tick():
        pass
    with factory() as db:
        jobs = db.scalars(select(Job).order_by(Job.created_at)).all()
        assert [j.status for j in jobs] == ["done", "done", "failed"]
        assert (
            jobs[0].progress["result"]["status"] == "created"
            and jobs[1].progress["result"]["status"] == "created"
        )
        assert "not a valid folder name" in jobs[2].error
        assert (
            db.scalar(select(sa.func.count()).select_from(Run)) == 2
            and db.scalar(select(sa.func.count()).select_from(Paper)) == 6 + 12
        )


def take_over(factory, settings, job_id):
    """What happens when this worker looks dead: the job is requeued as stale and worker B claims it."""
    with factory() as db:
        db.get(Job, job_id).heartbeat_at = utcnow() - timedelta(minutes=10)
        db.commit()
        requeue_stale(db, settings.job_stale_seconds, settings.job_max_attempts)
        db.commit()
        assert claim(db, "worker-b").id == job_id
        db.commit()


@pytest.mark.parametrize("polls", [1, 3], ids=["lost-as-the-child-finished", "lost-while-running"])
def test_a_worker_that_lost_its_job_stops_the_child_and_writes_nothing(env, polls):
    settings, factory, _ = env
    job_id, run_id, _folder = queue_run(factory, settings)
    children = []

    def spawn(spec, env_, log):
        make_demo_run(spec.run_dir, topic=spec.topic, max_papers=spec.max_papers)
        taken = []

        def on_poll():
            if not taken:
                take_over(factory, settings, job_id)
                taken.append(True)

        children.append(FakeProcess(0, polls=polls, on_poll=on_poll))
        return children[-1]

    assert Worker(settings, factory, spawn=spawn, sleep=lambda s: None, worker_id="worker-a").tick() is True
    assert children[0].terminated is (polls > 1)
    with factory() as db:
        job, run = db.get(Job, job_id), db.get(Run, run_id)
        assert (job.status, job.locked_by, job.error, job.progress) == ("running", "worker-b", None, {})
        # the requeue queued the run again; worker B has not started it and worker A wrote nothing
        assert run.status == "queued" and run.error is None and run.source_sha256 is None
        assert db.scalar(select(sa.func.count()).select_from(Screening)) == 0


def test_a_worker_whose_heartbeat_fails_stops_the_child_and_does_not_import(env, monkeypatch):
    import research_agent.web.worker as worker_module

    monkeypatch.setattr(worker_module, "heartbeat", lambda *a, **k: False)
    settings, factory, _ = env
    job_id, run_id, _folder = queue_run(factory, settings)
    children = []

    def spawn(spec, env_, log):
        make_demo_run(spec.run_dir, topic=spec.topic, max_papers=spec.max_papers)
        children.append(FakeProcess(0, polls=3))
        return children[-1]

    Worker(settings, factory, spawn=spawn, sleep=lambda s: None).tick()
    assert children[0].terminated
    with factory() as db:
        assert db.get(Job, job_id).status == "running" and db.get(Run, run_id).status == "running"
        assert db.scalar(select(sa.func.count()).select_from(Screening)) == 0


def test_the_child_is_stopped_when_the_worker_itself_fails(env, monkeypatch):
    import research_agent.web.worker as worker_module

    def broken(*a, **k):
        raise RuntimeError("database went away")

    monkeypatch.setattr(worker_module, "set_progress", broken)
    settings, factory, _ = env
    job_id, run_id, _folder = queue_run(factory, settings)
    children = []

    def spawn(spec, env_, log):
        children.append(FakeProcess(0, polls=3))
        return children[-1]

    Worker(settings, factory, spawn=spawn, sleep=lambda s: None).tick()
    assert children[0].terminated
    with factory() as db:
        job, run = db.get(Job, job_id), db.get(Run, run_id)
        assert job.status == "failed" and job.error == "RuntimeError: database went away"
        assert run.status == "failed" and run.error == job.error


def test_run_forever_survives_a_failing_tick_and_redacts_the_log(env, monkeypatch, caplog):
    settings, factory, _tmp = env
    monkeypatch.setenv("SOME_API_KEY", "sk-sentinel-value-123456")
    worker = Worker(settings, factory, sleep=lambda s: None)
    calls = []

    def tick():
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("db down, key sk-sentinel-value-123456")
        return False

    worker.tick = tick
    worker.run_forever(stop=lambda: len(calls) >= 2)
    assert len(calls) == 2
    assert "worker tick failed" in caplog.text and "sk-sentinel-value-123456" not in caplog.text


def capture_spawn(captured, code=1, polls=1):
    def spawn(spec, env_, log):
        captured.append(spec)
        return FakeProcess(code, polls=polls)

    return spawn


def test_a_resume_without_a_manifest_starts_fresh_from_the_saved_contract(env):
    """A run that failed before writing manifest.json cannot be resumed; it is started again instead."""
    settings, factory, _ = env
    job_id, run_id, folder = queue_run(factory, settings)
    with factory() as db:
        db.get(Job, job_id).payload = {"run_id": str(run_id), "resume": True}  # no topic in the payload
        db.get(Run, run_id).manifest = {"contract": {"topic": TOPIC, "max_papers": 2, "mode": "demo"}}
        db.commit()
    folder.mkdir(parents=True)  # the first attempt made the folder, then failed
    captured = []
    Worker(settings, factory, spawn=capture_spawn(captured), sleep=lambda s: None).tick()
    [spec] = captured
    assert spec.resume is False and (spec.topic, spec.max_papers, spec.mode) == (TOPIC, 2, "demo")


def test_a_resume_job_with_a_manifest_resumes(env):
    settings, factory, _ = env
    job_id, run_id, folder = queue_run(factory, settings)
    folder.mkdir(parents=True)
    (folder / "manifest.json").write_text("{}")
    with factory() as db:
        db.get(Job, job_id).payload = {"run_id": str(run_id), "resume": True}
        db.commit()
    captured = []
    Worker(settings, factory, spawn=capture_spawn(captured), sleep=lambda s: None).tick()
    assert captured[0].resume is True


def test_a_run_that_exceeds_the_time_limit_is_stopped_and_failed(env):
    settings, factory, _ = env
    settings = replace(settings, job_timeout_seconds=0.05)
    job_id, run_id, _folder = queue_run(factory, settings)
    elapsed, children = [0.0], []

    def sleep(seconds):
        elapsed[0] += seconds

    def spawn(spec, env_, log):
        children.append(FakeProcess(0, polls=10**6))  # a hung pipeline: never exits on its own
        return children[-1]

    worker = Worker(settings, factory, spawn=spawn, sleep=sleep, monotonic=lambda: elapsed[0])
    assert worker.tick() is True
    assert children[0].terminated
    with factory() as db:
        job, run = db.get(Job, job_id), db.get(Run, run_id)
        assert job.status == run.status == "failed"
        assert job.error == run.error == "the run timed out after 0.05 s"


@pytest.mark.parametrize("how", ["path", "symlink"])
def test_a_run_folder_outside_the_runs_directory_is_refused(env, how):
    settings, factory, tmp_path = env
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    folder = outside
    if how == "symlink":
        settings.runs_dir.mkdir(parents=True)
        folder = settings.runs_dir / "link"
        folder.symlink_to(outside, target_is_directory=True)
    job_id, run_id, _folder = queue_run(factory, settings, existing_dir=folder)
    captured = []
    Worker(settings, factory, spawn=capture_spawn(captured, code=0), sleep=lambda s: None).tick()
    assert captured == []  # nothing was started
    with factory() as db:
        job, run = db.get(Job, job_id), db.get(Run, run_id)
        assert job.status == run.status == "failed"
        assert job.error == run.error == "ValueError: the run folder is outside the runs directory"
        assert str(tmp_path) not in job.error


def test_a_busy_run_folder_gives_the_job_back_without_failing_the_run(env):
    """Exit code 75: another child holds .run.lock on this folder. Not a failure; try again later."""
    settings, factory, _ = env
    job_id, run_id, _folder = queue_run(factory, settings)
    worker = Worker(settings, factory, spawn=capture_spawn([], code=75), sleep=lambda s: None)
    assert worker.tick() is False  # nothing finished: run_forever sleeps, drain stops
    with factory() as db:
        job, run = db.get(Job, job_id), db.get(Run, run_id)
        assert (job.status, job.locked_by, job.attempts, job.error) == ("queued", None, 0, None)
        assert run.status == "queued" and run.error is None


def test_a_worker_asked_to_stop_mid_run_stops_the_child_and_gives_the_job_back(env):
    settings, factory, _ = env
    job_id, run_id, _folder = queue_run(factory, settings)
    children = []

    def spawn(spec, env_, log):
        make_demo_run(spec.run_dir, topic=spec.topic, max_papers=spec.max_papers)
        polls = itertools.count(1)
        on_poll = lambda: next(polls) == 2 and worker.request_stop()
        children.append(FakeProcess(0, polls=5, on_poll=on_poll))
        return children[-1]

    worker = Worker(settings, factory, spawn=spawn, sleep=lambda s: None)
    worker.tick()
    assert children[0].terminated
    with factory() as db:
        job, run = db.get(Job, job_id), db.get(Run, run_id)
        assert (job.status, job.locked_by, job.attempts, job.error) == ("queued", None, 0, None)
        assert run.status == "queued" and run.error is None
        assert db.scalar(select(sa.func.count()).select_from(Screening)) == 0
    assert worker.tick() is False  # a stopping worker claims nothing
    worker.run_forever()  # returns at once
    worker.drain()


def test_an_import_keeps_the_heartbeat_going(env, monkeypatch):
    """Importing a large run takes a while; the job must not look stale meanwhile."""
    import research_agent.web.worker as worker_module

    settings, factory, _ = env
    job_id, _run_id, _folder = queue_run(factory, settings)
    real, beats = worker_module.import_research_run, []

    def slow_import(db, folder, created_by=None):
        for _ in range(3):
            time.sleep(0.1)  # progress_poll_seconds is 0.01: several heartbeats per sleep
            with factory() as other:
                beats.append(other.get(Job, job_id).heartbeat_at)
        return real(db, folder, created_by=created_by)

    monkeypatch.setattr(worker_module, "import_research_run", slow_import)
    Worker(settings, factory, spawn=demo_spawn, sleep=lambda s: None).tick()
    assert all(a < b for a, b in itertools.pairwise(beats)), beats
    with factory() as db:
        assert db.get(Job, job_id).status == "done"


def test_an_import_job_refuses_a_symlink_that_leaves_the_root(env):
    settings, factory, tmp_path = env
    outside = make_demo_run(tmp_path / "elsewhere" / "run")
    settings.runs_dir.mkdir(parents=True)
    (settings.runs_dir / "escape").symlink_to(outside, target_is_directory=True)
    with factory() as db:
        user = create_user(
            db, email="a@example.org", name="A", role="admin", password="correct horse battery"
        )
        job, _ = enqueue(db, "import", {"kind": "research", "name": "escape"}, user.id)
        db.commit()
    Worker(settings, factory, sleep=lambda s: None).tick()
    with factory() as db:
        row = db.get(Job, job.id)
        assert row.status == "failed" and "no such folder under the research directory" in row.error
        assert db.scalar(select(sa.func.count()).select_from(Run)) == 0
