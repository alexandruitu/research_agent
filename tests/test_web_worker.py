import json
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

    Worker(settings, factory, spawn=spawn, sleep=lambda s: None).tick()
    assert (
        seen
        and seen[-1][0] == "running"
        and seen[-1][1]["stages"] == {"plan": "running"}
        and seen[-1][2] is not None
    )


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
        assert run.status == "running" and run.error is None and run.source_sha256 is None
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
