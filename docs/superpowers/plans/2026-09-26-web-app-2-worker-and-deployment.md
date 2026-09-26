# Web app 2 of 3: worker, jobs and deployment — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a member start a research run from the API and have a worker execute the existing pipeline, mirror its progress, import the finished run into the database, and surface failures safely; add the `POST /imports` job, health check, `serve`/`worker` commands, and the Docker Compose deployment files.

**Architecture:** The API never runs the pipeline: it writes a `jobs` row (PostgreSQL is the queue, claimed with `FOR UPDATE SKIP LOCKED`) and returns 202. A worker process claims jobs, runs the existing `research_agent.cli` in a child process (keys only in the child environment, never on a command line, in the database or in logs), copies `progress.json` into `jobs.progress`, and on success calls the plan 1 importer. Stale heartbeats requeue a job, and a re-claimed run resumes from its checkpoint. Spec: `docs/superpowers/specs/2026-09-26-web-app-slice1-design.md`. Plan 1 (backend foundation) must be complete and merged first.

**Tech Stack:** as plan 1 (Python 3.12, FastAPI, SQLAlchemy 2, PostgreSQL 16 via `pgserver` in tests), plus `subprocess` for the child run and Docker Compose files (written and linted, **not runnable on this Mac: no Docker**).

**Conventions used in every task**
- Work in the repo root with the venv active: `cd /Users/alexandruitu/Projects/research_agent && . .venv/bin/activate`. Branch: `feat/web-app`.
- Commit with the trailer `Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>` as the second `-m`.
- After each task: `ruff format src tests && ruff check .` then `pytest -q` must be green before committing.
- A `.env` file with real API keys exists in the repo root: never read, print or commit it.
- **Never run a live-mode pipeline in a test or a check.** The `research_agent.cli` child calls `load_dotenv()`, which walks up from the package directory and would find the repository `.env`, so a live run would spend real money. Tests use demo mode with a real subprocess, or a fake `spawn`.
- Worker and queue tests need committed data visible across connections, so they use the `fresh_db_url` fixture (a throwaway database), never the rollback `db` fixture.

## Contracts this plan adds (plan 3 relies on them)

- Endpoints: `POST /api/v1/runs` (member; 202 `StartRunOut`, or 200 when an `Idempotency-Key` repeats), `POST /api/v1/runs/{id}/resume` (member), `GET /api/v1/jobs/{id}` (creator or admin), `POST /api/v1/imports` (admin), `GET /api/v1/health` (public).
- Schemas: `RunRequest`, `JobOut`, `StartRunOut`, `ImportRequest` in `research_agent.web.api.schemas`.
- Job progress shape (what the UI polls): `{"status": str|None, "stages": {stage: "running"|"completed"|"failed"}, "updated_at": str|None}`; for import jobs `{"result": {"status", "warnings"}}`.
- Run failure text (`runs.error`, `jobs.error`): `failed at stage '<stage>': <ErrorType>: <safe message>` or `the run process exited with code <n>`; never raw provider output.
- Commands: `research-web serve`, `research-web worker [--once]`, `research-web dev --with-worker`.

## File structure

| File | Responsibility |
|---|---|
| `src/research_agent/web/settings.py` (modify) | job caps, demo switch, stale/poll timings |
| `src/research_agent/web/jobs.py` | queue primitives: enqueue, claim, heartbeat, complete, fail, requeue stale |
| `src/research_agent/web/runner.py` | sanitized errors, child command and environment, progress and failure text, `spawn` |
| `src/research_agent/web/worker.py` | `Worker`: tick, research and import execution |
| `src/research_agent/web/api/schemas.py` (modify) | run/job/import request and response models |
| `src/research_agent/web/api/routers/runs.py` (modify) | `POST /runs`, `POST /runs/{id}/resume` |
| `src/research_agent/web/api/routers/jobs.py`, `imports.py`, `health.py` | new routers |
| `src/research_agent/web/cli.py` (modify) | `serve`, `worker`, `dev --with-worker` |
| `deploy/Dockerfile`, `deploy/docker-compose.yml`, `deploy/*.example` | deployment files |
| `docs/deployment.md` | how to deploy and what was not verified locally |
| `tests/test_web_settings.py`, `test_web_jobs.py`, `test_web_runner.py`, `test_web_worker.py`, `test_web_runs_api.py`, `test_web_e2e.py`, `test_web_deploy.py` | tests |

---

### Task 0: Settings for jobs

**Files:**
- Modify: `src/research_agent/web/settings.py`, `tests/conftest.py`
- Test: `tests/test_web_settings.py`

- [ ] **Step 1: Write the failing test**

`tests/test_web_settings.py`:

```python
import pytest

from research_agent.web.settings import SettingsError, load_settings

BASE = {"RESEARCH_WEB_DATABASE_URL": "postgresql+psycopg://x/y"}


def test_job_settings_have_safe_defaults():
    s = load_settings(BASE)
    assert s.allow_demo is False and s.max_papers_cap == 12 and s.max_active_jobs_per_user == 2
    assert s.job_stale_seconds == 120 and s.job_max_attempts == 3
    assert s.worker_poll_seconds == 2.0 and s.progress_poll_seconds == 2.0


def test_job_settings_can_be_overridden_from_the_environment():
    s = load_settings(
        {**BASE, "RESEARCH_WEB_ALLOW_DEMO": "true", "RESEARCH_WEB_MAX_PAPERS": "5", "RESEARCH_WEB_MAX_ACTIVE_JOBS": "1",
         "RESEARCH_WEB_JOB_STALE_SECONDS": "30", "RESEARCH_WEB_WORKER_POLL_SECONDS": "0.1"}
    )
    assert s.allow_demo is True and s.max_papers_cap == 5 and s.max_active_jobs_per_user == 1
    assert s.job_stale_seconds == 30 and s.worker_poll_seconds == 0.1


@pytest.mark.parametrize("name,value", [("RESEARCH_WEB_MAX_PAPERS", "abc"), ("RESEARCH_WEB_MAX_PAPERS", "0"), ("RESEARCH_WEB_MAX_PAPERS", "31")])
def test_bad_numbers_are_rejected(name, value):
    with pytest.raises(SettingsError, match=name):
        load_settings({**BASE, name: value})
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/test_web_settings.py -v`
Expected: FAIL, `AttributeError: 'Settings' object has no attribute 'allow_demo'`

- [ ] **Step 3: Implement**

In `settings.py` add these fields to `Settings` (after `min_password_length`):

```python
    allow_demo: bool = False
    max_papers_cap: int = 12
    max_active_jobs_per_user: int = 2
    job_stale_seconds: int = 120
    job_max_attempts: int = 3
    worker_poll_seconds: float = 2.0
    progress_poll_seconds: float = 2.0
```

and add this helper above `load_settings`, then extend the `Settings(...)` construction inside it:

```python
def _number(env, name, default, cast=int, low=None, high=None):
    raw = env.get(name)
    if raw is None or raw == "":
        return default
    try:
        value = cast(raw)
    except ValueError:
        raise SettingsError(f"{name} must be a number, got {raw!r}") from None
    if (low is not None and value < low) or (high is not None and value > high):
        raise SettingsError(f"{name} must be between {low} and {high}, got {value}")
    return value
```

```python
        allow_demo=env.get("RESEARCH_WEB_ALLOW_DEMO", "false").strip().lower() == "true",
        max_papers_cap=_number(env, "RESEARCH_WEB_MAX_PAPERS", 12, low=1, high=30),
        max_active_jobs_per_user=_number(env, "RESEARCH_WEB_MAX_ACTIVE_JOBS", 2, low=1, high=20),
        job_stale_seconds=_number(env, "RESEARCH_WEB_JOB_STALE_SECONDS", 120, low=5),
        job_max_attempts=_number(env, "RESEARCH_WEB_JOB_MAX_ATTEMPTS", 3, low=1, high=10),
        worker_poll_seconds=_number(env, "RESEARCH_WEB_WORKER_POLL_SECONDS", 2.0, cast=float, low=0.01),
        progress_poll_seconds=_number(env, "RESEARCH_WEB_PROGRESS_POLL_SECONDS", 2.0, cast=float, low=0.01),
```

In `tests/conftest.py`, in the `settings` fixture's environment dict, add `"RESEARCH_WEB_ALLOW_DEMO": "true"` (tests use demo mode; production defaults to false).

- [ ] **Step 4: Run and commit**

