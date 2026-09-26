"""The worker: claims jobs and runs them. The only process that holds LLM provider keys."""

import logging
import os
import re
import socket
import subprocess
import threading
import time
from contextlib import contextmanager
from pathlib import Path

from .db.models import Job, Run
from .db.session import make_engine, make_session_factory
from .importer.common import ImportFailed
from .importer.evals import import_eval_run
from .importer.research import import_research_run
from .jobs import claim, complete, fail, heartbeat, release, requeue_stale, set_progress
from .runner import (
    EXIT_LOCKED,
    RunSpec,
    child_environment,
    failure_message,
    progress_snapshot,
    redact,
    sanitize_error,
)
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
    """Claims jobs and runs them, one at a time.

    `request_stop()` (from a signal handler or another thread) makes the worker finish: a pipeline child
    that is still running is stopped and its job goes back to the queue without counting an attempt."""

    def __init__(
        self,
        settings,
        session_factory=None,
        spawn=spawn_process,
        sleep=None,
        clock=None,
        worker_id=None,
        monotonic=time.monotonic,
    ):
        self.settings = settings
        self.factory = session_factory or make_session_factory(make_engine(settings.database_url))
        self.stop_requested = threading.Event()
        self.spawn, self.monotonic = spawn, monotonic
        self.sleep = sleep or self.stop_requested.wait  # a stop request cuts the wait short
        self.clock = clock or (lambda: None)  # None: the database clock (see jobs)
        self.worker_id = worker_id or f"{socket.gethostname()}-{os.getpid()}"

    def request_stop(self):
        self.stop_requested.set()

    @property
    def stopping(self):
        return self.stop_requested.is_set()

    def tick(self):
        """Do at most one job. Returns True when a job was executed (not when none was claimed, and not
        when the claimed job went back to the queue)."""
        if self.stopping:
            return False
        with self.factory() as db:
            requeue_stale(db, self.settings.job_stale_seconds, self.settings.job_max_attempts, self.clock())
            job = claim(db, self.worker_id, self.clock())
            db.commit()  # the claim is visible to other workers immediately
            if job is None:
                return False
            job_id = job.id
        return self.execute(job_id)

    def run_forever(self, stop=lambda: False):
        while not (stop() or self.stopping):
            try:
                busy = self.tick()
            except Exception as exc:  # noqa: BLE001 -- e.g. the database is briefly unreachable: keep polling
                log.warning("worker tick failed: %s", redact(f"{type(exc).__name__}: {exc}"))
                busy = False
            if not busy and not self.stopping:
                self.sleep(self.settings.worker_poll_seconds)

    def drain(self):
        while self.tick():
            pass

    def execute(self, job_id):
        """Run one claimed job. Returns False when it went back to the queue."""
        with self.factory() as db:
            job = db.get(Job, job_id)
            try:
                if job.kind == "research":
                    return self._research(db, job)
                if job.kind == "import":
                    return self._import(db, job)
                raise ValueError(f"unknown job kind {job.kind!r}")
            except Exception as exc:  # noqa: BLE001 -- the worker must survive and report any failure
                db.rollback()
                job = db.get(Job, job_id)
                self._fail(db, job, sanitize_error(exc))
                return True

    def _fail(self, db, job, message):
        """Fail the job and its run, only while this worker owns the job."""
        if fail(db, job, message, worker_id=self.worker_id):
            run_id = (job.payload or {}).get("run_id")
            if run_id and (run := db.get(Run, run_id)) is not None:
                run.status, run.error = "failed", message
            db.commit()
        else:
            db.rollback()

    def _release(self, db, job):
        """Back to the queue, attempt not counted; the run is queued again."""
        if release(db, job, worker_id=self.worker_id):
            db.commit()
        else:
            db.rollback()
        return False

    def _still_owned(self, db, job, run_dir):
        """Mirror progress and beat the heart; False once the job was requeued and taken by another worker."""
        now = self.clock()
        owned = set_progress(
            db, job, progress_snapshot(run_dir), now, worker_id=self.worker_id
        ) and heartbeat(db, job, now, worker_id=self.worker_id)
        db.commit()
        return owned

    @contextmanager
    def _heartbeat_while(self, job_id):
        """Keep the job's heartbeat going from a thread with its own session (e.g. during a long import)."""
        done = threading.Event()

        def beat():
            while not done.wait(self.settings.progress_poll_seconds):
                try:
                    with self.factory() as db:
                        alive = heartbeat(db, db.get(Job, job_id), self.clock(), worker_id=self.worker_id)
                        db.commit()
                except Exception as exc:  # noqa: BLE001 -- a missed beat is retried on the next one
                    log.warning("heartbeat failed: %s", redact(f"{type(exc).__name__}: {exc}"))
                    continue
                if not alive:
                    return

        thread = threading.Thread(target=beat, name="job-heartbeat", daemon=True)
        thread.start()
        try:
            yield
        finally:
            done.set()
            thread.join()

    def _research(self, db, job):
        payload = job.payload
        run = db.get(Run, payload["run_id"])
        run_dir = Path(run.folder).resolve()
        if not run_dir.is_relative_to(self.settings.runs_dir.resolve()):
            raise ValueError("the run folder is outside the runs directory")
        # Resume only what the pipeline saved; a run that failed before its manifest starts again.
        resume = (run_dir / "manifest.json").exists()
        saved = (run.manifest or {}).get("contract") or {}
        contract = {k: payload.get(k, saved.get(k)) for k in ("topic", "max_papers", "mode")}
        if not resume and not contract["topic"]:
            raise ValueError("the run has no saved topic to start from")
        run.status, run.error = "running", None
        db.commit()
        mode = contract["mode"] or "live"
        spec = RunSpec(
            topic=contract["topic"] or "",
            max_papers=int(contract["max_papers"] or self.settings.max_papers_cap),
            mode=mode,
            jev=mode == "live" and bool(os.environ.get("TYPESAFE_API_KEY")),
            resume=resume,
            run_dir=run_dir,
        )
        process = self.spawn(spec, child_environment(), run_dir / "worker.log")
        deadline = self.monotonic() + self.settings.job_timeout_seconds
        interrupted = None
        try:
            while process.poll() is None:
                if self.stopping:
                    interrupted = "stopped"
                    break
                if self.monotonic() >= deadline:
                    interrupted = "timeout"
                    break
                self.sleep(self.settings.progress_poll_seconds)
                if not self._still_owned(db, job, run_dir):
                    return True  # another worker owns the run now: stop our child, touch nothing
            if interrupted is None and not self._still_owned(db, job, run_dir):
                return True
        finally:
            stop_child(process)  # no-op when the child already exited
        if interrupted == "stopped" or process.returncode == EXIT_LOCKED:
            return self._release(db, job)  # the worker is stopping, or another child holds the folder
        if interrupted == "timeout":
            self._fail(db, job, f"the run timed out after {self.settings.job_timeout_seconds:g} s")
        elif process.returncode == 0:
            with self._heartbeat_while(job.id):
                import_research_run(db, run_dir, created_by=job.created_by)
            if not complete(db, job, worker_id=self.worker_id):
                db.rollback()  # lost the job while importing: leave the import to its new owner
                return True
            run.status = "done"
            db.commit()
        else:
            self._fail(db, job, failure_message(run_dir, process.returncode))
        return True

    def _import(self, db, job):
        payload = job.payload
        name, kind = payload.get("name", ""), payload.get("kind")
        if not NAME.match(name) or kind not in ("research", "eval"):
            raise ValueError("not a valid folder name or kind")
        root = self.settings.runs_dir if kind == "research" else self.settings.evals_dir
        folder = (root / name).resolve()
        if not folder.is_relative_to(root.resolve()) or not folder.is_dir():
            raise ImportFailed(f"no such folder under the {kind} directory")
        with self._heartbeat_while(job.id):
            if kind == "research":
                result = import_research_run(db, folder, created_by=job.created_by)
            else:
                result = import_eval_run(
                    db, folder, created_by=job.created_by, gold_dir=self.settings.gold_dir
                )
        if not complete(
            db,
            job,
            {"result": {"status": result.status, "warnings": result.warnings}},
            worker_id=self.worker_id,
        ):
            db.rollback()
            return True
        db.commit()
        return True
