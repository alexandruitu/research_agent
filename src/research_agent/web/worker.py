"""The worker: claims jobs and runs them. The only process that holds LLM provider keys."""

import json
import logging
import os
import re
import socket
import subprocess
import tempfile
import threading
import time
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from ..sources import REGISTRY
from ..storage import Store
from .assist import assist_model, field_assist
from .checks import check_keys, check_source_keys, criteria_test, source_check
from .db.models import Job, Run, SourceRow, WorkerStatus
from .db.session import make_engine, make_session_factory
from .fields import settings_row
from .importer.common import ImportFailed
from .importer.evals import import_eval_run
from .importer.research import import_research_run
from .jobs import claim, complete, fail, heartbeat, release, requeue_stale, set_progress
from .runner import (
    EXIT_LOCKED,
    RunSpec,
    child_environment,
    eval_command,
    failure_message,
    progress_snapshot,
    redact,
    sanitize_error,
    spawn_command,
)
from .runner import spawn as spawn_process
from .uploads import materialize

log = logging.getLogger(__name__)
NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
DOMAIN_REQUEST = "domain.request.json"  # the pipeline copies it byte for byte to domain.json
REVIEW_REQUEST = "review.request.json"  # likewise to review.json
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
        http_client=None,
        jev_client=None,
        key_check=False,
        spawn_eval=spawn_command,
    ):
        self.settings = settings
        self.factory = session_factory or make_session_factory(make_engine(settings.database_url))
        self.stop_requested = threading.Event()
        self.spawn, self.monotonic = spawn, monotonic
        self.sleep = sleep or self.stop_requested.wait  # a stop request cuts the wait short
        self.clock = clock or (lambda: None)  # None: the database clock (see jobs)
        self.worker_id = worker_id or f"{socket.gethostname()}-{os.getpid()}"
        # HTTP clients for source checks and criteria tests (None: the connectors' own); tests inject mocks.
        self.http_client, self.jev_client = http_client, jev_client
        self.key_check = key_check  # check the provider keys once when run_forever starts
        self.spawn_eval = (
            spawn_eval  # (command, env, log_path, cwd) -> process; tests run research-eval in-process
        )

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

    def check_keys(self):
        """Record, per model role, whether the provider key is present and accepted (never its value).
        A failure is logged and does not stop the worker: runs still start and fail clearly."""
        try:
            rows = check_keys(os.environ, self.http_client)
            with self.factory() as db:
                for row in rows:
                    status = db.get(WorkerStatus, row["role"]) or WorkerStatus(role=row["role"])
                    for name, value in row.items():
                        setattr(status, name, value)
                    status.checked_at, status.worker_id = datetime.now(UTC), self.worker_id
                    db.add(status)
                db.commit()
        except Exception as exc:  # noqa: BLE001 -- the queue must not depend on this check
            log.warning("key check failed: %s", redact(f"{type(exc).__name__}: {exc}"))
            return None
        self.check_source_keys()
        return rows

    def check_source_keys(self):
        """Record, per source, whether its key is present and accepted (never a value). Never fatal."""
        try:
            with self.factory() as db:
                contact = settings_row(db).contact_email
            with tempfile.TemporaryDirectory() as scratch:  # the raw responses are not kept
                rows = check_source_keys(
                    os.environ, Store(scratch), contact=contact, http_client=self.http_client
                )
            with self.factory() as db:
                now = datetime.now(UTC)
                for row in rows:
                    source = db.get(SourceRow, row["name"])
                    if source is None:
                        continue
                    source.key_present, source.key_accepted = row["key_present"], row["key_accepted"]
                    source.key_detail, source.key_checked_at = row["detail"], now
                db.commit()
            return rows
        except Exception as exc:  # noqa: BLE001 -- the queue must not depend on this check
            log.warning("source key check failed: %s", redact(f"{type(exc).__name__}: {exc}"))
            return None

    def run_forever(self, stop=lambda: False):
        if self.key_check:
            self.check_keys()
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
                if job.kind == "source_check":
                    return self._source_check(db, job)
                if job.kind == "criteria_test":
                    return self._criteria_test(db, job)
                if job.kind == "field_assist":
                    return self._field_assist(db, job)
                if job.kind == "field_preview":
                    return self._field_preview(db, job)
                if job.kind == "eval_run":
                    return self._eval_run(db, job)
                if job.kind == "gold_build":
                    return self._gold_build(db, job)
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
        domain = payload.get("domain") or (run.manifest or {}).get("domain_request")
        if not resume and not (contract["topic"] or domain):
            raise ValueError("the run has no saved topic to start from")
        review = payload.get("review") or (run.manifest or {}).get("review_request")
        domain_file = review_file = None
        if domain and not resume:  # a resume reads the saved contract, domain included
            run_dir.mkdir(parents=True, exist_ok=True)
            domain_file = run_dir / DOMAIN_REQUEST
            domain_file.write_text(json.dumps(domain, ensure_ascii=False, indent=2))
        if review and not resume:  # likewise the review panel
            run_dir.mkdir(parents=True, exist_ok=True)
            review_file = run_dir / REVIEW_REQUEST
            review_file.write_text(json.dumps(review, ensure_ascii=False, indent=2))
        if review:  # uploaded PDFs, on every start and resume (papers are found during the run)
            materialize(db, self.settings.uploads_dir, run_dir)
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
            domain_file=domain_file,
            review_file=review_file,
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

    def _finish(self, db, job, result):
        if not complete(db, job, {"status": "done", "result": result}, worker_id=self.worker_id):
            db.rollback()
            return True
        db.commit()
        return True

    def _source_check(self, db, job):
        name = (job.payload or {}).get("name")
        if name not in REGISTRY or "search" not in REGISTRY[name].capabilities:
            raise ValueError("not a known search source")
        contact = settings_row(db).contact_email
        with tempfile.TemporaryDirectory() as scratch:  # the raw response is not kept
            result = source_check(name, Store(scratch), contact=contact, http_client=self.http_client)
        row = db.get(SourceRow, name)
        row.last_check_at = datetime.now(UTC)
        row.last_check_ok, row.last_check_ms, row.last_check_error = (
            result["ok"],
            result["ms"],
            result["error"],
        )
        return self._finish(db, job, result)

    def _criteria_test(self, db, job):
        payload = job.payload or {}

        def progress(snapshot):
            set_progress(db, job, snapshot, self.clock(), worker_id=self.worker_id)
            db.commit()

        # A scratch store: nothing is written to the paper tables, and nothing is kept.
        with tempfile.TemporaryDirectory() as scratch, self._heartbeat_while(job.id):
            result = criteria_test(
                payload["domain"],
                Store(scratch),
                mode=payload.get("mode", "live"),
                api_key=os.environ.get("TYPESAFE_API_KEY"),
                jev_client=self.jev_client,
                http_client=self.http_client,
                progress=progress,
            )
        result["field_id"], result["version"] = payload.get("field_id"), payload.get("version")
        return self._finish(db, job, result)

    def _field_assist(self, db, job):
        payload = job.payload or {}
        store = Store(self.settings.cache_dir / "assist")  # kept: the same draft never costs twice
        with self._heartbeat_while(job.id):
            result = field_assist(
                payload.get("draft") or {},
                store,
                mode=payload.get("mode", "live"),
                model=assist_model(os.environ),
            )
        return self._finish(db, job, result)

    def _field_preview(self, db, job):
        from .preview import field_preview

        payload = job.payload or {}
        with tempfile.TemporaryDirectory() as scratch, self._heartbeat_while(job.id):
            result = field_preview(payload, Store(scratch), http_client=self.http_client)
        return self._finish(db, job, result)

    def _eval_run(self, db, job):
        """research-eval steps in child processes (the only place with keys), then import the folder as a
        new eval report. Progress: {status, kind, step, steps, done, total}; result: {eval_id, folder, warnings}."""
        from .eval_jobs import eval_steps, parent_report_id

        payload = job.payload or {}
        folder, steps, options = eval_steps(self.settings, payload, db)
        db.commit()
        names = [argv[0] for argv in steps]
        deadline = self.monotonic() + self.settings.job_timeout_seconds
        for done, argv in enumerate(steps):
            snapshot = {
                "status": "running",
                "kind": payload["kind"],
                "step": argv[0],
                "steps": names,
                "done": done,
                "total": len(steps),
            }
            if not set_progress(db, job, snapshot, self.clock(), worker_id=self.worker_id):
                db.rollback()
                return True
            db.commit()
            process = self.spawn_eval(
                eval_command(argv), child_environment(), folder / "worker.log", str(self.settings.evals_dir)
            )
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
                    owned = heartbeat(db, job, self.clock(), worker_id=self.worker_id)
                    db.commit()
                    if not owned:
                        return True
            finally:
                stop_child(process)
            if interrupted == "stopped":
                return self._release(db, job)  # resumes from the eval's call cache when claimed again
            if interrupted == "timeout":
                self._fail(db, job, f"the evaluation timed out after {self.settings.job_timeout_seconds:g} s")
                return True
            if process.returncode != 0:
                self._fail(db, job, eval_failure(folder, argv[0], process.returncode))
                return True
        with self._heartbeat_while(job.id):
            result = import_eval_run(
                db,
                folder,
                created_by=job.created_by,
                gold_dir=self.settings.gold_dir,
                kind=options["kind"],
                parent_id=parent_report_id(db, options["parent_id"]),
                extra_config=options["extra_config"],
            )
        progress = {
            "status": "done",
            "kind": payload["kind"],
            "step": None,
            "steps": names,
            "done": len(steps),
            "total": len(steps),
            "result": {"eval_id": str(result.report_id), "folder": folder.name, "warnings": result.warnings},
        }
        if not complete(db, job, progress, worker_id=self.worker_id):
            db.rollback()
            return True
        db.commit()
        return True

    def _gold_build(self, db, job):
        from .eval_jobs import build_gold_set

        with self._heartbeat_while(job.id):
            _row, result = build_gold_set(
                self.settings,
                job.payload or {},
                http_client=self.http_client,
                created_by=job.created_by,
                db=db,
            )
        return self._finish(db, job, result)


def eval_failure(folder, step, code):
    """`research-eval` writes `Type: message` (keys redacted) to errors.log; redacted again and cut here."""
    try:
        first = (Path(folder) / "errors.log").read_text().splitlines()[0]
    except (OSError, IndexError):
        return f"step '{step}' exited with code {code}"
    return redact(f"step '{step}' failed: {first}")[:300]