Run: `pytest tests/test_web_settings.py tests/test_web_db.py -v` (all green), then:

```bash
ruff format src tests && ruff check . && pytest -q && git add -A
git commit -m "Add job and worker settings" -m "Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 1: Queue primitives

**Files:**
- Create: `src/research_agent/web/jobs.py`
- Test: `tests/test_web_jobs.py`

PostgreSQL is the queue. Every function works on a session and leaves committing to the caller, so a claim can be committed immediately (making the job visible as running to other workers) while progress updates commit on their own cadence.

- [ ] **Step 1: Write the failing tests**

`tests/test_web_jobs.py`:

```python
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
        ids = [create_user(db, email=f"u{i}@example.org", name="U", role="member", password="correct horse battery").id for i in range(2)]
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
        db.commit()
        claim(db, "w")
        set_progress(db, job, {"stages": {"plan": "completed"}})
        heartbeat(db, job)
        assert job.progress == {"stages": {"plan": "completed"}}
        complete(db, job, {"result": "ok"})
        assert job.status == "done" and job.progress == {"result": "ok"} and job.locked_by is None
        other, _ = enqueue(db, "research", {}, user_ids[0])
        fail(db, other, "boom")
        assert other.status == "failed" and other.error == "boom"


def test_stale_running_jobs_are_requeued_until_attempts_run_out(factory, user_ids):
    now = utcnow()
    with factory() as db:
        fresh, _ = enqueue(db, "research", {"k": "fresh"}, user_ids[0])
        stale, _ = enqueue(db, "research", {"k": "stale"}, user_ids[0])
        spent, _ = enqueue(db, "research", {"k": "spent"}, user_ids[0])
        for job, beat, attempts in ((fresh, now, 1), (stale, now - timedelta(minutes=10), 1), (spent, now - timedelta(minutes=10), 3)):
            job.status, job.heartbeat_at, job.attempts, job.locked_by = "running", beat, attempts, "dead-worker"
        db.commit()
        changed = requeue_stale(db, stale_after_seconds=120, max_attempts=3, now=now)
        db.commit()
        assert {j.payload["k"] for j in changed} == {"stale", "spent"}
        assert (fresh.status, stale.status, spent.status) == ("running", "queued", "failed")
        assert stale.locked_by is None and "stopped responding" in spent.error
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/test_web_jobs.py -v`
Expected: FAIL, `ModuleNotFoundError: No module named 'research_agent.web.jobs'`

- [ ] **Step 3: Implement `jobs.py`**

```python
"""PostgreSQL-backed job queue. Callers commit; claims use FOR UPDATE SKIP LOCKED."""

from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from .auth import utcnow
from .db.models import Job


def enqueue(db, kind, payload, created_by, idempotency_key=None):
    """Returns (job, created). The same (user, idempotency key) always yields the same job."""
    if idempotency_key:
        existing = db.scalar(select(Job).where(Job.created_by == created_by, Job.idempotency_key == idempotency_key))
        if existing is not None:
            return existing, False
    job = Job(kind=kind, payload=payload, status="queued", created_by=created_by, idempotency_key=idempotency_key)
    try:
        with db.begin_nested():
            db.add(job)
            db.flush()
    except IntegrityError:  # a concurrent identical request won the race
        existing = db.scalar(select(Job).where(Job.created_by == created_by, Job.idempotency_key == idempotency_key))
        if existing is None:
            raise
        return existing, False
    return job, True


def claim(db, worker_id, now=None):
    now = now or utcnow()
    job = db.scalar(
        select(Job).where(Job.status == "queued").order_by(Job.created_at, Job.id).with_for_update(skip_locked=True).limit(1)
    )
    if job is None:
        return None
    job.status, job.locked_by, job.heartbeat_at, job.attempts = "running", worker_id, now, job.attempts + 1
    db.flush()
    return job


def heartbeat(db, job, now=None):
    job.heartbeat_at = now or utcnow()
    db.flush()


def set_progress(db, job, progress, now=None):
    job.progress = progress
    job.heartbeat_at = now or utcnow()
    db.flush()


def complete(db, job, progress=None):
    job.status, job.locked_by = "done", None
    if progress is not None:
        job.progress = progress
    db.flush()


def fail(db, job, error):
    job.status, job.locked_by, job.error = "failed", None, error
    db.flush()


def requeue_stale(db, stale_after_seconds, max_attempts, now=None):
    """Running jobs whose heartbeat stopped go back to the queue, or fail once attempts are spent."""
    now = now or utcnow()
    cutoff = now - timedelta(seconds=stale_after_seconds)
    stale = db.scalars(
        select(Job).where(Job.status == "running", Job.heartbeat_at < cutoff).with_for_update(skip_locked=True)
    ).all()
    for job in stale:
        job.locked_by = None
        if job.attempts < max_attempts:
            job.status = "queued"
        else:
            job.status, job.error = "failed", "the worker stopped responding and no attempts are left"
    db.flush()
    return stale
```

- [ ] **Step 4: Run and commit**

Run: `pytest tests/test_web_jobs.py -v`
Expected: 5 passed. Then:

```bash
ruff format src tests && ruff check . && pytest -q && git add -A
git commit -m "Add the PostgreSQL job queue primitives" -m "Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 2: Runner helpers (sanitized errors, child command and environment, progress)

**Files:**
- Create: `src/research_agent/web/runner.py`
- Test: `tests/test_web_runner.py`

Design rules: a topic is passed as one argv element (never through a shell); the child environment keeps the provider keys but drops the database URL; failure text is built only from the pipeline's own sanitized `progress.json` fields, never from stdout/stderr; anything else that reaches the database goes through `sanitize_error`, which redacts `*_API_KEY` values.

- [ ] **Step 1: Write the failing tests**

`tests/test_web_runner.py`:

```python
import json
from dataclasses import replace

from research_agent.web.runner import (
    RunSpec, build_command, child_environment, failure_message, progress_snapshot, read_progress, sanitize_error,
)


def spec(tmp_path, **kw):
    return RunSpec(topic="t topic; rm -rf /", max_papers=3, mode="demo", jev=False, resume=False, run_dir=tmp_path, **kw)


def test_new_run_command_passes_the_topic_as_a_single_argument(tmp_path):
    command = build_command(spec(tmp_path))
    assert command[1:3] == ["-m", "research_agent.cli"]
    assert "t topic; rm -rf /" in command  # one argv element: never interpolated into a shell
    assert command[command.index("--mode") + 1] == "demo" and command[command.index("--max-papers") + 1] == "3"
    assert command[command.index("--run-dir") + 1] == str(tmp_path) and "--jev" not in command and "--resume" not in command


def test_resume_and_jev_flags(tmp_path):
    resume = build_command(replace(spec(tmp_path), resume=True))
    assert "--resume" in resume and "t topic; rm -rf /" not in resume and "--mode" not in resume
    assert "--jev" in build_command(replace(spec(tmp_path), mode="live", jev=True))


def test_child_environment_keeps_provider_keys_but_not_the_database(monkeypatch):
    monkeypatch.setenv("RESEARCH_WEB_DATABASE_URL", "postgresql://u:secret@h/db")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k1")
    env = child_environment()
    assert "RESEARCH_WEB_DATABASE_URL" not in env and env["ANTHROPIC_API_KEY"] == "k1"
    assert env["PYTHONUNBUFFERED"] == "1"


def test_read_progress_and_snapshot(tmp_path):
    assert read_progress(tmp_path) == {} and progress_snapshot(tmp_path) == {"status": None, "stages": {}, "updated_at": None}
    (tmp_path / "progress.json").write_text(
        json.dumps({"status": "running", "stages": {"plan": "completed", "discover": "running"}, "updated_at": "2026-09-26T10:00:00+00:00", "pid": 1})
    )
    assert progress_snapshot(tmp_path) == {
        "status": "running", "stages": {"plan": "completed", "discover": "running"}, "updated_at": "2026-09-26T10:00:00+00:00",
    }
    (tmp_path / "progress.json").write_text("{ not json")
    assert read_progress(tmp_path) == {}


def test_failure_message_uses_only_the_pipelines_sanitized_fields(tmp_path):
    (tmp_path / "progress.json").write_text(
        json.dumps({"status": "failed", "stages": {"plan": "completed", "screen": "failed"}, "error_type": "ValidationError", "message": "Etapa nu s-a încheiat."})
    )
    assert failure_message(tmp_path, 1) == "failed at stage 'screen': ValidationError: Etapa nu s-a încheiat."
    assert failure_message(tmp_path / "missing", 3) == "the run process exited with code 3"
    (tmp_path / "progress.json").write_text(json.dumps({"status": "completed"}))
    assert failure_message(tmp_path, 1) == "the run process exited with code 1"


def test_sanitize_error_redacts_key_values_and_truncates(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-SECRET-VALUE-123")
    monkeypatch.setenv("TYPESAFE_API_KEY", "abc")  # shorter than 8 characters: left alone (would mangle text)
    text = sanitize_error(RuntimeError("provider rejected sk-ant-SECRET-VALUE-123 and abc"))
    assert "SECRET" not in text and text.startswith("RuntimeError:") and "***" in text and "abc" in text
    assert len(sanitize_error(RuntimeError("x" * 1000))) <= 300
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/test_web_runner.py -v`
Expected: FAIL, `ModuleNotFoundError: No module named 'research_agent.web.runner'`

