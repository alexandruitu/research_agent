"""The worker: claims jobs and runs them. The only process that holds LLM provider keys."""

import logging
import os
import re
import socket
import subprocess
import time
from pathlib import Path

from .auth import utcnow
from .db.models import Job, Run
from .db.session import make_engine, make_session_factory
from .importer.common import ImportFailed
from .importer.evals import import_eval_run
from .importer.research import import_research_run
from .jobs import claim, complete, fail, heartbeat, requeue_stale, set_progress
from .runner import RunSpec, child_environment, failure_message, progress_snapshot, redact, sanitize_error
from .runner import spawn as spawn_process

log = logging.getLogger(__name__)
NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
STOP_GRACE_SECONDS = 10


def stop_child(process, grace=STOP_GRACE_SECONDS):
    """Terminate the child, then kill it if it has not exited after `grace` seconds."""
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=grace)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()


class Worker:
    def __init__(
        self,
        settings,
        session_factory=None,
        spawn=spawn_process,
        sleep=time.sleep,
        clock=utcnow,
        worker_id=None,
    ):
        self.settings = settings
        self.factory = session_factory or make_session_factory(make_engine(settings.database_url))
        self.spawn, self.sleep, self.clock = spawn, sleep, clock
        self.worker_id = worker_id or f"{socket.gethostname()}-{os.getpid()}"

    def tick(self):
        """Do at most one job. Returns True when a job was executed."""
        with self.factory() as db:
            requeue_stale(db, self.settings.job_stale_seconds, self.settings.job_max_attempts, self.clock())
            job = claim(db, self.worker_id, self.clock())
            db.commit()  # the claim is visible to other workers immediately
            if job is None:
                return False
            job_id = job.id
        self.execute(job_id)
        return True

    def run_forever(self, stop=lambda: False):
        while not stop():
            try:
                busy = self.tick()
            except Exception as exc:  # noqa: BLE001 -- e.g. the database is briefly unreachable: keep polling
                log.warning("worker tick failed: %s", redact(f"{type(exc).__name__}: {exc}"))
                busy = False
            if not busy:
                self.sleep(self.settings.worker_poll_seconds)

    def drain(self):
        while self.tick():
            pass

    def execute(self, job_id):
        with self.factory() as db:
            job = db.get(Job, job_id)
            try:
                if job.kind == "research":
                    self._research(db, job)
                elif job.kind == "import":
                    self._import(db, job)
                else:
                    raise ValueError(f"unknown job kind {job.kind!r}")
            except Exception as exc:  # noqa: BLE001 -- the worker must survive and report any failure
                db.rollback()
                job = db.get(Job, job_id)
                message = sanitize_error(exc)
                if fail(db, job, message, worker_id=self.worker_id):  # only while this worker owns the job
                    run_id = (job.payload or {}).get("run_id")
                    if run_id and (run := db.get(Run, run_id)) is not None:
                        run.status, run.error = "failed", message
                db.commit()

    def _still_owned(self, db, job, run_dir):
        """Mirror progress and beat the heart; False once the job was requeued and taken by another worker."""
        now = self.clock()
        owned = set_progress(
            db, job, progress_snapshot(run_dir), now, worker_id=self.worker_id
        ) and heartbeat(db, job, now, worker_id=self.worker_id)
        db.commit()
        return owned

    def _research(self, db, job):
        payload = job.payload
        run = db.get(Run, payload["run_id"])
        run.status, run.error = "running", None
        db.commit()
        run_dir = Path(run.folder)
        resume = payload.get("resume") or (run_dir / "manifest.json").exists()
        mode = payload.get("mode", "live")
        spec = RunSpec(
            topic=payload["topic"],
            max_papers=payload["max_papers"],
            mode=mode,
            jev=mode == "live" and bool(os.environ.get("TYPESAFE_API_KEY")),
            resume=resume,
            run_dir=run_dir,
        )
        process = self.spawn(spec, child_environment(), run_dir / "worker.log")
        try:
            while process.poll() is None:
                self.sleep(self.settings.progress_poll_seconds)
                if not self._still_owned(db, job, run_dir):
                    return  # another worker owns the run now: stop our child, touch nothing
            if not self._still_owned(db, job, run_dir):
                return
        finally:
            stop_child(process)  # no-op when the child already exited
        if process.returncode == 0:
            import_research_run(db, run_dir, created_by=job.created_by)
            if not complete(db, job, worker_id=self.worker_id):
                db.rollback()  # lost the job while importing: leave the import to its new owner
                return
            run.status = "done"
        else:
            message = failure_message(run_dir, process.returncode)
            if not fail(db, job, message, worker_id=self.worker_id):
                db.rollback()
                return
            run.status, run.error = "failed", message
        db.commit()

    def _import(self, db, job):
        payload = job.payload
        name, kind = payload.get("name", ""), payload.get("kind")
        if not NAME.match(name) or kind not in ("research", "eval"):
            raise ValueError("not a valid folder name or kind")
        root = self.settings.runs_dir if kind == "research" else self.settings.evals_dir
        folder = (root / name).resolve()
        if not folder.is_relative_to(root.resolve()) or not folder.is_dir():
            raise ImportFailed(f"no such folder under the {kind} directory")
        if kind == "research":
            result = import_research_run(db, folder, created_by=job.created_by)
        else:
            result = import_eval_run(db, folder, created_by=job.created_by, gold_dir=self.settings.gold_dir)
        if not complete(
            db,
            job,
            {"result": {"status": result.status, "warnings": result.warnings}},
            worker_id=self.worker_id,
        ):
            db.rollback()
            return
        db.commit()