- [ ] **Step 3: Implement `runner.py`**

```python
"""Running the existing pipeline in a child process, safely."""

import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

MAX_ERROR = 300
DROPPED_FROM_CHILD = ("RESEARCH_WEB_DATABASE_URL",)


@dataclass(frozen=True)
class RunSpec:
    topic: str
    max_papers: int
    mode: str  # live | demo
    jev: bool
    resume: bool
    run_dir: Path


def build_command(spec):
    """argv for `research_agent.cli`. The topic is one argument; no shell is involved anywhere."""
    args = [sys.executable, "-m", "research_agent.cli", "--run-dir", str(spec.run_dir)]
    if spec.resume:
        return args + ["--resume"]
    args += [spec.topic, "--mode", spec.mode, "--max-papers", str(spec.max_papers)]
    return args + (["--jev"] if spec.jev else [])


def child_environment():
    env = {k: v for k, v in os.environ.items() if k not in DROPPED_FROM_CHILD}
    env["PYTHONUNBUFFERED"] = "1"
    return env


def spawn(spec, env, log_path):
    """Start the child. Its output goes to a log file in the run folder, never into the database."""
    Path(spec.run_dir).mkdir(parents=True, exist_ok=True)
    log = open(log_path, "ab")  # noqa: SIM115 -- owned by the child for its lifetime
    try:
        return subprocess.Popen(build_command(spec), env=env, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
    finally:
        log.close()  # the child holds its own copy of the descriptor


def read_progress(run_dir):
    try:
        return json.loads((Path(run_dir) / "progress.json").read_text())
    except (OSError, ValueError):
        return {}


def progress_snapshot(run_dir):
    data = read_progress(run_dir)
    return {"status": data.get("status"), "stages": data.get("stages", {}), "updated_at": data.get("updated_at")}


def failure_message(run_dir, exit_code):
    """Built only from the pipeline's own sanitized progress fields; never from process output."""
    data = read_progress(run_dir)
    if data.get("status") == "failed":
        failed = [stage for stage, state in (data.get("stages") or {}).items() if state == "failed"]
        where = f"failed at stage '{failed[0]}': " if failed else "failed: "
        return where + f"{data.get('error_type', 'Error')}: {data.get('message', 'no details')}"[:MAX_ERROR]
    return f"the run process exited with code {exit_code}"


def sanitize_error(exc):
    """`Type: message`, with the values of every *_API_KEY variable replaced, cut to 300 characters."""
    text = f"{type(exc).__name__}: {exc}"
    for name, value in os.environ.items():
        if name.endswith("_API_KEY") and len(value) >= 8:
            text = text.replace(value, "***")
    return text[:MAX_ERROR]
```

- [ ] **Step 4: Run and commit**

Run: `pytest tests/test_web_runner.py -v`
Expected: 6 passed. Then:

```bash
ruff format src tests && ruff check . && pytest -q && git add -A
git commit -m "Add runner helpers: safe command, child environment, progress and failure text" -m "Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 3: The worker

**Files:**
- Create: `src/research_agent/web/worker.py`
- Test: `tests/test_web_worker.py`

Behaviour: `tick()` requeues stale jobs, claims one job (committing the claim at once), executes it, and returns whether it did work. A research job sets its run to `running`, spawns the pipeline (resuming automatically when the run folder already holds a manifest), polls the child, mirrors `progress.json` into `jobs.progress` with a heartbeat on every poll, and on exit imports the finished run (success) or records a safe failure. Any exception fails the job with a sanitized message and marks the run failed. An import job imports a run or eval folder that lives under the configured roots, addressed by name only.

- [ ] **Step 1: Write the failing tests**

`tests/test_web_worker.py`:

```python
import json
from datetime import timedelta
from pathlib import Path

import pytest
import sqlalchemy as sa
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from research_agent.web.auth import create_user, utcnow
from research_agent.web.db.models import Field, Job, Paper, Run, Screening
from research_agent.web.importer.common import get_or_create_field
from research_agent.web.jobs import enqueue
from research_agent.web.settings import load_settings
from research_agent.web.worker import Worker
from web_fixtures import make_demo_run, make_eval_run

TOPIC = "retrieval augmented generation"


class FakeProcess:
    """Stands in for the pipeline child: finishes after `polls` polls with `code`."""

    def __init__(self, code, polls=1, on_poll=None):
        self.code, self.polls, self.on_poll, self.returncode = code, polls, on_poll, None

    def poll(self):
        if self.on_poll:
            self.on_poll()
        self.polls -= 1
        if self.polls <= 0:
            self.returncode = self.code
            return self.code
        return None


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
        user = create_user(db, email="m@example.org", name="M", role="member", password="correct horse battery")
        field = get_or_create_field(db, TOPIC, user.id)
        run = Run(field_id=field.id, kind="research", status="queued", manifest={}, created_by=user.id)
        db.add(run)
        db.flush()
        run.folder = str(existing_dir or settings.runs_dir / run.id.hex)
        payload = {"run_id": str(run.id), "field_id": str(field.id), "topic": TOPIC, "max_papers": max_papers, "mode": mode, "resume": False}
        job, _ = enqueue(db, "research", payload, user.id)
        db.commit()
        return job.id, run.id, Path(run.folder)


def demo_spawn(spec, env_, log):
    make_demo_run(spec.run_dir, topic=spec.topic, max_papers=spec.max_papers)
    return FakeProcess(0)


def test_a_finished_run_is_imported_and_the_job_completes(env):
    settings, factory, _ = env
    job_id, run_id, folder = queue_run(factory, settings)
    worker = Worker(settings, factory, spawn=demo_spawn, sleep=lambda s: None)
    assert worker.tick() is True
    with factory() as db:
        job, run = db.get(Job, job_id), db.get(Run, run_id)
        assert job.status == "done" and job.locked_by is None and job.attempts == 1
        assert run.status == "done" and run.error is None and run.manifest["prompt_version"]
        assert db.scalar(select(sa.func.count()).select_from(Screening).where(Screening.run_id == run_id)) == 3
    assert worker.tick() is False  # nothing left to do


def test_a_failed_run_records_a_safe_message_and_keeps_the_checkpoint(env):
    settings, factory, _ = env
    job_id, run_id, folder = queue_run(factory, settings)

    def failing_spawn(spec, env_, log):
        spec.run_dir.mkdir(parents=True, exist_ok=True)
        (spec.run_dir / "manifest.json").write_text("{}")
        (spec.run_dir / "progress.json").write_text(
            json.dumps({"status": "failed", "stages": {"plan": "completed", "screen": "failed"}, "error_type": "ValidationError", "message": "Etapa nu s-a încheiat."})
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
    job_id, run_id, folder = queue_run(factory, settings)
    seen = []

    def spawn(spec, env_, log):
        spec.run_dir.mkdir(parents=True, exist_ok=True)
        (spec.run_dir / "progress.json").write_text(json.dumps({"status": "running", "stages": {"plan": "running"}, "updated_at": "t1"}))

        def on_poll():
            with factory() as db:
                job = db.get(Job, job_id)
                seen.append((job.status, dict(job.progress), job.heartbeat_at))

        return FakeProcess(1, polls=3, on_poll=on_poll)

    Worker(settings, factory, spawn=spawn, sleep=lambda s: None).tick()
    assert seen and seen[-1][0] == "running" and seen[-1][1]["stages"] == {"plan": "running"} and seen[-1][2] is not None


def test_a_run_folder_that_already_has_a_manifest_is_resumed(env):
    settings, factory, tmp_path = env
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
    job_id, run_id, _folder = queue_run(factory, settings)
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
        user = create_user(db, email="a@example.org", name="A", role="admin", password="correct horse battery")
        enqueue(db, "import", {"kind": "research", "name": "demo"}, user.id)
        enqueue(db, "import", {"kind": "eval", "name": "toy"}, user.id)
        enqueue(db, "import", {"kind": "research", "name": "../evals/toy"}, user.id)  # a hostile name
        db.commit()
    worker = Worker(settings, factory, sleep=lambda s: None)
    while worker.tick():
        pass
    with factory() as db:
        jobs = db.scalars(select(Job).order_by(Job.created_at)).all()
        assert [j.status for j in jobs] == ["done", "done", "failed"]
        assert jobs[0].progress["result"]["status"] == "created" and jobs[1].progress["result"]["status"] == "created"
        assert "not a valid folder name" in jobs[2].error
        assert db.scalar(select(sa.func.count()).select_from(Run)) == 2 and db.scalar(select(sa.func.count()).select_from(Paper)) == 6 + 12
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/test_web_worker.py -v`
Expected: FAIL, `ModuleNotFoundError: No module named 'research_agent.web.worker'`

- [ ] **Step 3: Implement `worker.py`**

```python
"""The worker: claims jobs and runs them. The only process that holds LLM provider keys."""

import os
import re
import socket
import time
from pathlib import Path

from .auth import utcnow
from .db.models import Job, Run
from .db.session import make_engine, make_session_factory
from .importer.common import ImportFailed
from .importer.evals import import_eval_run
from .importer.research import import_research_run
from .jobs import claim, complete, fail, heartbeat, requeue_stale, set_progress
from .runner import RunSpec, child_environment, failure_message, progress_snapshot, sanitize_error, spawn as spawn_process

NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


class Worker:
    def __init__(self, settings, session_factory=None, spawn=spawn_process, sleep=time.sleep, clock=utcnow, worker_id=None):
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
            if not self.tick():
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
                fail(db, job, message)
                run_id = (job.payload or {}).get("run_id")
                if run_id and (run := db.get(Run, run_id)) is not None:
                    run.status, run.error = "failed", message
                db.commit()

    def _research(self, db, job):
        payload = job.payload
        run = db.get(Run, payload["run_id"])
        run.status, run.error = "running", None
        db.commit()
        run_dir = Path(run.folder)
        resume = payload.get("resume") or (run_dir / "manifest.json").exists()
        mode = payload.get("mode", "live")
        spec = RunSpec(
            topic=payload["topic"], max_papers=payload["max_papers"], mode=mode,
            jev=mode == "live" and bool(os.environ.get("TYPESAFE_API_KEY")), resume=resume, run_dir=run_dir,
        )
        process = self.spawn(spec, child_environment(), run_dir / "worker.log")
        while process.poll() is None:
            self.sleep(self.settings.progress_poll_seconds)
            set_progress(db, job, progress_snapshot(run_dir), self.clock())
            heartbeat(db, job, self.clock())
            db.commit()
        set_progress(db, job, progress_snapshot(run_dir), self.clock())
        if process.returncode == 0:
            import_research_run(db, run_dir, created_by=job.created_by)
            run.status = "done"
            complete(db, job)
        else:
            message = failure_message(run_dir, process.returncode)
            run.status, run.error = "failed", message
            fail(db, job, message)
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
        complete(db, job, {"result": {"status": result.status, "warnings": result.warnings}})
        db.commit()
```

The hostile import name `../evals/toy` must fail with the message from the first `raise ValueError` in `_import` ("not a valid folder name or kind").

- [ ] **Step 4: Run**

Run: `pytest tests/test_web_worker.py -v`
Expected: 7 passed. Debug notes: (a) the importer finds the pre-created `runs` row by `folder`, so a successful run is *updated* in place and keeps its id; (b) `set_progress` commits happen inside the poll loop so other connections see progress; (c) `test_a_run_folder_that_already_has_a_manifest_is_resumed` only checks the `resume` flag of the spec passed to `spawn`.

- [ ] **Step 5: Commit**

```bash
ruff format src tests && ruff check . && pytest -q && git add -A
git commit -m "Add the worker: claim, run the pipeline in a child, mirror progress, import, fail safely" -m "Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---
### Task 4: The runs, jobs, imports and health endpoints

**Files:**
- Modify: `src/research_agent/web/api/schemas.py`, `src/research_agent/web/api/routers/runs.py`, `src/research_agent/web/api/app.py`, `tests/test_web_guards.py`
- Create: `src/research_agent/web/api/routers/jobs.py`, `src/research_agent/web/api/routers/imports.py`, `src/research_agent/web/api/routers/health.py`
- Test: `tests/test_web_runs_api.py`

- [ ] **Step 1: Write the failing tests**

`tests/test_web_runs_api.py`:

```python
import uuid
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from research_agent.web.api.app import create_app
from research_agent.web.api.deps import get_db
from research_agent.web.auth import create_user
from research_agent.web.db.models import Field, Job, Run
from web_fixtures import make_demo_run

BODY = {"max_papers": 3, "mode": "demo"}


@pytest.fixture
def field_id(imported, db):
    return str(db.scalar(select(Field.id).where(Field.topic == "retrieval augmented generation")))


def start(client, csrf, field, **overrides):
    return client.post("/api/v1/runs", json={"field_id": field, **BODY, **overrides}, headers=csrf)


def test_health_is_public_and_touches_nothing(client):
    r = client.get("/api/v1/health")
    assert r.status_code == 200 and r.json() == {"status": "ok"}


def test_member_starts_a_run_which_is_queued_not_executed(sign_in, field_id, db, settings):
    member, csrf = sign_in("member")
    r = start(member, csrf, field_id)
    assert r.status_code == 202
    body = r.json()
    assert body["job"]["status"] == "queued" and body["job"]["kind"] == "research" and body["job"]["run_id"] == body["run_id"]
    run = db.get(Run, uuid.UUID(body["run_id"]))
    assert run.status == "queued" and run.kind == "research" and run.folder == str(settings.runs_dir / run.id.hex)
    assert run.manifest["contract"] == {"topic": "retrieval augmented generation", "max_papers": 3, "mode": "demo"}
    job = db.get(Job, uuid.UUID(body["job"]["id"]))
    assert job.payload["topic"] == "retrieval augmented generation" and job.payload["resume"] is False
    listed = {r["id"]: r for r in member.get("/api/v1/runs").json()}
    assert listed[body["run_id"]]["status"] == "queued" and listed[body["run_id"]]["paper_count"] == 0


def test_only_members_may_start_runs_and_csrf_is_required(sign_in, client, field_id):
    viewer, viewer_csrf = sign_in("viewer")
    assert start(viewer, viewer_csrf, field_id).status_code == 403
    assert client.post("/api/v1/runs", json={"field_id": field_id, **BODY}).status_code == 401
    member, _ = sign_in("member")
    assert member.post("/api/v1/runs", json={"field_id": field_id, **BODY}).status_code == 403  # no CSRF header


@pytest.mark.parametrize("overrides,status", [({"max_papers": 0}, 422), ({"max_papers": 13}, 422), ({"mode": "nope"}, 422), ({"field_id": str(uuid.uuid4())}, 404)])
def test_validation(sign_in, field_id, overrides, status):
    member, csrf = sign_in("member")
    assert start(member, csrf, field_id, **overrides).status_code == status


def test_demo_mode_is_refused_when_the_deployment_disables_it(app, settings, db, users, field_id):
    strict = create_app(replace(settings, allow_demo=False), session_factory=lambda: db)
    strict.dependency_overrides[get_db] = lambda: db
    client = TestClient(strict)
    login = client.post("/api/v1/auth/login", json={"email": "member@example.org", "password": "correct horse battery"})
    r = start(client, {"X-CSRF-Token": login.json()["csrf_token"]}, field_id)
    assert r.status_code == 422 and "demo" in r.json()["message"]


def test_the_same_idempotency_key_returns_the_same_job(sign_in, field_id, db):
    member, csrf = sign_in("member")
    first = member.post("/api/v1/runs", json={"field_id": field_id, **BODY}, headers={**csrf, "Idempotency-Key": "k1"})
    again = member.post("/api/v1/runs", json={"field_id": field_id, **BODY}, headers={**csrf, "Idempotency-Key": "k1"})
    assert first.status_code == 202 and again.status_code == 200
    assert again.json()["job"]["id"] == first.json()["job"]["id"] and again.json()["run_id"] == first.json()["run_id"]
    assert db.scalar(select(func.count()).select_from(Job).where(Job.kind == "research")) == 1
    assert db.scalar(select(func.count()).select_from(Run).where(Run.status == "queued")) == 1


def test_a_member_cannot_have_more_active_runs_than_the_cap(sign_in, field_id):
    member, csrf = sign_in("member")
    assert [start(member, csrf, field_id).status_code for _ in range(2)] == [202, 202]
    third = start(member, csrf, field_id)
    assert third.status_code == 429 and third.json()["code"] == "too_many_active_runs"


def test_resume_only_for_failed_research_runs(sign_in, field_id, db, imported):
    member, csrf = sign_in("member")
    failed = Run(field_id=uuid.UUID(field_id), kind="research", status="failed", error="boom", folder="/x",
                 manifest={"contract": {"topic": "retrieval augmented generation", "max_papers": 3, "mode": "demo"}})
    db.add(failed)
    db.commit()
    r = member.post(f"/api/v1/runs/{failed.id}/resume", headers=csrf)
    assert r.status_code == 202 and r.json()["run_id"] == str(failed.id)
    db.refresh(failed)
    assert failed.status == "queued" and failed.error is None
    assert db.get(Job, uuid.UUID(r.json()["job"]["id"])).payload["resume"] is True
    again = member.post(f"/api/v1/runs/{failed.id}/resume", headers=csrf)  # now queued, not failed
    assert again.status_code == 409 and again.json()["code"] == "conflict"
    assert member.post(f"/api/v1/runs/{imported['eval']}/resume", headers=csrf).status_code == 409  # an eval run
    assert member.post(f"/api/v1/runs/{uuid.uuid4()}/resume", headers=csrf).status_code == 404


def test_jobs_are_visible_to_their_creator_and_admins_only(sign_in, app, users, db, field_id):
    member, csrf = sign_in("member")
    job_id = start(member, csrf, field_id).json()["job"]["id"]
    assert member.get(f"/api/v1/jobs/{job_id}").json()["id"] == job_id
    other = create_user(db, email="other@example.org", name="O", role="member", password="correct horse battery")
    db.commit()
    stranger = TestClient(app)
    stranger.post("/api/v1/auth/login", json={"email": "other@example.org", "password": "correct horse battery"})
    assert stranger.get(f"/api/v1/jobs/{job_id}").status_code == 404
    admin, _ = sign_in("admin")
    assert admin.get(f"/api/v1/jobs/{job_id}").status_code == 200
    assert admin.get(f"/api/v1/jobs/{uuid.uuid4()}").status_code == 404
    assert other.role == "member"


def test_import_endpoint_queues_a_job_for_a_named_folder(sign_in, settings):
    make_demo_run(settings.runs_dir / "demo")
    admin, csrf = sign_in("admin")
    ok = admin.post("/api/v1/imports", json={"kind": "research", "name": "demo"}, headers=csrf)
    assert ok.status_code == 202 and ok.json()["kind"] == "import" and ok.json()["status"] == "queued"
    assert admin.post("/api/v1/imports", json={"kind": "research", "name": "missing"}, headers=csrf).status_code == 404
    for bad in ("../evals", "a/b", ".hidden", ""):
        assert admin.post("/api/v1/imports", json={"kind": "research", "name": bad}, headers=csrf).status_code == 422
    member, member_csrf = sign_in("member")
    assert member.post("/api/v1/imports", json={"kind": "research", "name": "demo"}, headers=member_csrf).status_code == 403
```

Also update `tests/test_web_guards.py`: change `PUBLIC` to `{("POST", f"{API_PREFIX}/auth/login"), ("GET", f"{API_PREFIX}/health")}` and add these rows to the list returned by `matrix()`:

```python
        ("POST", "/runs", "member"),
        ("POST", f"/runs/{run}/resume", "member"),
        ("GET", f"/jobs/{'00000000-0000-0000-0000-000000000000'}", "member"),
        ("POST", "/imports", "admin"),
```

(An allowed role must not see 401/403 for these: an empty body gives 422 and an unknown job 404, which is fine.)

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/test_web_runs_api.py -v`
Expected: FAIL (routes missing: 404/405 responses).

- [ ] **Step 3: Add the schemas (in `api/schemas.py`; add `Field` to the pydantic import)**

```python
from pydantic import BaseModel, ConfigDict, Field


class RunRequest(Model):
    field_id: uuid.UUID
    max_papers: int = Field(default=12, ge=1)
    mode: Literal["live", "demo"] = "live"


class JobOut(Model):
    id: uuid.UUID
    kind: str
    status: str
    progress: dict[str, Any]
    error: str | None
    run_id: uuid.UUID | None
    attempts: int
    created_at: datetime


class StartRunOut(Model):
    job: JobOut
    run_id: uuid.UUID


class ImportRequest(Model):
    kind: Literal["research", "eval"]
    name: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$", max_length=200)
```

- [ ] **Step 4: Implement the run-starting routes (append to `api/routers/runs.py`)**

Add imports: `from fastapi import Header, Response`, `from ...db.models import Job`, `from ...jobs import enqueue`, `from ..schemas import JobOut, RunRequest, StartRunOut`. Then append:

```python
def job_out(job):
    run_id = (job.payload or {}).get("run_id")
    return JobOut(
        id=job.id, kind=job.kind, status=job.status, progress=job.progress or {}, error=job.error,
        run_id=uuid.UUID(run_id) if run_id else None, attempts=job.attempts, created_at=job.created_at,
    )


def _check_active_cap(db, user, settings):
    active = db.scalar(
        select(func.count()).select_from(Job).where(Job.created_by == user.id, Job.status.in_(("queued", "running")))
    )
    if active >= settings.max_active_jobs_per_user:
        raise ApiError(429, "too_many_active_runs", "You already have the maximum number of active runs")


@router.post("", response_model=StartRunOut, status_code=202)
def start_run(
    body: RunRequest, response: Response, idempotency_key: str | None = Header(None, max_length=100),
    user=Depends(require_role("member")), db=Depends(get_db), settings=Depends(get_settings),
):
    field = db.get(Field, body.field_id)
    if field is None:
        raise ApiError(404, "not_found", "No such field")
    if body.max_papers > settings.max_papers_cap:
        raise ApiError(422, "validation_error", f"max_papers must be at most {settings.max_papers_cap}")
    if body.mode == "demo" and not settings.allow_demo:
        raise ApiError(422, "validation_error", "demo mode is disabled on this deployment")
    if idempotency_key:
        existing = db.scalar(select(Job).where(Job.created_by == user.id, Job.idempotency_key == idempotency_key))
        if existing is not None:
            response.status_code = 200
            return StartRunOut(job=job_out(existing), run_id=uuid.UUID(existing.payload["run_id"]))
    _check_active_cap(db, user, settings)
    contract = {"topic": field.topic, "max_papers": body.max_papers, "mode": body.mode}
    run = Run(field_id=field.id, kind="research", status="queued", manifest={"contract": contract}, created_by=user.id)
    db.add(run)
    db.flush()
    run.folder = str(settings.runs_dir / run.id.hex)
    payload = {"run_id": str(run.id), "field_id": str(field.id), **contract, "resume": False}
    job, created = enqueue(db, "research", payload, user.id, idempotency_key)
    if not created:  # lost a race with an identical request: drop the run we just made
        db.delete(run)
        db.commit()
        response.status_code = 200
        return StartRunOut(job=job_out(job), run_id=uuid.UUID(job.payload["run_id"]))
    db.commit()
    return StartRunOut(job=job_out(job), run_id=run.id)


@router.post("/{run_id}/resume", response_model=StartRunOut, status_code=202)
def resume_run(run_id: uuid.UUID, user=Depends(require_role("member")), db=Depends(get_db), settings=Depends(get_settings)):
    run = db.get(Run, run_id)
    if run is None:
        raise ApiError(404, "not_found", "No such run")
    if run.kind != "research" or run.status != "failed":
        raise ApiError(409, "conflict", "Only a failed research run can be resumed")
    _check_active_cap(db, user, settings)
    contract = run.manifest.get("contract") or {}
    field = db.get(Field, run.field_id)
    payload = {
        "run_id": str(run.id), "field_id": str(run.field_id), "topic": contract.get("topic", field.topic),
        "max_papers": contract.get("max_papers", 12), "mode": contract.get("mode", "live"), "resume": True,
    }
    job, _ = enqueue(db, "research", payload, user.id)
    run.status, run.error = "queued", None
    db.commit()
    return StartRunOut(job=job_out(job), run_id=run.id)
```

- [ ] **Step 5: Implement the new routers**

`api/routers/jobs.py`:

```python
import uuid

from fastapi import APIRouter, Depends

from ...db.models import Job
from ..deps import get_db, require_role
from ..errors import ApiError
from ..schemas import JobOut
from .runs import job_out

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.get("/{job_id}", response_model=JobOut)
def get_job(job_id: uuid.UUID, user=Depends(require_role("member")), db=Depends(get_db)):
    job = db.get(Job, job_id)
    if job is None or (job.created_by != user.id and user.role != "admin"):
        raise ApiError(404, "not_found", "No such job")  # other people's jobs are indistinguishable from missing ones
    return job_out(job)
```

`api/routers/imports.py`:

```python
from fastapi import APIRouter, Depends

from ...jobs import enqueue
from ..deps import get_db, get_settings, require_role
from ..errors import ApiError
from ..schemas import ImportRequest, JobOut
from .runs import job_out

router = APIRouter(prefix="/imports", tags=["imports"])


@router.post("", response_model=JobOut, status_code=202)
def request_import(body: ImportRequest, user=Depends(require_role("admin")), db=Depends(get_db), settings=Depends(get_settings)):
    root = settings.runs_dir if body.kind == "research" else settings.evals_dir
    if not (root / body.name).is_dir():  # the name is regex-validated: it can only address a direct child of the root
        raise ApiError(404, "not_found", f"No {body.kind} folder named {body.name}")
    job, _ = enqueue(db, "import", {"kind": body.kind, "name": body.name}, user.id)
    db.commit()
    return job_out(job)
```

`api/routers/health.py`:

```python
from fastapi import APIRouter

router = APIRouter(prefix="/health", tags=["health"])


@router.get("")
def health():
    """Public liveness probe for the container health check. Touches nothing and reveals nothing."""
    return {"status": "ok"}
```

In `api/app.py` import and include `jobs`, `imports`, `health` (each with `prefix=API_PREFIX`). Because `/runs/{run_id}/...` and `/jobs/{job_id}` use typed path parameters, a non-UUID such as `health` never collides with them.

- [ ] **Step 6: Run**

Run: `pytest tests/test_web_runs_api.py tests/test_web_guards.py -v`
Expected: all pass (the guard test proves the four new routes declare roles and that `health` is the only new public route).

- [ ] **Step 7: Commit**

```bash
ruff format src tests && ruff check . && pytest -q && git add -A
git commit -m "Add start/resume run, jobs, imports and health endpoints" -m "Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 5: `serve`, `worker`, dev worker, and the end-to-end test

**Files:**
- Modify: `src/research_agent/web/cli.py`, `tests/test_web_cli.py`
- Test: `tests/test_web_e2e.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_web_cli.py`:

```python
def test_worker_once_drains_the_queue_and_exits(cli_settings, tmp_path):
    from research_agent.web.auth import create_user
    from research_agent.web.db.models import Job
    from research_agent.web.db.session import make_engine, make_session_factory
    from research_agent.web.jobs import enqueue

    assert main(["worker", "--once"], settings=cli_settings) == 0  # empty queue: exits at once
    factory = make_session_factory(make_engine(cli_settings.database_url))
    with factory() as db:
        admin = create_user(db, email="a@example.org", name="A", role="admin", password="correct horse battery")
        enqueue(db, "import", {"kind": "research", "name": "demo"}, admin.id)
        db.commit()
    assert main(["worker", "--once"], settings=cli_settings) == 0
    assert scalar(cli_settings.database_url, select(Job.status)) == "done"
    assert scalar(cli_settings.database_url, select(func.count()).select_from(Run)) == 1


def test_serve_and_dev_are_registered(capsys):
    from research_agent.web.cli import build_parser

    parser = build_parser()
    assert parser.parse_args(["serve", "--port", "9000"]).port == 9000
    dev = parser.parse_args(["dev", "--with-worker", "--allow-demo"])
    assert dev.with_worker is True and dev.allow_demo is True
```

`tests/test_web_e2e.py`:

```python
"""Start a run through the API, let a real worker execute the real pipeline (demo mode, offline), read the table."""

from fastapi.testclient import TestClient

from research_agent.web.api.app import create_app
from research_agent.web.auth import create_user
from research_agent.web.db.session import make_engine, make_session_factory
from research_agent.web.importer.common import get_or_create_field
from research_agent.web.settings import load_settings
from research_agent.web.worker import Worker

TOPIC = "retrieval augmented generation"
PASSWORD = "correct horse battery"


def test_start_run_worker_import_and_table(fresh_db_url, tmp_path):
    settings = load_settings(
        {
            "RESEARCH_WEB_DATABASE_URL": fresh_db_url,
            "RESEARCH_RUNS_DIR": str(tmp_path / "runs"),
            "RESEARCH_EVALS_DIR": str(tmp_path / "evals"),
            "RESEARCH_GOLD_DIR": str(tmp_path / "gold"),
            "RESEARCH_WEB_COOKIE_SECURE": "false",
            "RESEARCH_WEB_ALLOW_DEMO": "true",
            "RESEARCH_WEB_PROGRESS_POLL_SECONDS": "0.05",
        }
    )
    factory = make_session_factory(make_engine(fresh_db_url))
    with factory() as db:
        create_user(db, email="member@example.org", name="M", role="member", password=PASSWORD)
        field = get_or_create_field(db, TOPIC)
        db.commit()
        field_id = str(field.id)
    client = TestClient(create_app(settings, session_factory=factory))
    login = client.post("/api/v1/auth/login", json={"email": "member@example.org", "password": PASSWORD})
    csrf = {"X-CSRF-Token": login.json()["csrf_token"]}

    started = client.post("/api/v1/runs", json={"field_id": field_id, "max_papers": 3, "mode": "demo"}, headers=csrf)
    assert started.status_code == 202
    job_id, run_id = started.json()["job"]["id"], started.json()["run_id"]
    assert client.get(f"/api/v1/jobs/{job_id}").json()["status"] == "queued"

    Worker(settings, factory).drain()  # the real child process runs the real (demo) pipeline

    job = client.get(f"/api/v1/jobs/{job_id}").json()
    assert job["status"] == "done" and job["error"] is None and job["progress"]["stages"]["rank"] == "completed"
    run = client.get(f"/api/v1/runs/{run_id}").json()
    assert run["status"] == "done" and run["counts"]["screened"] == 3 and run["paper_count"] == 3
    table = client.get(f"/api/v1/runs/{run_id}/papers").json()
    assert table["total"] == 3 and all(row["screen"]["tier"] == "llm" for row in table["items"])
    assert (tmp_path / "runs" / run_id.replace("-", "") / "worker.log").exists()  # process output stays on disk, not in the DB
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/test_web_cli.py tests/test_web_e2e.py -v`
Expected: FAIL (`worker` and `serve` are unknown commands; `--with-worker` is unknown).

- [ ] **Step 3: Implement the commands in `cli.py`**

Add `import threading` and `from .worker import Worker` to the imports, and these functions:

```python
def cmd_serve(args, settings):
    import uvicorn

    uvicorn.run(create_app(settings), host=args.host, port=args.port, log_level="info")
    return 0


def cmd_worker(args, settings):
    worker = Worker(settings)
    if args.once:
        worker.drain()
        return 0
    print(f"worker {worker.worker_id} started (Ctrl-C to stop)")
    try:
        worker.run_forever()
    except KeyboardInterrupt:
        pass
    return 0
```

In `build_parser` add:

```python
    p = sub.add_parser("serve", help="run the API (behind a reverse proxy that terminates TLS)")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8000)
    p.set_defaults(func=cmd_serve)
    p = sub.add_parser("worker", help="run the job worker (the only process that needs LLM provider keys)")
    p.add_argument("--once", action="store_true", help="process queued jobs, then exit")
    p.set_defaults(func=cmd_worker)
```

and on the `dev` parser add `p.add_argument("--with-worker", action="store_true")` and `p.add_argument("--allow-demo", action="store_true")`. In `cmd_dev`: when `args.allow_demo`, add `RESEARCH_WEB_ALLOW_DEMO="true"` to `env` before `load_settings(env)`; and before `uvicorn.run(...)` add:

```python
    stop = threading.Event()
    if args.with_worker:
        threading.Thread(target=Worker(dev_settings).run_forever, kwargs={"stop": stop.is_set}, daemon=True, name="dev-worker").start()
        print("worker started in this process")
    try:
        uvicorn.run(create_app(dev_settings), host=args.host, port=args.port, log_level="info")
    finally:
        stop.set()
```

(replacing the existing bare `uvicorn.run(...)` line).

- [ ] **Step 4: Run**

Run: `pytest tests/test_web_cli.py tests/test_web_e2e.py -v`
Expected: all pass. The end-to-end test starts one real child process running the demo pipeline (a few seconds). If it hangs, run `pytest tests/test_web_e2e.py -x -s` and check `runs/<hex>/worker.log` under the test's `tmp_path` for the child's output.

- [ ] **Step 5: Commit**

```bash
ruff format src tests && ruff check . && pytest -q && git add -A
git commit -m "Add serve and worker commands, a dev worker, and the end-to-end run test" -m "Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 6: Deployment files (written and linted, not run)

**Files:**
- Create: `deploy/Dockerfile`, `deploy/docker-compose.yml`, `deploy/.env.example`, `deploy/worker.env.example`, `.dockerignore`, `docs/deployment.md`
- Test: `tests/test_web_deploy.py`

There is no Docker on the development machine. These files are verified by tests that read them as data (structure and the rule that provider keys exist only in the worker); a person with Docker must run `docker compose config` and `docker compose up`, which `docs/deployment.md` says explicitly.

- [ ] **Step 1: Write the failing tests**

`tests/test_web_deploy.py`:

```python
import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
COMPOSE = ROOT / "deploy" / "docker-compose.yml"
KEYS = ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "TYPESAFE_API_KEY", "RESEARCH_MODEL")


@pytest.fixture(scope="module")
def compose():
    return yaml.safe_load(COMPOSE.read_text())


def test_services_and_startup_order(compose):
    services = compose["services"]
    assert set(services) == {"db", "migrate", "api", "worker"}
    assert services["api"]["depends_on"]["migrate"]["condition"] == "service_completed_successfully"
    assert services["worker"]["depends_on"]["migrate"]["condition"] == "service_completed_successfully"
    assert services["migrate"]["depends_on"]["db"]["condition"] == "service_healthy"
    assert "healthcheck" in services["db"] and "healthcheck" in services["api"]


def test_provider_keys_exist_only_in_the_worker(compose):
    for name in ("db", "migrate", "api"):
        service = compose["services"][name]
        assert "env_file" not in service, f"{name} must not read the worker key file"
        env = service.get("environment") or {}
        assert not any(key in env for key in KEYS), f"{name} must not carry provider keys"
    assert compose["services"]["worker"]["env_file"] == ["worker.env"]


def test_the_api_mounts_run_folders_read_only_and_the_worker_can_write_runs(compose):
    api_volumes = compose["services"]["api"]["volumes"]
    assert api_volumes and all(v.endswith(":ro") for v in api_volumes)
    worker_volumes = compose["services"]["worker"]["volumes"]
    assert any(v.startswith("runs:/data/runs") and not v.endswith(":ro") for v in worker_volumes)
    assert all(v.endswith(":ro") for v in worker_volumes if "/data/evals" in v or "/data/gold" in v)


def test_only_the_api_publishes_a_port_and_only_on_loopback(compose):
    for name, service in compose["services"].items():
        ports = service.get("ports", [])
        if name == "api":
            assert ports and all(p.startswith("127.0.0.1:") for p in ports)
        else:
            assert not ports, f"{name} must not publish ports"


def test_secure_defaults_in_the_api_environment(compose):
    env = compose["services"]["api"]["environment"]
    assert env["RESEARCH_WEB_COOKIE_SECURE"] == "true" and env["RESEARCH_WEB_ALLOW_DEMO"] == "false"
    assert "0.0.0.0" in compose["services"]["api"]["command"]  # inside the container; the published port is loopback only


def test_no_secret_value_is_written_into_any_deployment_file():
    for path in (COMPOSE, ROOT / "deploy" / ".env.example", ROOT / "deploy" / "worker.env.example"):
        text = path.read_text()
        assert not re.search(r"sk-[A-Za-z0-9_-]{8,}|apikey_[0-9a-f]{8,}", text), path
    for name in ("deploy/.env.example", "deploy/worker.env.example"):
        for line in (ROOT / name).read_text().splitlines():
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                assert value == "" or key in {"RESEARCH_MODEL", "RESEARCH_REVIEWER_A_MODEL", "RESEARCH_REVIEWER_B_MODEL", "RESEARCH_ADJUDICATOR_MODEL"}, f"{name}: {key} must be empty in the example"


def test_dockerfile_is_unprivileged_and_never_copies_env_files():
    text = (ROOT / "deploy" / "Dockerfile").read_text()
    assert "USER app" in text and not re.search(r"COPY[^\n]*\.env", text)
    ignore = (ROOT / ".dockerignore").read_text().split()
    assert {".env", ".venv", ".git", "runs", "evals", "gold", ".web-dev"} <= set(ignore)
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/test_web_deploy.py -v`
Expected: FAIL (`FileNotFoundError` for `deploy/docker-compose.yml`).

- [ ] **Step 3: Write `deploy/Dockerfile`**

```dockerfile
FROM python:3.12-slim
ENV PIP_NO_CACHE_DIR=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY pyproject.toml ./
COPY src ./src
RUN pip install '.[web,live]'
RUN useradd --create-home --uid 10001 app \
    && mkdir -p /data/runs /data/evals /data/gold \
    && chown -R app /data
USER app
CMD ["research-web", "--help"]
```

- [ ] **Step 4: Write `deploy/docker-compose.yml`**

```yaml
name: research-agent

x-app-env: &app-env
  RESEARCH_WEB_DATABASE_URL: postgresql+psycopg://research:${DB_PASSWORD:?set DB_PASSWORD in deploy/.env}@db:5432/research
  RESEARCH_RUNS_DIR: /data/runs
  RESEARCH_EVALS_DIR: /data/evals
  RESEARCH_GOLD_DIR: /data/gold

services:
  db:
    image: postgres:16
    environment:
      POSTGRES_DB: research
      POSTGRES_USER: research
      POSTGRES_PASSWORD: ${DB_PASSWORD:?set DB_PASSWORD in deploy/.env}
    volumes:
      - dbdata:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U research -d research"]
      interval: 5s
      timeout: 3s
      retries: 12
    restart: unless-stopped

  migrate:
    build:
      context: ..
      dockerfile: deploy/Dockerfile
    command: ["research-web", "migrate"]
    environment: *app-env
    depends_on:
      db:
        condition: service_healthy
    restart: "no"

  api:
    build:
      context: ..
      dockerfile: deploy/Dockerfile
    command: ["research-web", "serve", "--host", "0.0.0.0", "--port", "8000"]
    environment:
      <<: *app-env
      RESEARCH_WEB_COOKIE_SECURE: "true"
      RESEARCH_WEB_ALLOW_DEMO: "false"
    volumes:
      - runs:/data/runs:ro
      - ${EVALS_DIR:-../evals}:/data/evals:ro
      - ${GOLD_DIR:-../gold}:/data/gold:ro
    depends_on:
      migrate:
        condition: service_completed_successfully
    ports:
      - "127.0.0.1:8000:8000"
    healthcheck:
      test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health')"]
      interval: 10s
      timeout: 3s
      retries: 6
    restart: unless-stopped

  worker:
    build:
      context: ..
      dockerfile: deploy/Dockerfile
    command: ["research-web", "worker"]
    environment: *app-env
    env_file:
      - worker.env
    volumes:
      - runs:/data/runs
      - ${EVALS_DIR:-../evals}:/data/evals:ro
      - ${GOLD_DIR:-../gold}:/data/gold:ro
    depends_on:
      migrate:
        condition: service_completed_successfully
    restart: unless-stopped

volumes:
  dbdata: {}
  runs: {}
```

- [ ] **Step 5: Write the example files and `.dockerignore`**

`deploy/.env.example`:

```
# Copy to deploy/.env. Read by docker compose for variable substitution only.
DB_PASSWORD=
# Optional: where the eval folders and gold files live on the host (defaults: ../evals and ../gold)
# EVALS_DIR=
# GOLD_DIR=
```

`deploy/worker.env.example`:

```
# Copy to deploy/worker.env. This file is read ONLY by the worker service.
# Never commit it. The API container never sees these values.
ANTHROPIC_API_KEY=
OPENAI_API_KEY=
TYPESAFE_API_KEY=
RESEARCH_MODEL=anthropic:claude-sonnet-5
RESEARCH_REVIEWER_A_MODEL=anthropic:claude-sonnet-5
RESEARCH_REVIEWER_B_MODEL=anthropic:claude-sonnet-5
RESEARCH_ADJUDICATOR_MODEL=anthropic:claude-opus-5-5
```

`.dockerignore` (repository root, one entry per line):

```
.env
.venv
.git
.web-dev
.superpowers
runs
evals
gold
docs
tests
web/node_modules
```

Also add `deploy/.env` and `deploy/worker.env` to `.gitignore`.

- [ ] **Step 6: Write `docs/deployment.md`**

Sections (plain prose plus the exact commands): (1) What runs where (the four services, which one holds the keys). (2) First deployment: copy the two example files, set `DB_PASSWORD`, fill `worker.env`, `docker compose -f deploy/docker-compose.yml up -d --build`, then `docker compose -f deploy/docker-compose.yml run --rm -e RESEARCH_WEB_ADMIN_PASSWORD='…' api research-web create-admin --email … --name …`, then import existing folders with `docker compose … run --rm worker research-web import --all`. (3) TLS: put a reverse proxy in front of `127.0.0.1:8000`; the session cookie is `Secure`, so plain HTTP will not keep a login; set HSTS there. (4) Backups: `pg_dump` of the `db` service and a copy of the `runs` volume. (5) Provider policy: only public titles and abstracts leave the company; the allowed providers are exactly the keys present in `worker.env`. (6) **What was not verified on the development machine**: Docker is not installed there, so the compose file is validated by tests as data only; on a Docker host run `docker compose -f deploy/docker-compose.yml config` first and expect it to print the merged file without errors.

- [ ] **Step 7: Run and commit**

Run: `pytest tests/test_web_deploy.py -v`
Expected: 7 passed.

```bash
ruff format src tests && ruff check . && pytest -q && git add -A
git commit -m "Add Docker Compose deployment files with key isolation checks" -m "Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 7: Verify a run end to end in development, and document

**Files:**
- Modify: `docs/web-app.md`, `CLAUDE.md`

A manual check in demo mode (offline, free). **Do not run a live pipeline here.**

- [ ] **Step 1: Start the dev server with a worker and demo runs enabled**

```bash
export RESEARCH_WEB_ADMIN_PASSWORD='choose-a-long-passphrase'
research-web dev --with-worker --allow-demo --import-all --admin-email you@example.org --admin-name "Your Name"
```

Expected: `created admin …`, the import lines from plan 1, `worker started in this process`, then the API line. (If the admin already exists from a previous session the command prints `admin not created: email already registered`, which is fine.)

- [ ] **Step 2: Start a demo run and follow it**

In a second terminal:

```bash
rm -f .web-dev/jar
LOGIN=$(curl -s -c .web-dev/jar -X POST http://127.0.0.1:8000/api/v1/auth/login -H 'content-type: application/json' \
  -d "{\"email\":\"you@example.org\",\"password\":\"$RESEARCH_WEB_ADMIN_PASSWORD\"}")
CSRF=$(python3 -c "import sys,json; print(json.loads(sys.argv[1])['csrf_token'])" "$LOGIN")
FIELD=$(curl -s -b .web-dev/jar http://127.0.0.1:8000/api/v1/fields | python3 -c "import sys,json; print(json.load(sys.stdin)[0]['id'])")
START=$(curl -s -b .web-dev/jar -X POST http://127.0.0.1:8000/api/v1/runs -H 'content-type: application/json' -H "X-CSRF-Token: $CSRF" \
  -H 'Idempotency-Key: manual-check-1' -d "{\"field_id\":\"$FIELD\",\"max_papers\":3,\"mode\":\"demo\"}")
echo "$START"
JOB=$(python3 -c "import sys,json; print(json.loads(sys.argv[1])['job']['id'])" "$START")
RUN=$(python3 -c "import sys,json; print(json.loads(sys.argv[1])['run_id'])" "$START")
for i in 1 2 3 4 5 6 7 8 9 10; do
  curl -s -b .web-dev/jar http://127.0.0.1:8000/api/v1/jobs/$JOB | python3 -c "import sys,json; j=json.load(sys.stdin); print(j['status'], j['progress'].get('stages'))"
  sleep 2
done
```

Expected: the first status is `queued` or `running`, the stage map fills in (`plan`, `discover`, ... `rank` becoming `completed`), and the last lines read `done`. Repeating the same `POST` with the same `Idempotency-Key` returns HTTP 200 with the same job id.

- [ ] **Step 3: Read the imported run and check the guards**

```bash
curl -s -b .web-dev/jar http://127.0.0.1:8000/api/v1/runs/$RUN | python3 -c "import sys,json; r=json.load(sys.stdin); print(r['status'], r['counts'])"
curl -s -b .web-dev/jar "http://127.0.0.1:8000/api/v1/runs/$RUN/papers" | python3 -c "import sys,json; b=json.load(sys.stdin); print(b['total'], [i['screen']['tier'] for i in b['items']])"
curl -s -o /dev/null -w '%{http_code}\n' -X POST http://127.0.0.1:8000/api/v1/runs -b .web-dev/jar -H 'content-type: application/json' -d '{}'
```

Expected: `done {'screened': 3, ...}`, then `3 ['llm', 'llm', 'llm']`, then `403` (a state-changing request without the CSRF header is refused).

Stop the server with Ctrl-C (the worker thread ends with it).

- [ ] **Step 4: Update the documentation**

In `docs/web-app.md` add a section "Runs and the worker" (a few sentences and the commands from Steps 1 and 2: `research-web dev --with-worker --allow-demo`, how a run flows queued → running → done, that live runs need the provider keys in the *worker's* environment and are never started from tests, and the failure text format). In `CLAUDE.md`, under "Comenzi", add `research-web worker` and `research-web serve` with a pointer to `docs/deployment.md`.

- [ ] **Step 5: Final verification and commit**

Run: `ruff check . && pytest -q`
Expected: everything green.

```bash
git add docs/web-app.md CLAUDE.md
git commit -m "Document runs and the worker; verified end to end in demo mode" -m "Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

## Self-review against the spec

**Spec coverage (worker, jobs and deployment part of slice 1)**
- "The API never runs the pipeline; it enqueues" → Task 4 (`POST /runs` writes rows and returns 202) and the e2e test (queued before the worker runs).
- Job queue in PostgreSQL with `FOR UPDATE SKIP LOCKED`, heartbeat, stale requeue with an attempts cap → Task 1 (including a two-thread race test).
- Worker runs `run_research` in a separate process, keys only in the child environment, progress copied into `jobs.progress`, importer on success, sanitized error and kept checkpoint on failure, resume, stale requeue → Tasks 2 and 3.
- `Idempotency-Key`, caps (`max_papers`, active runs), `POST /runs/{id}/resume`, `GET /jobs/{id}`, `POST /imports` (job, by folder name only) → Task 4.
- Failure text never contains raw provider output; `*_API_KEY` values redacted → Tasks 2 and 3.
- Docker Compose with `api`, `worker`, `db` (plus a one-shot `migrate`), API read-only volumes, keys only in the worker, loopback-only published port → Task 6 (tested as data).
- Success criterion "a member can start a demo-mode run that appears in the table" → Task 5 end-to-end test and Task 7 manual check.
- **Not here:** the `web` (nginx + React) service and CSP for the SPA, the frontend, Playwright and CI (plan 3).

**Placeholder scan:** none. Task 7 is a manual check with exact commands and expected output; Task 6 `docs/deployment.md` lists its required sections explicitly.

**Consistency:** `RunSpec`, `build_command`, `child_environment`, `spawn`, `read_progress`, `progress_snapshot`, `failure_message`, `sanitize_error` are defined in Task 2 and used with those names in Task 3. `Worker(settings, session_factory, spawn, sleep, clock, worker_id)` is used identically by the tests, the CLI and the e2e test. `job_out` is defined in `runs.py` and imported by `jobs.py` and `imports.py`. Run `manifest["contract"]` written by `start_run` is what `resume_run` reads. `PUBLIC` in the guard test is updated in the same task that adds `health`.

**Known limits, stated up front:** nothing here was run against Docker; live runs are deliberately never exercised by tests (the child would load the repository `.env`); the worker executes one job at a time (scale by running more worker processes); a run started while the worker is down simply stays queued.
