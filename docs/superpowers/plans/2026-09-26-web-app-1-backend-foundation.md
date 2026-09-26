# Web app 1 of 3: backend foundation — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the database, the run/eval importer, sign-in with roles, and the read API (paper table, paper drawer, runs, evals, System map data), so the real mlffrct-2024 / aiffr-slr-2023 / live-01 data can be imported into PostgreSQL and queried over HTTP.

**Architecture:** New package `src/research_agent/web/` beside the existing pipeline and eval libraries (unchanged apart from one tiny public accessor). SQLAlchemy 2 + Alembic on PostgreSQL 16; FastAPI JSON API under `/api/v1`; importers read run/eval folders with the existing readers and write one transaction per run; raw prompts stay in the run folders and are read on demand through validated `call_key`s. Spec: `docs/superpowers/specs/2026-09-26-web-app-slice1-design.md`. This is plan 1 of 3; plan 2 adds the worker/jobs/Start run, plan 3 the React app.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2, Alembic, psycopg 3, argon2-cffi, PyYAML, pytest with a real PostgreSQL 16 supplied by the pip package `pgserver` (embedded server; no Docker needed), ruff (line length 110).

**Environment facts (verified on the development Mac)**
- No Docker and no system PostgreSQL. Tests and local development use `pgserver` (PostgreSQL 16.2, arm64, starts in ~2 s, `FOR UPDATE SKIP LOCKED` works).
- Docker Compose files are written in plan 2 but **cannot be run on this machine**; they are reviewed by reading and linted, not executed here.
- SQLAlchemy `text()` treats `:name` as a bind parameter, even inside a JSON literal. Use bound parameters (`cast(:j as jsonb)`), never inline JSON with colons.

**Conventions used in every task**
- Work in the repo root with the venv active: `cd /Users/alexandruitu/Projects/research_agent && . .venv/bin/activate`.
- Branch: `feat/web-app`.
- Commit with the trailer `Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>` as the second `-m`.
- After each task: `ruff format src tests && ruff check .` then `pytest -q` must be green before committing.
- A `.env` file with real API keys exists in the repo root: never read, print or commit it. No test touches the network or needs a key.
- Test modules are flat files under `tests/` (`tests/test_web_*.py`), matching the existing layout; shared helpers are `tests/conftest.py` and `tests/web_fixtures.py`.

## Contracts other plans rely on

- Settings: `research_agent.web.settings.Settings`, `load_settings(env=None)`; env vars `RESEARCH_WEB_DATABASE_URL` (required), `RESEARCH_RUNS_DIR`, `RESEARCH_EVALS_DIR`, `RESEARCH_GOLD_DIR`, `RESEARCH_WEB_COOKIE_SECURE` (default `true`).
- DB: `research_agent.web.db.models` (all tables, including `Job`, defined here so one migration covers the slice), `db.session.make_engine/make_session_factory`, `db.migrate.upgrade(url)`.
- API: `research_agent.web.api.app.create_app(settings=None, session_factory=None)`, dependency `research_agent.web.api.deps.get_db`, role guard `require_role("viewer"|"member"|"admin")`, error shape `{"code", "message", "request_id"}`.
- Importers: `import_research_run(db, folder, created_by=None) -> ImportResult`, `import_eval_run(db, folder, created_by=None, gold_dir=None) -> ImportResult`; `ImportResult(run_id, status, warnings)` with `status` in `created | updated | unchanged`.
- Test fixtures: `tests/web_fixtures.py::make_demo_run(dir)` and `make_eval_run(dir)` build a real research run (demo mode) and a real eval run (toy gold) without network.

## File structure

| File | Responsibility |
|---|---|
| `pyproject.toml` (modify) | `web` and `web-dev` extras, `research-web` script |
| `alembic.ini` (create) | repo-root Alembic config (for `alembic revision --autogenerate`) |
| `src/research_agent/web/__init__.py` | package marker |
| `src/research_agent/web/settings.py` | environment-driven settings |
| `src/research_agent/web/db/models.py` | SQLAlchemy models for every table in the spec |
| `src/research_agent/web/db/session.py` | engine and session factory |
| `src/research_agent/web/db/migrate.py` | programmatic `alembic upgrade` |
| `src/research_agent/web/db/migrations/` | Alembic env + versions |
| `src/research_agent/web/security.py` | password hashing, tokens, login rate limiter |
| `src/research_agent/web/auth.py` | users, sessions, roles, provider interface |
| `src/research_agent/web/api/app.py` | `create_app`, error handlers, request id |
| `src/research_agent/web/api/deps.py` | `get_db`, current user, `require_role` |
| `src/research_agent/web/api/schemas.py` | Pydantic response/request models |
| `src/research_agent/web/api/routers/*.py` | auth, users, fields, runs, papers, stages, evals |
| `src/research_agent/web/callstore.py` | call index and raw-call reader for run folders |
| `src/research_agent/web/importer/*.py` | research-run and eval importers |
| `src/research_agent/web/stages.py` + `stages.yaml` | stage catalog and computed status |
| `src/research_agent/web/cli.py` | `research-web` |
| `src/research_agent/eval/report.py` (modify) | public `load_run` accessor |
| `tests/conftest.py`, `tests/web_fixtures.py`, `tests/test_web_*.py` | tests |

---

### Task 0: Dependencies, package skeleton, real-PostgreSQL test fixtures

**Files:**
- Modify: `pyproject.toml`, `.gitignore`
- Create: `src/research_agent/web/__init__.py`, `tests/conftest.py`, `tests/test_web_infra.py`

- [ ] **Step 1: Declare extras and the script in `pyproject.toml`**

Under `[project.optional-dependencies]` add (keep the existing `live`, `ui`, `dev`):

```toml
web = [
  "fastapi>=0.115,<1",
  "uvicorn>=0.30,<1",
  "sqlalchemy>=2.0,<3",
  "alembic>=1.13,<2",
  "psycopg[binary]>=3.2,<4",
  "argon2-cffi>=23,<26",
]
web-dev = ["pgserver>=0.1.4,<1"]
```

Under `[project.scripts]` add `research-web = "research_agent.web.cli:main"`.

- [ ] **Step 2: Ignore local artefacts**

Append to `.gitignore`:

```
.web-dev/
*.log
```

- [ ] **Step 3: Create the package marker**

`src/research_agent/web/__init__.py`:

```python
"""Web app: database, importers, sign-in and read API (slice 1)."""
```

- [ ] **Step 4: Write the failing infra test**

`tests/test_web_infra.py`:

```python
import sqlalchemy as sa


def test_real_postgres_is_available_and_supports_the_queue_primitives(pg_engine):
    with pg_engine.begin() as c:
        assert c.execute(sa.text("select current_setting('server_version_num')::int")).scalar() >= 160000
        c.execute(sa.text("create temp table q(id int primary key, status text, p jsonb)"))
        c.execute(sa.text("insert into q values (1,'queued',cast(:j as jsonb)),(2,'queued','{}')"), {"j": '{"a": 1}'})
        first = c.execute(
            sa.text("select id from q where status='queued' order by id for update skip locked limit 1")
        ).scalar()
        assert first == 1
        assert c.execute(sa.text("select p->>'a' from q where id=1")).scalar() == "1"
```

- [ ] **Step 5: Run to verify it fails**

Run: `pytest tests/test_web_infra.py -v`
Expected: FAIL with `fixture 'pg_engine' not found`.

- [ ] **Step 6: Implement the fixtures in `tests/conftest.py`**

```python
"""Shared fixtures. Web tests use a real PostgreSQL 16 from the pip package `pgserver`."""

import pytest

pgserver = pytest.importorskip("pgserver", reason="install the web-dev extra: pip install -e '.[web,web-dev]'")
sa = pytest.importorskip("sqlalchemy")


@pytest.fixture(scope="session")
def pg_url(tmp_path_factory):
    server = pgserver.get_server(tmp_path_factory.mktemp("pgdata"), cleanup_mode="delete")
    yield server.get_uri().replace("postgresql://", "postgresql+psycopg://", 1)
    server.cleanup()


@pytest.fixture(scope="session")
def pg_engine(pg_url):
    engine = sa.create_engine(pg_url)
    yield engine
    engine.dispose()
```

(Later tasks extend this file with `migrated_engine`, `db`, `app` and `client` fixtures.)

- [ ] **Step 7: Install and run**

Run: `pip install -e '.[dev,live,ui,web,web-dev]' -q && pytest tests/test_web_infra.py -v`
Expected: 1 passed. Then `pytest -q` (the whole suite) must still pass.

- [ ] **Step 8: Commit**

```bash
ruff format src tests && ruff check . && git add -A
git commit -m "Scaffold web package with real-PostgreSQL test fixtures" -m "Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 1: Settings and database schema with a migration

**Files:**
- Create: `src/research_agent/web/settings.py`, `src/research_agent/web/db/__init__.py`, `src/research_agent/web/db/models.py`, `src/research_agent/web/db/session.py`, `src/research_agent/web/db/migrate.py`, `src/research_agent/web/db/migrations/env.py`, `src/research_agent/web/db/migrations/script.py.mako`, `alembic.ini`, one generated file under `src/research_agent/web/db/migrations/versions/`
- Modify: `tests/conftest.py`
- Test: `tests/test_web_db.py`

- [ ] **Step 1: Write the failing tests**

`tests/test_web_db.py`:

```python
import pytest
import sqlalchemy as sa
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext

from research_agent.web.db.models import Base
from research_agent.web.settings import SettingsError, load_settings

TABLES = {
    "users", "sessions", "fields", "criteria", "papers", "runs", "screenings", "criterion_scores",
    "evidence_claims", "reviews", "rankings", "gold_sets", "gold_labels", "eval_reports", "jobs",
}


def test_settings_require_a_database_url(tmp_path):
    with pytest.raises(SettingsError, match="RESEARCH_WEB_DATABASE_URL"):
        load_settings({})
    s = load_settings({"RESEARCH_WEB_DATABASE_URL": "postgresql+psycopg://x/y", "RESEARCH_RUNS_DIR": str(tmp_path)})
    assert s.runs_dir == tmp_path.resolve() and s.cookie_secure is True
    dev = load_settings({"RESEARCH_WEB_DATABASE_URL": "u", "RESEARCH_WEB_COOKIE_SECURE": "false"})
    assert dev.cookie_secure is False


def test_migration_creates_every_table_and_matches_the_models(migrated_engine):
    inspector = sa.inspect(migrated_engine)
    assert TABLES <= set(inspector.get_table_names())
    assert {t.name for t in Base.metadata.sorted_tables} == TABLES
    with migrated_engine.connect() as connection:
        diff = compare_metadata(MigrationContext.configure(connection), Base.metadata)
    assert diff == [], f"models and migration drifted: {diff}"


def test_key_constraints_hold(db):
    from research_agent.web.db.models import Paper, Screening

    db.add(Paper(source_id="MED:1", title="t", abstract="a"))
    db.flush()
    db.add(Paper(source_id="MED:1", title="dup", abstract="a"))
    with pytest.raises(sa.exc.IntegrityError):
        db.flush()
    db.rollback()
    assert Screening.__table__.c.run_id.foreign_keys
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/test_web_db.py -v`
Expected: FAIL, `ModuleNotFoundError: No module named 'research_agent.web.settings'`

- [ ] **Step 3: Implement `settings.py`**

```python
"""Environment-driven settings. No secrets live here except the database URL."""

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[3]


class SettingsError(ValueError):
    pass


@dataclass(frozen=True)
class Settings:
    database_url: str
    runs_dir: Path
    evals_dir: Path
    gold_dir: Path
    stages_path: Path
    cookie_secure: bool = True
    session_idle_hours: int = 8
    session_absolute_days: int = 7
    login_max_attempts: int = 5
    login_window_seconds: int = 300
    max_page_size: int = 200
    min_password_length: int = 12


def load_settings(env: Mapping[str, str] | None = None) -> Settings:
    env = os.environ if env is None else env
    url = env.get("RESEARCH_WEB_DATABASE_URL", "")
    if not url:
        raise SettingsError("Set RESEARCH_WEB_DATABASE_URL")
    folder = lambda name, default: Path(env.get(name) or PROJECT / default).resolve()  # noqa: E731
    return Settings(
        database_url=url,
        runs_dir=folder("RESEARCH_RUNS_DIR", "runs"),
        evals_dir=folder("RESEARCH_EVALS_DIR", "evals"),
        gold_dir=folder("RESEARCH_GOLD_DIR", "gold"),
        stages_path=Path(__file__).with_name("stages.yaml"),
        cookie_secure=env.get("RESEARCH_WEB_COOKIE_SECURE", "true").strip().lower() != "false",
    )
```

- [ ] **Step 4: Implement the models `db/models.py`**

```python
"""Tables for slice 1 (spec section "Data model"). Every table has created_at; keys are UUIDs."""

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint, Uuid, func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


def pk():
    return mapped_column(Uuid, primary_key=True, default=uuid.uuid4)


def created():
    return mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class User(Base):
    __tablename__ = "users"
    id: Mapped[uuid.UUID] = pk()
    email: Mapped[str] = mapped_column(String(320), unique=True)
    name: Mapped[str] = mapped_column(String(200))
    role: Mapped[str] = mapped_column(String(16))  # viewer | member | admin
    password_hash: Mapped[str] = mapped_column(Text)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = created()


class AuthSession(Base):
    __tablename__ = "sessions"
    id: Mapped[uuid.UUID] = pk()
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="CASCADE"))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    csrf_token: Mapped[str] = mapped_column(String(64))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = created()


class Field(Base):
    __tablename__ = "fields"
    id: Mapped[uuid.UUID] = pk()
    name: Mapped[str] = mapped_column(String(200))
    topic: Mapped[str] = mapped_column(Text, unique=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = created()


class Criterion(Base):
    __tablename__ = "criteria"
    __table_args__ = (UniqueConstraint("field_id", "key", "version"),)
    id: Mapped[uuid.UUID] = pk()
    field_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("fields.id", ondelete="CASCADE"))
    key: Mapped[str] = mapped_column(String(100))
    question: Mapped[str] = mapped_column(Text)
    version: Mapped[int] = mapped_column(Integer, default=1)
    position: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = created()


class Paper(Base):
    __tablename__ = "papers"
    id: Mapped[uuid.UUID] = pk()
    source_id: Mapped[str] = mapped_column(String(200), unique=True)
    doi: Mapped[str] = mapped_column(String(300), default="", index=True)
    title: Mapped[str] = mapped_column(Text)
    abstract: Mapped[str] = mapped_column(Text, default="")
    year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    fulltext_ref: Mapped[str | None] = mapped_column(Text, nullable=True)  # reserved for step 2
    created_at: Mapped[datetime] = created()


class GoldSet(Base):
    __tablename__ = "gold_sets"
    id: Mapped[uuid.UUID] = pk()
    name: Mapped[str] = mapped_column(String(200), unique=True)
    citation: Mapped[str] = mapped_column(Text)
    sha256: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = created()


class Run(Base):
    __tablename__ = "runs"
    id: Mapped[uuid.UUID] = pk()
    field_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("fields.id"), index=True)
    kind: Mapped[str] = mapped_column(String(16))  # research | eval
    status: Mapped[str] = mapped_column(String(16))  # queued | running | done | failed
    manifest: Mapped[dict] = mapped_column(JSONB, default=dict)
    folder: Mapped[str | None] = mapped_column(Text, unique=True, nullable=True)
    source_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    gold_set_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("gold_sets.id"), nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id"), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = created()


class Screening(Base):
    __tablename__ = "screenings"
    __table_args__ = (UniqueConstraint("run_id", "paper_id"),)
    id: Mapped[uuid.UUID] = pk()
    run_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("runs.id", ondelete="CASCADE"), index=True)
    paper_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("papers.id"), index=True)
    found_by: Mapped[str] = mapped_column(String(16), default="query")  # query | lookup
    tier: Mapped[str] = mapped_column(String(16))  # jev | llm | rule
    decision: Mapped[str] = mapped_column(String(16))  # include | exclude | uncertain
    jev_decision: Mapped[str | None] = mapped_column(String(16), nullable=True)  # include | exclude | escalate
    llm_decision: Mapped[str | None] = mapped_column(String(16), nullable=True)
    reason: Mapped[str] = mapped_column(Text, default="")
    call_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = created()


class CriterionScore(Base):
    __tablename__ = "criterion_scores"
    screening_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("screenings.id", ondelete="CASCADE"), primary_key=True)
    criterion_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("criteria.id"), primary_key=True)
    probability: Mapped[float] = mapped_column(Float)
    jev_version: Mapped[str] = mapped_column(String(64), default="")


class EvidenceClaim(Base):
    __tablename__ = "evidence_claims"
    id: Mapped[uuid.UUID] = pk()
    run_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("runs.id", ondelete="CASCADE"), index=True)
    paper_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("papers.id"), index=True)
    statement: Mapped[str] = mapped_column(Text)
    quote: Mapped[str] = mapped_column(Text)
    call_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = created()


class Review(Base):
    __tablename__ = "reviews"
    __table_args__ = (UniqueConstraint("run_id", "paper_id", "role"),)
    id: Mapped[uuid.UUID] = pk()
    run_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("runs.id", ondelete="CASCADE"), index=True)
    paper_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("papers.id"), index=True)
    role: Mapped[str] = mapped_column(String(16))  # a | b | adjudicator
    verdict: Mapped[str] = mapped_column(String(16))
    relevance: Mapped[int] = mapped_column(Integer)
    methods: Mapped[int] = mapped_column(Integer)
    support: Mapped[int] = mapped_column(Integer)
    detail: Mapped[dict] = mapped_column(JSONB, default=dict)
    call_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = created()


class Ranking(Base):
    __tablename__ = "rankings"
    run_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("runs.id", ondelete="CASCADE"), primary_key=True)
    paper_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("papers.id"), primary_key=True)
    score: Mapped[float] = mapped_column(Float)
    position: Mapped[int] = mapped_column(Integer)


class GoldLabel(Base):
    __tablename__ = "gold_labels"
    gold_set_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("gold_sets.id", ondelete="CASCADE"), primary_key=True)
    paper_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("papers.id"), primary_key=True)
    label: Mapped[str] = mapped_column(String(16))  # include | not_included
    label_source: Mapped[str] = mapped_column(String(32), default="sr_included_list")
    via: Mapped[str] = mapped_column(String(16), default="query")


class EvalReport(Base):
    __tablename__ = "eval_reports"
    id: Mapped[uuid.UUID] = pk()
    gold_set_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("gold_sets.id"))
    run_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("runs.id", ondelete="CASCADE"), unique=True)
    metrics: Mapped[dict] = mapped_column(JSONB)
    agreement: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = created()


class Job(Base):
    __tablename__ = "jobs"
    __table_args__ = (
        UniqueConstraint("created_by", "idempotency_key"),
        Index("ix_jobs_status_created", "status", "created_at"),
    )
    id: Mapped[uuid.UUID] = pk()
    kind: Mapped[str] = mapped_column(String(16))  # research | import
    payload: Mapped[dict] = mapped_column(JSONB, default=dict)
    status: Mapped[str] = mapped_column(String(16), default="queued")
    progress: Mapped[dict] = mapped_column(JSONB, default=dict)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    locked_by: Mapped[str | None] = mapped_column(String(100), nullable=True)
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id"), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = created()
```

- [ ] **Step 5: Implement `db/session.py` and `db/migrate.py`**

`db/__init__.py` is an empty file with a docstring. `db/session.py`:

```python
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


def make_engine(url):
    return create_engine(url, pool_pre_ping=True)


def make_session_factory(engine):
    return sessionmaker(bind=engine, expire_on_commit=False)
```

`db/migrate.py`:

```python
from pathlib import Path

from alembic import command
from alembic.config import Config

MIGRATIONS = Path(__file__).with_name("migrations")


def alembic_config(url):
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS))
    config.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    return config


def upgrade(url, revision="head"):
    command.upgrade(alembic_config(url), revision)
```

- [ ] **Step 6: Alembic environment**

`db/migrations/env.py`:

```python
import os

from alembic import context
from sqlalchemy import create_engine

from research_agent.web.db.models import Base

config = context.config
target_metadata = Base.metadata


def _url():
    return config.get_main_option("sqlalchemy.url") or os.environ["RESEARCH_WEB_DATABASE_URL"]


def run_migrations_online():
    engine = create_engine(_url())
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()


run_migrations_online()
```

`db/migrations/script.py.mako`:

```mako
"""${message}

Revision ID: ${up_revision}
Revises: ${down_revision | comma,n}
"""
from alembic import op
import sqlalchemy as sa
${imports if imports else ""}

revision = ${repr(up_revision)}
down_revision = ${repr(down_revision)}
branch_labels = ${repr(branch_labels)}
depends_on = ${repr(depends_on)}


def upgrade():
    ${upgrades if upgrades else "pass"}


def downgrade():
    ${downgrades if downgrades else "pass"}
```

Repo-root `alembic.ini` (only for the autogenerate command; the app itself configures Alembic in code):

```ini
[alembic]
script_location = src/research_agent/web/db/migrations
```

- [ ] **Step 7: Generate the initial migration against a scratch database**

Start a throwaway PostgreSQL and autogenerate; review the file, do not hand-write it:

```bash
python - <<'EOF'
import os, subprocess, tempfile, pgserver
server = pgserver.get_server(tempfile.mkdtemp(), cleanup_mode="delete")
url = server.get_uri().replace("postgresql://", "postgresql+psycopg://", 1)
env = dict(os.environ, RESEARCH_WEB_DATABASE_URL=url)
subprocess.run(["alembic", "revision", "--autogenerate", "-m", "initial schema", "--rev-id", "0001"], check=True, env=env)
server.cleanup()
EOF
ls src/research_agent/web/db/migrations/versions/
```

Open the generated `0001_initial_schema.py`: it must contain `op.create_table` for all 15 tables and `downgrade` dropping them. Add `import sqlalchemy as sa` and `from sqlalchemy.dialects import postgresql` if missing.

- [ ] **Step 8: Extend `tests/conftest.py` with migrated fixtures**

Append:

```python
@pytest.fixture(scope="session")
def migrated_engine(pg_url, pg_engine):
    from research_agent.web.db.migrate import upgrade

    upgrade(pg_url)
    return pg_engine


@pytest.fixture
def db(migrated_engine):
    """Each test runs inside a transaction that is rolled back afterwards."""
    from sqlalchemy.orm import Session

    connection = migrated_engine.connect()
    outer = connection.begin()
    session = Session(bind=connection, join_transaction_mode="create_savepoint", expire_on_commit=False)
    yield session
    session.close()
    outer.rollback()
    connection.close()
```

- [ ] **Step 9: Run**

Run: `pytest tests/test_web_db.py -v`
Expected: 3 passed (the drift test proves the migration matches the models).

- [ ] **Step 10: Commit**

```bash
ruff format src tests && ruff check . && pytest -q && git add -A
git commit -m "Add web settings, schema models and initial migration" -m "Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 2: Security primitives

**Files:**
- Create: `src/research_agent/web/security.py`
- Test: `tests/test_web_security.py`

- [ ] **Step 1: Write the failing tests**

```python
from research_agent.web.security import RateLimiter, hash_password, new_token, token_hash, verify_password


def test_password_hash_roundtrip_and_wrong_password():
    hashed = hash_password("correct horse battery")
    assert hashed != "correct horse battery" and hashed.startswith("$argon2id$")
    assert verify_password(hashed, "correct horse battery") is True
    assert verify_password(hashed, "wrong") is False
    assert verify_password("not-a-hash", "x") is False


def test_tokens_are_random_and_hashed_deterministically():
    a, b = new_token(), new_token()
    assert a != b and len(a) >= 40
    assert token_hash(a) == token_hash(a) and token_hash(a) != token_hash(b) and len(token_hash(a)) == 64


def test_rate_limiter_blocks_after_max_attempts_and_recovers():
    now = [1000.0]
    limiter = RateLimiter(max_attempts=3, window_seconds=60, clock=lambda: now[0])
    for _ in range(3):
        assert limiter.allowed("k")
        limiter.record_failure("k")
    assert not limiter.allowed("k")
    assert limiter.allowed("other")
    now[0] += 61
    assert limiter.allowed("k")


def test_rate_limiter_success_clears_failures():
    limiter = RateLimiter(max_attempts=2, window_seconds=60, clock=lambda: 0.0)
    limiter.record_failure("k")
    limiter.record_success("k")
    limiter.record_failure("k")
    assert limiter.allowed("k")
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/test_web_security.py -v`
Expected: FAIL, `ModuleNotFoundError: No module named 'research_agent.web.security'`

- [ ] **Step 3: Implement `security.py`**

```python
"""Password hashing, opaque tokens and a per-process login rate limiter."""

import hashlib
import secrets
import time
from collections import defaultdict, deque

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

_hasher = PasswordHasher()


def hash_password(password):
    return _hasher.hash(password)


def verify_password(hashed, password):
    try:
        return _hasher.verify(hashed, password)
    except (VerificationError, InvalidHashError):
        return False


def new_token():
    return secrets.token_urlsafe(32)


def token_hash(token):
    return hashlib.sha256(token.encode()).hexdigest()


class RateLimiter:
    """Sliding window of failures per key. In-process: with several API processes each keeps its own count."""

    def __init__(self, max_attempts, window_seconds, clock=time.monotonic):
        self.max_attempts, self.window, self.clock = max_attempts, window_seconds, clock
        self.failures = defaultdict(deque)

    def _prune(self, key):
        queue, cutoff = self.failures[key], self.clock() - self.window
        while queue and queue[0] <= cutoff:
            queue.popleft()
        return queue

    def allowed(self, key):
        return len(self._prune(key)) < self.max_attempts

    def record_failure(self, key):
        self._prune(key).append(self.clock())

    def record_success(self, key):
        self.failures.pop(key, None)
```

- [ ] **Step 4: Run to verify pass**

Run: `pytest tests/test_web_security.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
ruff format src tests && ruff check . && pytest -q && git add -A
git commit -m "Add password hashing, session tokens and login rate limiter" -m "Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 3: Auth service, API skeleton and the sign-in routes

**Files:**
- Create: `src/research_agent/web/auth.py`, `src/research_agent/web/api/__init__.py`, `src/research_agent/web/api/errors.py`, `src/research_agent/web/api/deps.py`, `src/research_agent/web/api/schemas.py`, `src/research_agent/web/api/app.py`, `src/research_agent/web/api/routers/__init__.py`, `src/research_agent/web/api/routers/auth.py`
- Modify: `tests/conftest.py`
- Test: `tests/test_web_auth.py`

Design notes: sign-in sits behind `AuthProvider` ("who is this request?") so OIDC can be a second implementation later. Sessions are server-side rows (revocable); the cookie holds only an opaque token whose SHA-256 is stored. Every state-changing request must carry `X-CSRF-Token`. Write endpoints commit explicitly (`db.commit()`); `get_db` only opens and closes a session. Interactive API docs and the OpenAPI URL are disabled (default deny); the schema is dumped offline by `research-web openapi`.

- [ ] **Step 1: Extend `tests/conftest.py` with app, client and user fixtures**

Append:

```python
PASSWORD = "correct horse battery"


@pytest.fixture
def settings(tmp_path, pg_url):
    from research_agent.web.settings import load_settings

    return load_settings(
        {
            "RESEARCH_WEB_DATABASE_URL": pg_url,
            "RESEARCH_RUNS_DIR": str(tmp_path / "runs"),
            "RESEARCH_EVALS_DIR": str(tmp_path / "evals"),
            "RESEARCH_GOLD_DIR": str(tmp_path / "gold"),
            "RESEARCH_WEB_COOKIE_SECURE": "false",
        }
    )


@pytest.fixture
def app(settings, db):
    from research_agent.web.api.app import create_app
    from research_agent.web.api.deps import get_db

    application = create_app(settings, session_factory=lambda: db)
    application.dependency_overrides[get_db] = lambda: db
    return application


@pytest.fixture
def client(app):
    from fastapi.testclient import TestClient

    return TestClient(app)


@pytest.fixture
def users(db):
    from research_agent.web.auth import create_user

    made = {
        role: create_user(db, email=f"{role}@example.org", name=role.title(), role=role, password=PASSWORD)
        for role in ("viewer", "member", "admin")
    }
    db.commit()
    return made


@pytest.fixture
def sign_in(app, users):
    """sign_in(role) -> (client, csrf_headers); each call gets its own cookie jar."""
    from fastapi.testclient import TestClient

    def go(role):
        c = TestClient(app)
        r = c.post("/api/v1/auth/login", json={"email": f"{role}@example.org", "password": PASSWORD})
        assert r.status_code == 200, r.text
        return c, {"X-CSRF-Token": r.json()["csrf_token"]}

    return go
```

- [ ] **Step 2: Write the failing tests**

`tests/test_web_auth.py`:

```python
from datetime import timedelta

import pytest

from research_agent.web.auth import (
    AuthError, authenticate_password, create_user, load_session, revoke_session, start_session, utcnow,
)
from conftest import PASSWORD


def test_create_user_validates_and_hashes(db, settings):
    user = create_user(db, email="  New@Example.ORG ", name=" Nia ", role="member", password=PASSWORD)
    assert user.email == "new@example.org" and user.name == "Nia" and user.password_hash != PASSWORD
    with pytest.raises(AuthError, match="at least 12"):
        create_user(db, email="a@b.c", name="x", role="member", password="short")
    with pytest.raises(AuthError, match="already"):
        create_user(db, email="new@example.org", name="x", role="member", password=PASSWORD)
    with pytest.raises(AuthError, match="role"):
        create_user(db, email="q@b.c", name="x", role="root", password=PASSWORD)


def test_authenticate_password(db, users):
    assert authenticate_password(db, "member@example.org", PASSWORD).role == "member"
    assert authenticate_password(db, "member@example.org", "nope") is None
    assert authenticate_password(db, "ghost@example.org", PASSWORD) is None
    users["member"].active = False
    assert authenticate_password(db, "member@example.org", PASSWORD) is None


def test_session_lifecycle_idle_absolute_and_revoked(db, users, settings):
    now = utcnow()
    token, row = start_session(db, users["viewer"], settings, now=now)
    assert load_session(db, token, settings, now=now + timedelta(hours=1))[1].email == "viewer@example.org"
    assert load_session(db, token, settings, now=now + timedelta(hours=10)) is None  # idle > 8 h since the hour-1 touch
    token2, row2 = start_session(db, users["viewer"], settings, now=now)
    row2.last_seen_at = now + timedelta(days=7, hours=1)  # keep it "active" so only absolute expiry fails
    assert load_session(db, token2, settings, now=now + timedelta(days=7, hours=1)) is None
    token3, row3 = start_session(db, users["viewer"], settings, now=now)
    revoke_session(db, row3, now=now)
    assert load_session(db, token3, settings, now=now) is None


def test_login_me_logout_flow(client, users):
    r = client.post("/api/v1/auth/login", json={"email": "member@example.org", "password": PASSWORD})
    assert r.status_code == 200
    body = r.json()
    assert body["user"]["role"] == "member" and body["csrf_token"] and "password" not in r.text
    assert "ra_session" in r.headers["set-cookie"] and "HttpOnly" in r.headers["set-cookie"]
    me = client.get("/api/v1/auth/me")
    assert me.status_code == 200 and me.json()["user"]["email"] == "member@example.org"
    assert client.post("/api/v1/auth/logout").status_code == 403  # no CSRF header
    ok = client.post("/api/v1/auth/logout", headers={"X-CSRF-Token": body["csrf_token"]})
    assert ok.status_code == 204
    assert client.get("/api/v1/auth/me").status_code == 401  # the session was revoked server-side


def test_wrong_password_is_generic_and_sets_no_cookie(client, users):
    r = client.post("/api/v1/auth/login", json={"email": "member@example.org", "password": "wrong"})
    assert r.status_code == 401 and r.json()["code"] == "invalid_credentials"
    assert "set-cookie" not in r.headers and r.json()["request_id"]
    ghost = client.post("/api/v1/auth/login", json={"email": "ghost@example.org", "password": "wrong"})
    assert ghost.json()["message"] == r.json()["message"]  # no user enumeration


def test_login_is_rate_limited_per_account_and_address(client, users):
    for _ in range(5):
        assert client.post("/api/v1/auth/login", json={"email": "member@example.org", "password": "x"}).status_code == 401
    blocked = client.post("/api/v1/auth/login", json={"email": "member@example.org", "password": PASSWORD})
    assert blocked.status_code == 429 and blocked.json()["code"] == "rate_limited"


def test_me_requires_a_session(client):
    r = client.get("/api/v1/auth/me")
    assert r.status_code == 401 and r.json()["code"] == "unauthorized"


def test_unknown_route_uses_the_error_shape(client):
    r = client.get("/api/v1/nope")
    assert r.status_code == 404 and set(r.json()) >= {"code", "message", "request_id"}
    assert r.headers["x-request-id"] == r.json()["request_id"]


def test_docs_and_openapi_are_not_exposed(client):
    for path in ("/docs", "/redoc", "/openapi.json", "/api/docs", "/api/openapi.json"):
        assert client.get(path).status_code == 404
```

- [ ] **Step 3: Run to verify failure**

Run: `pytest tests/test_web_auth.py -v`
Expected: FAIL, `ModuleNotFoundError: No module named 'research_agent.web.auth'`

- [ ] **Step 4: Implement `auth.py`**

```python
"""Users, sessions and roles. Sign-in sits behind AuthProvider so SSO can replace it later."""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol

from sqlalchemy import select, update

from .db.models import AuthSession, User
from .security import hash_password, new_token, token_hash, verify_password

ROLE_ORDER = {"viewer": 0, "member": 1, "admin": 2}
COOKIE = "ra_session"
TOUCH_SECONDS = 60


class AuthError(ValueError):
    pass


@dataclass(frozen=True)
class CurrentUser:
    id: uuid.UUID
    email: str
    name: str
    role: str
    csrf_token: str
    session_id: uuid.UUID


def utcnow():
    return datetime.now(UTC)


_DUMMY_HASH = hash_password("dummy-password-for-timing")


def create_user(db, *, email, name, role, password, min_password_length=12):
    email = email.strip().lower()
    if role not in ROLE_ORDER:
        raise AuthError("unknown role")
    if "@" not in email:
        raise AuthError("invalid email")
    if len(password) < min_password_length:
        raise AuthError(f"password must have at least {min_password_length} characters")
    if db.scalar(select(User).where(User.email == email)):
        raise AuthError("email already registered")
    user = User(email=email, name=name.strip(), role=role, password_hash=hash_password(password), active=True)
    db.add(user)
    db.flush()
    return user


def authenticate_password(db, email, password):
    user = db.scalar(select(User).where(User.email == email.strip().lower()))
    if user is None:
        verify_password(_DUMMY_HASH, password)  # equalise timing so unknown emails are not distinguishable
        return None
    if not verify_password(user.password_hash, password) or not user.active:
        return None
    return user


def start_session(db, user, settings, now=None):
    now = now or utcnow()
    token = new_token()
    row = AuthSession(
        user_id=user.id,
        token_hash=token_hash(token),
        csrf_token=new_token(),
        expires_at=now + timedelta(days=settings.session_absolute_days),
        last_seen_at=now,
    )
    db.add(row)
    db.flush()
    return token, row


def load_session(db, token, settings, now=None):
    """Return (session_row, user) for a valid token, else None. Slides the idle timer."""
    now = now or utcnow()
    row = db.scalar(select(AuthSession).where(AuthSession.token_hash == token_hash(token)))
    if row is None or row.revoked_at is not None or row.expires_at <= now:
        return None
    if now - row.last_seen_at > timedelta(hours=settings.session_idle_hours):
        return None
    user = db.get(User, row.user_id)
    if user is None or not user.active:
        return None
    if (now - row.last_seen_at).total_seconds() > TOUCH_SECONDS:
        row.last_seen_at = now
    return row, user


def revoke_session(db, row, now=None):
    row.revoked_at = now or utcnow()


def revoke_user_sessions(db, user_id, now=None):
    db.execute(
        update(AuthSession)
        .where(AuthSession.user_id == user_id, AuthSession.revoked_at.is_(None))
        .values(revoked_at=now or utcnow())
    )


class AuthProvider(Protocol):
    def current_user(self, db, request) -> CurrentUser | None: ...


class SessionCookieProvider:
    def __init__(self, settings, clock=utcnow):
        self.settings, self.clock = settings, clock

    def current_user(self, db, request):
        token = request.cookies.get(COOKIE)
        if not token:
            return None
        loaded = load_session(db, token, self.settings, self.clock())
        if loaded is None:
            return None
        row, user = loaded
        db.commit()  # persists the slid idle timer (a no-op when nothing changed)
        return CurrentUser(user.id, user.email, user.name, user.role, row.csrf_token, row.id)
```

- [ ] **Step 5: Implement the API skeleton**

`api/__init__.py` and `api/routers/__init__.py`: docstring-only files.

`api/errors.py`:

```python
"""One error shape for every failure: {"code", "message", "request_id"} (+ "fields" for 422)."""

import logging
from uuid import uuid4

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

log = logging.getLogger("research_agent.web")
CODES = {401: "unauthorized", 403: "forbidden", 404: "not_found", 405: "method_not_allowed", 409: "conflict", 429: "rate_limited"}


class ApiError(Exception):
    def __init__(self, status, code, message):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


def _body(request, code, message, **extra):
    return {"code": code, "message": message, "request_id": getattr(request.state, "request_id", "-"), **extra}


def install_error_handlers(app):
    @app.middleware("http")
    async def request_id(request: Request, call_next):
        rid = request.headers.get("x-request-id") or uuid4().hex[:16]
        request.state.request_id = rid
        response = await call_next(request)
        response.headers["X-Request-ID"] = rid
        return response

    @app.exception_handler(ApiError)
    async def api_error(request, exc):
        return JSONResponse(_body(request, exc.code, exc.message), status_code=exc.status)

    @app.exception_handler(StarletteHTTPException)
    async def http_error(request, exc):
        return JSONResponse(
            _body(request, CODES.get(exc.status_code, "error"), str(exc.detail)), status_code=exc.status_code
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, exc):
        fields = [{"loc": ".".join(str(p) for p in e["loc"]), "message": e["msg"]} for e in exc.errors()]
        return JSONResponse(
            _body(request, "validation_error", "Request validation failed", fields=fields), status_code=422
        )

    @app.exception_handler(Exception)
    async def unexpected(request, exc):
        log.exception("unhandled error, request %s", getattr(request.state, "request_id", "-"))
        return JSONResponse(_body(request, "internal_error", "Unexpected error"), status_code=500)
```

`api/deps.py`:

```python
import hmac

from fastapi import Depends, Request

from ..auth import ROLE_ORDER
from .errors import ApiError

SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


def get_db(request: Request):
    session = request.app.state.session_factory()
    try:
        yield session
    finally:
        session.close()


def get_settings(request: Request):
    return request.app.state.settings


def require_role(role):
    """Dependency factory. Every route declares one (default deny); the guard test relies on `.role`."""
    minimum = ROLE_ORDER[role]

    def dependency(request: Request, db=Depends(get_db)):
        user = request.app.state.auth_provider.current_user(db, request)
        if user is None:
            raise ApiError(401, "unauthorized", "Sign in required")
        if ROLE_ORDER[user.role] < minimum:
            raise ApiError(403, "forbidden", "Your role does not allow this")
        if request.method not in SAFE_METHODS:
            sent = request.headers.get("x-csrf-token", "")
            if not hmac.compare_digest(sent, user.csrf_token):
                raise ApiError(403, "csrf", "Missing or invalid CSRF token")
        return user

    dependency.role = role
    return dependency
```

`api/schemas.py` (extended in later tasks):

```python
import uuid

from pydantic import BaseModel, ConfigDict


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)


class LoginIn(Model):
    email: str
    password: str


class UserOut(Model):
    id: uuid.UUID
    email: str
    name: str
    role: str
    active: bool = True


class SessionOut(Model):
    user: UserOut
    csrf_token: str
```

`api/routers/auth.py`:

```python
from fastapi import APIRouter, Depends, Request, Response

from ...auth import COOKIE, authenticate_password, revoke_session, start_session
from ...db.models import AuthSession
from ..deps import get_db, get_settings, require_role
from ..errors import ApiError
from ..schemas import LoginIn, SessionOut, UserOut

router = APIRouter(prefix="/auth", tags=["auth"])


def _user_out(current):
    return UserOut(id=current.id, email=current.email, name=current.name, role=current.role)


@router.post("/login", response_model=SessionOut)
def login(body: LoginIn, request: Request, response: Response, db=Depends(get_db), settings=Depends(get_settings)):
    limiter = request.app.state.rate_limiter
    key = f"{request.client.host if request.client else '-'}|{body.email.strip().lower()}"
    if not limiter.allowed(key):
        raise ApiError(429, "rate_limited", "Too many attempts; try again later")
    user = authenticate_password(db, body.email, body.password)
    if user is None:
        limiter.record_failure(key)
        raise ApiError(401, "invalid_credentials", "Wrong email or password")
    limiter.record_success(key)
    token, row = start_session(db, user, settings)
    db.commit()
    response.set_cookie(
        COOKIE, token, httponly=True, samesite="lax", secure=settings.cookie_secure,
        max_age=settings.session_absolute_days * 86400, path="/",
    )
    return SessionOut(user=UserOut.model_validate(user), csrf_token=row.csrf_token)


@router.post("/logout", status_code=204)
def logout(response: Response, user=Depends(require_role("viewer")), db=Depends(get_db)):
    row = db.get(AuthSession, user.session_id)
    if row is not None:
        revoke_session(db, row)
        db.commit()
    response.delete_cookie(COOKIE, path="/")


@router.get("/me", response_model=SessionOut)
def me(user=Depends(require_role("viewer"))):
    return SessionOut(user=_user_out(user), csrf_token=user.csrf_token)
```

`api/app.py`:

```python
from fastapi import FastAPI

from ..auth import SessionCookieProvider
from ..db.session import make_engine, make_session_factory
from ..security import RateLimiter
from ..settings import load_settings
from .errors import install_error_handlers
from .routers import auth

API_PREFIX = "/api/v1"


def create_app(settings=None, session_factory=None):
    settings = settings or load_settings()
    if session_factory is None:
        session_factory = make_session_factory(make_engine(settings.database_url))
    # Docs and the schema URL are off (default deny); `research-web openapi` dumps the schema offline.
    app = FastAPI(title="Research Agent", version="1", docs_url=None, redoc_url=None, openapi_url=None)
    app.state.settings = settings
    app.state.session_factory = session_factory
    app.state.rate_limiter = RateLimiter(settings.login_max_attempts, settings.login_window_seconds)
    app.state.auth_provider = SessionCookieProvider(settings)
    install_error_handlers(app)
    app.include_router(auth.router, prefix=API_PREFIX)
    return app
```

- [ ] **Step 6: Run**

Run: `pytest tests/test_web_auth.py -v`
Expected: 9 passed. If `test_wrong_password_is_generic_and_sets_no_cookie` fails on `x-request-id`, check that the middleware in `install_error_handlers` is registered before the routers.

- [ ] **Step 7: Commit**

```bash
ruff format src tests && ruff check . && pytest -q && git add -A
git commit -m "Add auth service, API skeleton with error shape, and sign-in routes" -m "Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 4: Users administration

**Files:**
- Create: `src/research_agent/web/api/routers/users.py`
- Modify: `src/research_agent/web/api/schemas.py`, `src/research_agent/web/api/app.py`
- Test: `tests/test_web_users.py`

Spec addition found while planning: the Users screen needs a list, so `GET /users` (admin) is added next to `POST /users` and `PATCH /users/{id}`.

- [ ] **Step 1: Write the failing tests**

`tests/test_web_users.py`:

```python
import pytest
from fastapi.testclient import TestClient

from conftest import PASSWORD


@pytest.mark.parametrize("role,status", [("viewer", 403), ("member", 403), ("admin", 200)])
def test_list_users_is_admin_only(sign_in, role, status):
    client, _csrf = sign_in(role)
    r = client.get("/api/v1/users")
    assert r.status_code == status
    if status == 200:
        assert {u["email"] for u in r.json()} >= {"viewer@example.org", "member@example.org", "admin@example.org"}
        assert all("password" not in u for u in r.json())


def test_create_user_then_sign_in_as_them(sign_in, app):
    client, csrf = sign_in("admin")
    r = client.post(
        "/api/v1/users",
        json={"email": "Nia@Example.org", "name": "Nia", "role": "member", "password": PASSWORD},
        headers=csrf,
    )
    assert r.status_code == 201 and r.json()["email"] == "nia@example.org" and r.json()["role"] == "member"
    fresh = TestClient(app)
    assert fresh.post("/api/v1/auth/login", json={"email": "nia@example.org", "password": PASSWORD}).status_code == 200


def test_create_user_validation_and_duplicates(sign_in):
    client, csrf = sign_in("admin")
    body = {"email": "x@example.org", "name": "X", "role": "member", "password": PASSWORD}
    assert client.post("/api/v1/users", json=body, headers=csrf).status_code == 201
    dup = client.post("/api/v1/users", json=body, headers=csrf)
    assert dup.status_code == 409 and dup.json()["code"] == "conflict"
    short = client.post("/api/v1/users", json={**body, "email": "y@example.org", "password": "short"}, headers=csrf)
    assert short.status_code == 422 and short.json()["code"] == "invalid_user"
    assert client.post("/api/v1/users", json=body).status_code == 403  # no CSRF header


def test_patch_role_and_deactivate_revokes_sessions(sign_in, users):
    admin, csrf = sign_in("admin")
    member, _ = sign_in("member")
    assert member.get("/api/v1/auth/me").status_code == 200
    r = admin.patch(f"/api/v1/users/{users['member'].id}", json={"active": False}, headers=csrf)
    assert r.status_code == 200 and r.json()["active"] is False
    assert member.get("/api/v1/auth/me").status_code == 401  # sessions revoked immediately
    up = admin.patch(f"/api/v1/users/{users['viewer'].id}", json={"role": "member"}, headers=csrf)
    assert up.json()["role"] == "member"


def test_the_last_active_admin_cannot_be_demoted_or_deactivated(sign_in, users):
    admin, csrf = sign_in("admin")
    for patch in ({"role": "viewer"}, {"active": False}):
        r = admin.patch(f"/api/v1/users/{users['admin'].id}", json=patch, headers=csrf)
        assert r.status_code == 409 and r.json()["code"] == "last_admin"


def test_patch_unknown_user_is_404(sign_in):
    admin, csrf = sign_in("admin")
    r = admin.patch("/api/v1/users/00000000-0000-0000-0000-000000000000", json={"role": "viewer"}, headers=csrf)
    assert r.status_code == 404
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/test_web_users.py -v`
Expected: FAIL, the routes return 404.

- [ ] **Step 3: Extend the schemas (append to `api/schemas.py`)**

```python
class UserCreate(Model):
    email: str
    name: str
    role: str
    password: str


class UserPatch(Model):
    name: str | None = None
    role: str | None = None
    active: bool | None = None
    password: str | None = None
```

- [ ] **Step 4: Implement `api/routers/users.py`**

```python
import uuid

from fastapi import APIRouter, Depends
from sqlalchemy import func, select

from ...auth import ROLE_ORDER, AuthError, create_user, revoke_user_sessions
from ...db.models import User
from ...security import hash_password
from ..deps import get_db, get_settings, require_role
from ..errors import ApiError
from ..schemas import UserCreate, UserOut, UserPatch

router = APIRouter(prefix="/users", tags=["users"])


@router.get("", response_model=list[UserOut])
def list_users(user=Depends(require_role("admin")), db=Depends(get_db)):
    return [UserOut.model_validate(u) for u in db.scalars(select(User).order_by(User.email))]


@router.post("", response_model=UserOut, status_code=201)
def invite(body: UserCreate, user=Depends(require_role("admin")), db=Depends(get_db), settings=Depends(get_settings)):
    try:
        created = create_user(
            db, email=body.email, name=body.name, role=body.role, password=body.password,
            min_password_length=settings.min_password_length,
        )
    except AuthError as exc:
        status, code = (409, "conflict") if "already" in str(exc) else (422, "invalid_user")
        raise ApiError(status, code, str(exc)) from None
    db.commit()
    return UserOut.model_validate(created)


def _active_admins(db):
    return db.scalar(select(func.count()).select_from(User).where(User.role == "admin", User.active.is_(True)))


@router.patch("/{user_id}", response_model=UserOut)
def patch_user(
    user_id: uuid.UUID, body: UserPatch, user=Depends(require_role("admin")), db=Depends(get_db),
    settings=Depends(get_settings),
):
    target = db.get(User, user_id)
    if target is None:
        raise ApiError(404, "not_found", "No such user")
    demoting = body.role is not None and body.role != "admin" and target.role == "admin"
    deactivating = body.active is False and target.active
    if (demoting or deactivating) and target.role == "admin" and target.active and _active_admins(db) <= 1:
        raise ApiError(409, "last_admin", "There must be at least one active admin")
    if body.role is not None:
        if body.role not in ROLE_ORDER:
            raise ApiError(422, "invalid_user", "unknown role")
        target.role = body.role
    if body.name is not None:
        target.name = body.name.strip()
    if body.password is not None:
        if len(body.password) < settings.min_password_length:
            raise ApiError(422, "invalid_user", f"password must have at least {settings.min_password_length} characters")
        target.password_hash = hash_password(body.password)
        revoke_user_sessions(db, target.id)
    if body.active is not None:
        target.active = body.active
        if not body.active:
            revoke_user_sessions(db, target.id)
    db.commit()
    return UserOut.model_validate(target)
```

In `api/app.py`: `from .routers import auth, users` and `app.include_router(users.router, prefix=API_PREFIX)`.

- [ ] **Step 5: Run**

Run: `pytest tests/test_web_users.py -v`
Expected: 8 passed (the parametrized test counts as 3).

- [ ] **Step 6: Commit**

```bash
ruff format src tests && ruff check . && pytest -q && git add -A
git commit -m "Add users administration with role guards and last-admin protection" -m "Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---
### Task 5: Raw-call access for run folders

**Files:**
- Create: `src/research_agent/web/callstore.py`
- Test: `tests/test_web_callstore.py`

The run folders remain the audit trail: `research.sqlite` holds a `calls` table (`key, role, model, prompt_version, input, output`). The web app reads it read-only, finds a folder only from a database id (never from user input), and accepts only 64-hex call keys.

- [ ] **Step 1: Write the failing tests**

`tests/test_web_callstore.py`:

```python
import pytest

from research_agent.agents import Evaluator
from research_agent.schemas import Screen
from research_agent.storage import Store
from research_agent.web.callstore import CallIndex, CallStoreError, read_call, safe_folder

PAYLOAD = {"topic": "t", "paper": {"id": "MED:1", "title": "T", "abstract": "A."}}


def make_store(tmp_path):
    store = Store(tmp_path)
    Evaluator(store).ask("screen", Screen, PAYLOAD)  # demo call recorded in `calls`
    store.record(
        "f" * 64, "jev_screen", "jev-latest", "jev-screen.1",
        {"model": "jev-latest", "state": {"title": "T", "abstract": "A."}, "questions": {}},
        {"model": "jev-1.13.0", "answers": {}},
    )
    return store


def test_index_finds_calls_by_role_and_paper_and_by_jev_title(tmp_path):
    make_store(tmp_path)
    index = CallIndex(tmp_path)
    key = index.key("screen", "MED:1")
    assert key and len(key) == 64
    assert index.key("screen", "MED:2") is None and index.key("extract", "MED:1") is None
    assert index.jev_key("T", "A.") == "f" * 64
    assert index.jev_key("T", "other") is None


def test_index_of_a_folder_without_a_store_is_empty(tmp_path):
    index = CallIndex(tmp_path)
    assert index.key("screen", "MED:1") is None and index.empty


def test_read_call_returns_input_and_output(tmp_path):
    make_store(tmp_path)
    key = CallIndex(tmp_path).key("screen", "MED:1")
    call = read_call(tmp_path, key)
    assert call["role"] == "screen" and call["input"]["payload"]["paper"]["id"] == "MED:1"
    assert call["output"]["decision"] == "include" and call["prompt_version"]


@pytest.mark.parametrize("bad", ["", "abc", "../etc/passwd", "F" * 64, "g" * 64, "a" * 63, "a" * 65, "a'; drop table calls;--"])
def test_call_keys_must_be_64_lowercase_hex(tmp_path, bad):
    make_store(tmp_path)
    with pytest.raises(CallStoreError, match="call key"):
        read_call(tmp_path, bad)


def test_unknown_key_and_missing_store(tmp_path):
    make_store(tmp_path)
    with pytest.raises(CallStoreError, match="not found"):
        read_call(tmp_path, "0" * 64)
    with pytest.raises(CallStoreError, match="research.sqlite"):
        read_call(tmp_path / "nowhere", "0" * 64)


def test_the_store_is_opened_read_only(tmp_path):
    make_store(tmp_path)
    from research_agent.web.callstore import connect_readonly

    with pytest.raises(Exception, match="readonly"):
        connect_readonly(tmp_path).execute("delete from calls")


def test_safe_folder_only_allows_paths_inside_the_configured_roots(tmp_path):
    root = tmp_path / "runs"
    (root / "a").mkdir(parents=True)
    assert safe_folder(str(root / "a"), [root]) == (root / "a").resolve()
    with pytest.raises(CallStoreError, match="outside"):
        safe_folder(str(root / ".." / "etc"), [root])
    outside = tmp_path / "outside"
    outside.mkdir()
    (root / "link").symlink_to(outside)
    with pytest.raises(CallStoreError, match="outside"):
        safe_folder(str(root / "link"), [root])
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/test_web_callstore.py -v`
Expected: FAIL, `ModuleNotFoundError: No module named 'research_agent.web.callstore'`

- [ ] **Step 3: Implement `callstore.py`**

```python
"""Read-only access to a run folder's raw calls (the audit trail)."""

import json
import re
import sqlite3
from pathlib import Path

HEX64 = re.compile(r"^[0-9a-f]{64}$")


class CallStoreError(ValueError):
    pass


def connect_readonly(folder):
    path = Path(folder) / "research.sqlite"
    if not path.is_file():
        raise CallStoreError(f"{folder} has no research.sqlite")
    return sqlite3.connect(f"file:{path}?mode=ro", uri=True)


def safe_folder(folder, roots):
    """Resolve `folder` and require it to live inside one of `roots` (symlinks and `..` cannot escape)."""
    resolved = Path(folder).resolve()
    for root in roots:
        if resolved.is_relative_to(Path(root).resolve()):
            return resolved
    raise CallStoreError("run folder is outside the configured directories")


class CallIndex:
    """Maps (role, paper id) and Jev (title, abstract) to call keys, for the importers."""

    def __init__(self, folder):
        self.by_paper, self.jev_by_text, self.empty = {}, {}, True
        try:
            connection = connect_readonly(folder)
        except CallStoreError:
            return
        with connection:
            for key, role, raw in connection.execute("select key, role, input from calls order by rowid"):
                self.empty = False
                data = json.loads(raw)
                if role == "jev_screen":
                    state = data.get("state", {})
                    self.jev_by_text[(state.get("title"), state.get("abstract"))] = key
                else:
                    paper = (data.get("payload") or {}).get("paper") or {}
                    if "id" in paper:
                        self.by_paper[(role, paper["id"])] = key
        connection.close()

    def key(self, role, paper_id):
        return self.by_paper.get((role, paper_id))

    def jev_key(self, title, abstract):
        return self.jev_by_text.get((title, abstract))


def read_call(folder, key):
    if not isinstance(key, str) or not HEX64.match(key):
        raise CallStoreError("call key must be 64 lowercase hex characters")
    connection = connect_readonly(folder)
    try:
        row = connection.execute(
            "select key, role, model, prompt_version, input, output from calls where key = ?", (key,)
        ).fetchone()
    finally:
        connection.close()
    if row is None:
        raise CallStoreError("call not found")
    return {
        "key": row[0], "role": row[1], "model": row[2], "prompt_version": row[3],
        "input": json.loads(row[4]), "output": json.loads(row[5]),
    }
```

- [ ] **Step 4: Run**

Run: `pytest tests/test_web_callstore.py -v`
Expected: 15 passed (8 parametrized key cases count individually).

- [ ] **Step 5: Commit**

```bash
ruff format src tests && ruff check . && pytest -q && git add -A
git commit -m "Add read-only raw-call access with key validation and folder confinement" -m "Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 6: Test fixtures and the research-run importer

**Files:**
- Create: `tests/web_fixtures.py`, `src/research_agent/web/importer/__init__.py`, `src/research_agent/web/importer/common.py`, `src/research_agent/web/importer/research.py`
- Test: `tests/test_web_import_research.py`

- [ ] **Step 1: Create the shared fixtures `tests/web_fixtures.py`**

```python
"""Real (offline) runs for web tests: a demo-mode research run and a toy eval run."""

import json
from pathlib import Path

from eval_helpers import StubEvaluator, jev_client, make_gold

from research_agent.agents import Evaluator
from research_agent.eval.agreement import run_agreement
from research_agent.eval.gold import write_gold
from research_agent.eval.report import build_report, write_report
from research_agent.eval.screen import run_screen, write_manifest
from research_agent.jev import JevScreener
from research_agent.runner import run_research
from research_agent.schemas import Contract
from research_agent.storage import Store

JEV_P = {1: 0.97, 2: 0.5, 3: 0.03, 4: 0.9, 5: 0.01, 6: 0.02, 7: 0.5, 8: 0.5, 9: 0.95, 10: 0.5, 11: 0.5, 12: 0.04}
LLM_EXCLUDE = {"MED:7", "MED:8"}


def make_demo_run(directory, topic="retrieval augmented generation", max_papers=6):
    """A real research run in demo mode (synthetic papers, no network)."""
    run_research(directory, contract=Contract(topic=topic, mode="demo", max_papers=max_papers))
    return Path(directory)


def add_jev_block(directory, paper_id, probability=0.93):
    """Rewrite report.json so one paper looks Jev-decided (demo mode never uses Jev)."""
    path = Path(directory) / "report.json"
    data = json.loads(path.read_text())
    data["state"]["screens"][paper_id] = {
        "decision": "include",
        "reason": f"Jev: topic_match p={probability:.2f} (jev-1.13.0)",
        "tier": "jev",
        "jev": {
            "decision": "include",
            "probabilities": {"topic_match": probability},
            "model_version": "jev-1.13.0",
            "min_confidence": 0.6,
            "exclude_min_confidence": 0.9,
            "cached": False,
        },
    }
    path.write_text(json.dumps(data))


def make_eval_run(base, name="toy", positive_ids=(1, 2, 3, 4), jev_p=None, llm_exclude=None, with_agreement=True):
    """A real eval run: toy gold, Jev (mock HTTP) + demo LLM screen on every paper, agreement, report."""
    base = Path(base)
    gold_path = base / "gold" / f"{name}.json"
    gold = write_gold(make_gold(n=12, positive_ids=positive_ids, name=name), gold_path)
    run = base / "evals" / name
    store = Store(run)
    jev = JevScreener(store, "k", client=jev_client(JEV_P if jev_p is None else jev_p))
    excluded = LLM_EXCLUDE if llm_exclude is None else llm_exclude
    result = run_screen(gold, store, StubEvaluator(store, exclude=excluded), jev)
    write_manifest(
        run, gold_path=gold_path, gold=gold, mode="demo", models={}, jev_model="jev-latest", screened=result
    )
    if with_agreement:
        run_agreement(gold, run, Evaluator(store), limit=2)
    report = build_report(run)
    write_report(run, report)
    return run, gold_path, report
```

- [ ] **Step 2: Write the failing importer tests**

`tests/test_web_import_research.py`:

```python
import json

import pytest
from sqlalchemy import func, select

from research_agent.web.db.models import (
    CriterionScore, EvidenceClaim, Field, Paper, Ranking, Review, Run, Screening,
)
from research_agent.web.importer.common import ImportFailed
from research_agent.web.importer.research import import_research_run
from web_fixtures import add_jev_block, make_demo_run


def count(db, model):
    return db.scalar(select(func.count()).select_from(model))


def test_import_maps_a_demo_run_into_rows(db, tmp_path):
    folder = make_demo_run(tmp_path / "run")
    result = import_research_run(db, folder)
    assert result.status == "created" and result.warnings == []
    run = db.get(Run, result.run_id)
    assert run.kind == "research" and run.status == "done" and run.folder == str(folder.resolve())
    assert run.manifest["prompt_version"] and run.source_sha256
    assert count(db, Paper) == 6 and count(db, Screening) == 6
    assert count(db, EvidenceClaim) == 6 and count(db, Ranking) == 6
    roles = sorted(r for (r,) in db.execute(select(Review.role)).all())
    assert roles.count("a") == 6 and roles.count("b") == 6 and roles.count("adjudicator") == 6  # demo always disagrees
    screening = db.scalars(select(Screening)).first()
    assert screening.tier == "llm" and screening.llm_decision == "include" and screening.call_key
    field = db.get(Field, run.field_id)
    assert field.topic == "retrieval augmented generation"


def test_jev_decided_papers_carry_probabilities_and_the_jev_call_key(db, tmp_path):
    folder = make_demo_run(tmp_path / "run")
    add_jev_block(folder, "demo:1", 0.93)
    import_research_run(db, folder)
    screening = db.scalar(select(Screening).join(Paper).where(Paper.source_id == "demo:1"))
    assert screening.tier == "jev" and screening.jev_decision == "include" and screening.llm_decision is None
    score = db.scalar(select(CriterionScore).where(CriterionScore.screening_id == screening.id))
    assert score.probability == pytest.approx(0.93) and score.jev_version == "jev-1.13.0"


def test_reimport_is_idempotent_and_updates_in_place(db, tmp_path):
    folder = make_demo_run(tmp_path / "run")
    first = import_research_run(db, folder)
    again = import_research_run(db, folder)
    assert again.status == "unchanged" and again.run_id == first.run_id
    add_jev_block(folder, "demo:2", 0.9)  # changes report.json, hence its hash
    updated = import_research_run(db, folder)
    assert updated.status == "updated" and updated.run_id == first.run_id
    assert count(db, Run) == 1 and count(db, Screening) == 6 and count(db, Paper) == 6
    assert count(db, CriterionScore) == 1


def test_two_runs_share_papers_and_the_field(db, tmp_path):
    import_research_run(db, make_demo_run(tmp_path / "one"))
    import_research_run(db, make_demo_run(tmp_path / "two"))
    assert count(db, Run) == 2 and count(db, Field) == 1 and count(db, Paper) == 6  # papers are global
    assert count(db, Screening) == 12


def test_failed_import_changes_nothing(db, tmp_path):
    folder = make_demo_run(tmp_path / "run")
    path = folder / "report.json"
    data = json.loads(path.read_text())
    data["state"]["screens"]["demo:999"] = data["state"]["screens"]["demo:1"]  # a screen for an unknown paper
    path.write_text(json.dumps(data))
    with pytest.raises(ImportFailed, match="demo:999"):
        import_research_run(db, folder)
    assert count(db, Run) == 0 and count(db, Paper) == 0 and count(db, Screening) == 0


def test_missing_report_is_an_error(db, tmp_path):
    with pytest.raises(ImportFailed, match="report.json"):
        import_research_run(db, tmp_path)


def test_papers_missing_expected_downstream_data_produce_warnings(db, tmp_path):
    folder = make_demo_run(tmp_path / "run")
    path = folder / "report.json"
    data = json.loads(path.read_text())
    del data["state"]["evidence"]["demo:3"]
    path.write_text(json.dumps(data))
    result = import_research_run(db, folder)
    assert any("demo:3" in w and "evidence" in w for w in result.warnings)
```

- [ ] **Step 3: Run to verify failure**

Run: `pytest tests/test_web_import_research.py -v`
Expected: FAIL, `ModuleNotFoundError: No module named 'research_agent.web.importer'`

- [ ] **Step 4: Implement the shared importer helpers**

`importer/__init__.py`: docstring-only. `importer/common.py`:

```python
"""Helpers shared by the research-run and eval importers."""

import hashlib
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import delete, select

from ...connectors import normalize_doi
from ...jev import default_criteria
from ..db.models import (
    Criterion, CriterionScore, EvalReport, EvidenceClaim, Field, Paper, Ranking, Review, Screening,
)


class ImportFailed(RuntimeError):
    """The folder cannot be imported faithfully; nothing was written."""


@dataclass
class ImportResult:
    run_id: uuid.UUID
    status: str  # created | updated | unchanged
    warnings: list[str] = field(default_factory=list)


def file_sha256(*paths):
    digest = hashlib.sha256()
    for path in paths:
        path = Path(path)
        digest.update(path.name.encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


def get_or_create_field(db, topic, created_by=None):
    row = db.scalar(select(Field).where(Field.topic == topic))
    if row is None:
        row = Field(name=topic[:80], topic=topic, created_by=created_by)
        db.add(row)
        db.flush()
        question = default_criteria(topic)["topic_match"]["instructions"]
        db.add(Criterion(field_id=row.id, key="topic_match", question=question, version=1, position=0))
        db.flush()
    return row


def criterion(db, field_row, key):
    """Latest version of a criterion; created (version 1) when a run scored a key the field lacks."""
    found = db.scalar(
        select(Criterion).where(Criterion.field_id == field_row.id, Criterion.key == key).order_by(Criterion.version.desc())
    )
    if found is None:
        found = Criterion(field_id=field_row.id, key=key, question=key, version=1, position=1)
        db.add(found)
        db.flush()
    return found


def to_year(value):
    text = str(value or "")
    return int(text) if text.isdigit() else None


def upsert_paper(db, source_id, doi, title, abstract, year):
    paper = db.scalar(select(Paper).where(Paper.source_id == source_id))
    if paper is None:
        paper = Paper(source_id=source_id, doi="", title=title, abstract=abstract or "")
        db.add(paper)
    paper.doi = normalize_doi(doi or "")
    paper.title = title
    paper.abstract = abstract or ""
    paper.year = to_year(year)
    db.flush()
    return paper


def clear_run(db, run_id):
    """Remove a run's derived rows so it can be re-imported under the same id."""
    screening_ids = select(Screening.id).where(Screening.run_id == run_id)
    db.execute(delete(CriterionScore).where(CriterionScore.screening_id.in_(screening_ids)))
    for model in (Screening, EvidenceClaim, Review, Ranking, EvalReport):
        db.execute(delete(model).where(model.run_id == run_id))
    db.flush()
```

- [ ] **Step 5: Implement the research-run importer `importer/research.py`**

```python
"""Import a finished research run (`runs/<id>/report.json`) into PostgreSQL, one transaction per run."""

import json
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select

from ..callstore import CallIndex
from ..db.models import CriterionScore, EvidenceClaim, Ranking, Review, Run, Screening
from .common import (
    ImportFailed, ImportResult, clear_run, criterion, file_sha256, get_or_create_field, upsert_paper,
)


def _finished_at(folder):
    try:
        text = json.loads((folder / "progress.json").read_text())["updated_at"]
        return datetime.fromisoformat(text)
    except (OSError, ValueError, KeyError):
        return datetime.now(UTC)


def _review_row(run, paper, role, review, call_key, **detail_extra):
    detail = {k: review[k] for k in ("strengths", "weaknesses", "assessment", "takeaways")} | detail_extra
    return Review(
        run_id=run.id, paper_id=paper.id, role=role, verdict=review["verdict"], relevance=review["relevance"],
        methods=review["methods"], support=review["support"], detail=detail, call_key=call_key,
    )


def import_research_run(db, folder, created_by=None):
    folder = Path(folder).resolve()
    report_path = folder / "report.json"
    if not report_path.is_file():
        raise ImportFailed(f"{folder}: no report.json (is the run finished?)")
    digest = file_sha256(report_path)
    run = db.scalar(select(Run).where(Run.folder == str(folder)))
    if run is not None and run.source_sha256 == digest:
        return ImportResult(run.id, "unchanged")
    try:
        data = json.loads(report_path.read_text())
        state, manifest = data["state"], data["manifest"]
        with db.begin_nested():  # all-or-nothing: a failure leaves the database as it was
            return _import(db, folder, digest, run, state, manifest, created_by)
    except (KeyError, ValueError, TypeError) as exc:
        raise ImportFailed(f"{folder}: unexpected report.json content ({type(exc).__name__}: {exc})") from exc


def _import(db, folder, digest, run, state, manifest, created_by):
    warnings = []
    field_row = get_or_create_field(db, state["contract"]["topic"], created_by)
    status = "updated" if run is not None else "created"
    if run is None:
        run = Run(field_id=field_row.id, kind="research", status="done", folder=str(folder), created_by=created_by)
        db.add(run)
    else:
        clear_run(db, run.id)
    run.manifest, run.source_sha256, run.status, run.error = manifest, digest, "done", None
    run.finished_at = _finished_at(folder)
    db.flush()
    calls = CallIndex(folder)
    if calls.empty:
        warnings.append("no raw calls found (research.sqlite missing or empty); the drawer cannot show them")

    papers = {p["id"]: upsert_paper(db, p["id"], p.get("doi"), p["title"], p.get("abstract"), p.get("year")) for p in state["papers"]}

    for pid, screen in state["screens"].items():
        if pid not in papers:
            raise ImportFailed(f"{folder}: screen for unknown paper {pid}")
        paper, tier = papers[pid], screen.get("tier", "llm")
        jev = screen.get("jev") or {}
        key = None
        if tier == "llm":
            key = calls.key("screen", pid)
        elif tier == "jev":
            key = calls.jev_key(paper.title, paper.abstract)
        if key is None and tier != "rule" and not calls.empty:
            warnings.append(f"{pid}: raw call for the {tier} screen not found")
        row = Screening(
            run_id=run.id, paper_id=paper.id, found_by="query", tier=tier, decision=screen["decision"],
            jev_decision=jev.get("decision"), llm_decision=screen["decision"] if tier == "llm" else None,
            reason=screen.get("reason", ""), call_key=key,
        )
        db.add(row)
        db.flush()
        for name, probability in (jev.get("probabilities") or {}).items():
            db.add(CriterionScore(
                screening_id=row.id, criterion_id=criterion(db, field_row, name).id, probability=probability,
                jev_version=jev.get("model_version", ""),
            ))
        if screen["decision"] != "exclude" and tier != "rule" and pid not in state["evidence"]:
            warnings.append(f"{pid}: kept by the screen but has no evidence (expected extraction)")

    for pid, evidence in state["evidence"].items():
        for claim in evidence["claims"]:
            db.add(EvidenceClaim(
                run_id=run.id, paper_id=papers[pid].id, statement=claim["statement"], quote=claim["quote"],
                call_key=calls.key("extract", pid),
            ))
    for role, field_name, call_role in (("a", "reviews_a", "review_a"), ("b", "reviews_b", "review_b")):
        for pid, review in state[field_name].items():
            db.add(_review_row(run, papers[pid], role, review, calls.key(call_role, pid)))
    for pid, decision in state["decisions"].items():
        if decision["adjudicated"]:
            db.add(_review_row(run, papers[pid], "adjudicator", decision["review"], calls.key("adjudicate", pid), reason=decision["reason"]))
    for position, row in enumerate(state["ranking"], start=1):
        db.add(Ranking(run_id=run.id, paper_id=papers[row["paper_id"]].id, score=row["score"], position=position))
    db.flush()
    return ImportResult(run.id, status, warnings)
```

- [ ] **Step 6: Run**

Run: `pytest tests/test_web_import_research.py -v`
Expected: 6 passed. If `test_import_maps_a_demo_run_into_rows` finds a different adjudicator count, check `research_agent/agents.py::_demo` (demo reviewers A/B always differ by two points on methods, so every paper is adjudicated).

- [ ] **Step 7: Commit**

```bash
ruff format src tests && ruff check . && pytest -q && git add -A
git commit -m "Add web test fixtures and the research-run importer" -m "Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 7: The eval importer

**Files:**
- Modify: `src/research_agent/eval/report.py`, `tests/test_eval_report.py`
- Create: `src/research_agent/web/importer/evals.py`
- Test: `tests/test_web_import_eval.py`

- [ ] **Step 1: Add a failing test for a public `load_run` accessor**

The importer needs the same offline reads the report uses (cached Jev probabilities and LLM screen decision for every paper). Expose it publicly instead of importing a private function. Append to `tests/test_eval_report.py`:

```python
def test_load_run_is_a_public_accessor_that_accepts_a_gold_path_override(run_dir, tmp_path):
    from research_agent.eval.report import load_run

    manifest, gold, records, versions = load_run(run_dir, gold_path=tmp_path / "gold.json")
    assert gold.name == "toy" and len(records) == 12 and versions == ["jev-1.13.0"]
    assert manifest["mode"] == "demo"
```

Run: `pytest tests/test_eval_report.py -k load_run -v`
Expected: FAIL, `ImportError: cannot import name 'load_run'`.

- [ ] **Step 2: Implement it in `src/research_agent/eval/report.py`**

Change `_load_run` to accept an optional `gold_path` and add the public wrapper. Replace the first lines of `_load_run`:

```python
def _load_run(run_dir, allow_mixed, gold_path=None):
    manifest = read_manifest(run_dir)
    gold = load_gold(gold_path or manifest["gold_path"])
```

(the rest of the function is unchanged) and add directly below it:

```python
def load_run(run_dir, allow_mixed=False, gold_path=None):
    """Public accessor (used by the web importer): (manifest, gold, records, jev_model_versions).
    `gold_path` overrides the path recorded in the manifest, for runs moved to another machine."""
    return _load_run(run_dir, allow_mixed, gold_path)
```

Run: `pytest -q`
Expected: all green (existing callers pass two arguments, so nothing else changes).

- [ ] **Step 3: Write the failing importer tests**

`tests/test_web_import_eval.py`:

```python
import json

import pytest
from sqlalchemy import func, select

from research_agent.jev import JevThresholds
from research_agent.eval.metrics import cascade_decision
from research_agent.web.db.models import (
    CriterionScore, EvalReport, EvidenceClaim, GoldLabel, GoldSet, Paper, Review, Run, Screening,
)
from research_agent.web.importer.common import ImportFailed
from research_agent.web.importer.evals import import_eval_run
from web_fixtures import JEV_P, make_eval_run


def count(db, model):
    return db.scalar(select(func.count()).select_from(model))


def test_import_maps_an_eval_run(db, tmp_path):
    run_dir, gold_path, report = make_eval_run(tmp_path)
    result = import_eval_run(db, run_dir)
    assert result.status == "created"
    run = db.get(Run, result.run_id)
    assert run.kind == "eval" and run.status == "done" and run.gold_set_id
    assert count(db, Paper) == 12 and count(db, Screening) == 12 and count(db, GoldLabel) == 12
    assert count(db, CriterionScore) == 12
    gold = db.get(GoldSet, run.gold_set_id)
    assert gold.name == "toy" and gold.sha256
    labels = {p.source_id: lab for p, lab in db.execute(select(Paper, GoldLabel.label).join(GoldLabel, GoldLabel.paper_id == Paper.id))}
    assert sum(1 for v in labels.values() if v == "include") == 4


def test_screenings_equal_the_shipped_cascade_and_the_report(db, tmp_path):
    run_dir, gold_path, report = make_eval_run(tmp_path)
    import_eval_run(db, run_dir)
    rows = {p.source_id: s for s, p in db.execute(select(Screening, Paper).join(Paper, Paper.id == Screening.paper_id))}
    for index in range(1, 13):
        s = rows[f"MED:{index}"]
        llm = "exclude" if f"MED:{index}" in {"MED:7", "MED:8"} else "include"
        decision, tier = cascade_decision({"topic_match": JEV_P[index]}, llm, JevThresholds())
        assert (s.decision, s.tier, s.llm_decision) == (decision, tier, llm)
    kept = sum(1 for s in rows.values() if s.decision != "exclude")
    assert kept == report["strategies"]["cascade"]["kept"]  # the UI numbers equal the report numbers
    assert rows["MED:3"].decision == "exclude" and rows["MED:3"].jev_decision == "exclude"
    assert rows["MED:2"].tier == "llm" and rows["MED:2"].jev_decision == "escalate" and rows["MED:2"].call_key


def test_eval_report_and_agreement_rows(db, tmp_path):
    run_dir, gold_path, report = make_eval_run(tmp_path)
    result = import_eval_run(db, run_dir)
    stored = db.scalar(select(EvalReport).where(EvalReport.run_id == result.run_id))
    assert stored.metrics == json.loads((run_dir / "metrics.json").read_text())
    assert stored.agreement["n"] == 6
    roles = [r for (r,) in db.execute(select(Review.role)).all()]
    assert roles.count("a") == 6 and roles.count("b") == 6 and roles.count("adjudicator") == 6
    assert count(db, EvidenceClaim) == 6  # one demo claim per sampled paper
    adjudicator = db.scalar(select(Review).where(Review.role == "adjudicator"))
    assert adjudicator.verdict and "reason" in adjudicator.detail and adjudicator.call_key


def test_reimport_is_idempotent_and_gold_changes_are_refused(db, tmp_path):
    run_dir, _gold, _report = make_eval_run(tmp_path / "one")
    first = import_eval_run(db, run_dir)
    assert import_eval_run(db, run_dir).status == "unchanged"
    other_dir, _g, _r = make_eval_run(tmp_path / "two", positive_ids=(1, 2))  # same gold name, different labels
    with pytest.raises(ImportFailed, match="gold set 'toy' changed"):
        import_eval_run(db, other_dir)
    assert count(db, Run) == 1 and db.get(Run, first.run_id)


def test_gold_dir_override_for_moved_runs(db, tmp_path):
    run_dir, gold_path, _report = make_eval_run(tmp_path / "src")
    moved = tmp_path / "moved" / "gold"
    moved.mkdir(parents=True)
    (moved / gold_path.name).write_bytes(gold_path.read_bytes())
    gold_path.unlink()  # the manifest still points at the deleted original
    assert import_eval_run(db, run_dir, gold_dir=moved).status == "created"


def test_missing_metrics_json_is_an_error(db, tmp_path):
    run_dir, _g, _r = make_eval_run(tmp_path)
    (run_dir / "metrics.json").unlink()
    with pytest.raises(ImportFailed, match="research-eval report"):
        import_eval_run(db, run_dir)


def test_run_without_agreement_still_imports(db, tmp_path):
    run_dir, _g, _r = make_eval_run(tmp_path, with_agreement=False)
    import_eval_run(db, run_dir)
    assert count(db, Review) == 0 and db.scalar(select(EvalReport)).agreement is None


def test_candidates_without_an_abstract_are_kept_as_rule_screenings(db, tmp_path):
    from eval_helpers import StubEvaluator, jev_client, make_gold

    from research_agent.eval.gold import write_gold
    from research_agent.eval.report import build_report, write_report
    from research_agent.eval.screen import run_screen, write_manifest
    from research_agent.jev import JevScreener
    from research_agent.storage import Store

    gold = make_gold(n=6, positive_ids=(1, 2), name="noabs")
    gold.candidates[5].abstract = ""
    gold.candidates[5].flags = ["no_abstract"]
    gold_path = tmp_path / "gold" / "noabs.json"
    gold = write_gold(gold, gold_path)
    run = tmp_path / "evals" / "noabs"
    store = Store(run)
    result = run_screen(gold, store, StubEvaluator(store), JevScreener(store, "k", client=jev_client({})))
    write_manifest(run, gold_path=gold_path, gold=gold, mode="demo", models={}, jev_model="jev-latest", screened=result)
    write_report(run, build_report(run))
    import_eval_run(db, run)
    rule = db.scalar(select(Screening).where(Screening.tier == "rule"))
    assert rule.decision == "uncertain" and "No abstract" in rule.reason
    assert count(db, Screening) == 6 and count(db, CriterionScore) == 5
```

- [ ] **Step 4: Run to verify failure**

Run: `pytest tests/test_web_import_eval.py -v`
Expected: FAIL, `ModuleNotFoundError: No module named 'research_agent.web.importer.evals'`

- [ ] **Step 5: Implement `importer/evals.py`**

```python
"""Import a finished eval run (`evals/<name>/` + its gold file) into PostgreSQL, one transaction per run."""

import json
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import delete, select

from ...eval.metrics import cascade_decision
from ...eval.report import load_run
from ...jev import JevThresholds, decide_from_probabilities
from ..callstore import CallIndex, CallStoreError, read_call
from ..db.models import (
    CriterionScore, EvalReport, EvidenceClaim, GoldLabel, GoldSet, Review, Run, Screening,
)
from .common import ImportFailed, ImportResult, clear_run, criterion, file_sha256, get_or_create_field, upsert_paper

THRESHOLDS = JevThresholds()  # the shipped defaults: what `report` calls "cascade"


def import_eval_run(db, folder, created_by=None, gold_dir=None):
    folder = Path(folder).resolve()
    metrics_path, manifest_path = folder / "metrics.json", folder / "manifest.json"
    if not manifest_path.is_file():
        raise ImportFailed(f"{folder}: no manifest.json (run `research-eval screen` first)")
    if not metrics_path.is_file():
        raise ImportFailed(f"{folder}: no metrics.json (run `research-eval report` first)")
    agreement_path = folder / "agreement.json"
    files = [manifest_path, metrics_path] + ([agreement_path] if agreement_path.is_file() else [])
    digest = file_sha256(*files)
    run = db.scalar(select(Run).where(Run.folder == str(folder)))
    if run is not None and run.source_sha256 == digest:
        return ImportResult(run.id, "unchanged")
    manifest = json.loads(manifest_path.read_text())
    gold_path = Path(manifest["gold_path"])
    if not gold_path.is_file() and gold_dir is not None:
        gold_path = Path(gold_dir) / gold_path.name
    try:
        _m, gold, records, versions = load_run(folder, allow_mixed=True, gold_path=gold_path)
    except (OSError, ValueError, KeyError) as exc:
        raise ImportFailed(f"{folder}: cannot read the eval run ({type(exc).__name__}: {exc})") from exc
    with db.begin_nested():  # all-or-nothing
        return _import(db, folder, digest, run, manifest, gold, records, versions, created_by)


def _gold_set(db, gold):
    row = db.scalar(select(GoldSet).where(GoldSet.name == gold.name))
    if row is not None and row.sha256 != gold.content_sha256:
        raise ImportFailed(
            f"gold set '{gold.name}' changed since it was imported (hash differs); import it under a new name"
        )
    if row is None:
        row = GoldSet(name=gold.name, citation=gold.citation, sha256=gold.content_sha256)
        db.add(row)
        db.flush()
    return row


def _review_row(run, paper, role, review, call_key, **extra):
    detail = {k: review[k] for k in ("strengths", "weaknesses", "assessment", "takeaways") if k in review} | extra
    return Review(
        run_id=run.id, paper_id=paper.id, role=role, verdict=review["verdict"], relevance=review["relevance"],
        methods=review["methods"], support=review["support"], detail=detail, call_key=call_key,
    )


def _import(db, folder, digest, run, manifest, gold, records, versions, created_by):
    warnings = []
    field_row = get_or_create_field(db, gold.topic, created_by)
    gold_row = _gold_set(db, gold)
    status = "updated" if run is not None else "created"
    if run is None:
        run = Run(field_id=field_row.id, kind="eval", status="done", folder=str(folder), created_by=created_by)
        db.add(run)
    else:
        clear_run(db, run.id)
    run.manifest = {**manifest, "jev_model_versions": versions}
    run.source_sha256, run.status, run.error, run.gold_set_id = digest, "done", None, gold_row.id
    run.finished_at = datetime.now(UTC)
    db.flush()

    calls = CallIndex(folder)
    if calls.empty:
        warnings.append("no raw calls found (research.sqlite missing or empty); the drawer cannot show them")
    papers = {c.id: upsert_paper(db, c.id, c.doi, c.title, c.abstract, c.year) for c in gold.candidates}
    db.execute(delete(GoldLabel).where(GoldLabel.gold_set_id == gold_row.id))
    for c in gold.candidates:
        db.add(GoldLabel(gold_set_id=gold_row.id, paper_id=papers[c.id].id, label=c.label, label_source=c.label_source, via=c.via))
    version = versions[0] if len(versions) == 1 else ""

    by_id = {r["id"]: r for r in records}
    for c in gold.candidates:
        paper, record = papers[c.id], by_id.get(c.id)
        if record is None:  # no abstract: never screened, kept for completeness
            db.add(Screening(run_id=run.id, paper_id=paper.id, found_by=c.via, tier="rule", decision="uncertain",
                             reason="No abstract available; not screened"))
            continue
        probabilities, llm = record["probabilities"], record["llm"]
        decision, tier = cascade_decision(probabilities, llm, THRESHOLDS)
        jev_decision = decide_from_probabilities(probabilities, THRESHOLDS)
        key = calls.jev_key(paper.title, paper.abstract) if tier == "jev" else calls.key("screen", c.id)
        if key is None and not calls.empty:
            warnings.append(f"{c.id}: raw call for the {tier} screen not found")
        shown = ", ".join(f"{k}={p:.2f}" for k, p in probabilities.items())
        why = "decided by Jev" if tier == "jev" else "Jev was not confident, so the LLM decided"
        row = Screening(
            run_id=run.id, paper_id=paper.id, found_by=c.via, tier=tier, decision=decision, jev_decision=jev_decision,
            llm_decision=llm, reason=f"Jev {shown} ({why}); LLM screen: {llm}", call_key=key,
        )
        db.add(row)
        db.flush()
        for name, probability in probabilities.items():
            db.add(CriterionScore(screening_id=row.id, criterion_id=criterion(db, field_row, name).id,
                                  probability=probability, jev_version=version))

    agreement_path = folder / "agreement.json"
    agreement = json.loads(agreement_path.read_text())["papers"] if agreement_path.is_file() else {}
    for pid, entry in agreement.items():
        if pid not in papers:
            raise ImportFailed(f"{folder}: agreement.json names an unknown paper {pid}")
        paper = papers[pid]
        db.add(_review_row(run, paper, "a", entry["review_a"], calls.key("review_a", pid)))
        db.add(_review_row(run, paper, "b", entry["review_b"], calls.key("review_b", pid)))
        try:
            extract = read_call(folder, calls.key("extract", pid) or "")["output"]
            for claim in extract["claims"]:
                db.add(EvidenceClaim(run_id=run.id, paper_id=paper.id, statement=claim["statement"], quote=claim["quote"],
                                     call_key=calls.key("extract", pid)))
            if entry["adjudicated"]:
                adjudication = read_call(folder, calls.key("adjudicate", pid) or "")["output"]
                db.add(_review_row(run, paper, "adjudicator", adjudication["review"], calls.key("adjudicate", pid),
                                   reason=adjudication["reason"]))
        except CallStoreError:
            warnings.append(f"{pid}: extraction or adjudication call missing from the run's audit trail")

    metrics = json.loads((folder / "metrics.json").read_text())
    db.add(EvalReport(gold_set_id=gold_row.id, run_id=run.id, metrics=metrics, agreement=metrics.get("agreement")))
    db.flush()
    return ImportResult(run.id, status, warnings)
```

- [ ] **Step 6: Run**

Run: `pytest tests/test_web_import_eval.py tests/test_eval_report.py -v`
Expected: all pass. `test_screenings_equal_the_shipped_cascade_and_the_report` is the consistency test: if it fails on `kept`, the importer and `build_report` disagree about the cascade, which is a bug to fix in the importer, never in the test.

- [ ] **Step 7: Commit**

```bash
ruff format src tests && ruff check . && pytest -q && git add -A
git commit -m "Add the eval-run importer and a public load_run accessor" -m "Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 8: Stage catalog and computed status

**Files:**
- Create: `src/research_agent/web/stages.yaml`, `src/research_agent/web/stages.py`
- Test: `tests/test_web_stages.py`

Rule: a stage is `measured` only when its metric exists in the newest eval data; `caveat` when measured but a data-driven caveat applies; `unmeasured` otherwise; `input` for the topic box. Numbers are read from the same report fields the Evals page uses. Because different eval reports carry different parts (only the main set has agreement), metrics are merged across reports, newest first, per top-level key.

- [ ] **Step 1: Write the failing tests**

`tests/test_web_stages.py`:

```python
from research_agent.web.stages import evaluate_stages, format_headline, load_catalog, lookup, merge_metrics

METRICS = {
    "retrieval_recall": {"k": 15, "n": 16, "value": 0.9375},
    "strategies": {"cascade": {"recall": {"k": 15, "n": 16}}},
    "agreement": {"n": 36, "verdict": {"kappa": 0.9453}, "same_family": True, "adjudication_rate": {"k": 1, "n": 36}},
}


def by_id(stages):
    return {s["id"]: s for s in stages}


def test_catalog_loads_with_every_stage_of_the_pipeline(settings):
    ids = [s["id"] for s in load_catalog(settings.stages_path)]
    assert ids == ["topic", "plan", "search", "dedup", "screen", "extract", "reviewers", "adjudicate", "rank"]


def test_lookup_and_headline_formatting():
    assert lookup(METRICS, "strategies.cascade.recall.k") == 15
    assert lookup(METRICS, "agreement.nope") is None
    assert format_headline("recall {retrieval_recall.k}/{retrieval_recall.n}", METRICS) == "recall 15/16"
    assert format_headline("kappa {agreement.verdict.kappa:.2f}", METRICS) == "kappa 0.95"
    assert format_headline("kappa {agreement.missing:.2f}", METRICS) is None


def test_status_is_computed_from_measurements(settings):
    stages = by_id(evaluate_stages(load_catalog(settings.stages_path), METRICS))
    assert stages["topic"]["status"] == "input"
    assert stages["search"]["status"] == "measured" and stages["search"]["headline"] == "recall 15/16"
    assert stages["screen"]["status"] == "measured" and stages["screen"]["headline"] == "recall 15/16"
    assert stages["extract"]["status"] == "measured"
    assert stages["reviewers"]["status"] == "caveat" and "one model family" in stages["reviewers"]["caveat"]
    assert stages["adjudicate"]["headline"] == "fired 1 of 36"
    assert stages["plan"]["status"] == "unmeasured" and stages["plan"]["headline"] is None
    assert stages["rank"]["status"] == "unmeasured" and stages["dedup"]["status"] == "unmeasured"


def test_without_any_eval_data_nothing_is_green(settings):
    stages = evaluate_stages(load_catalog(settings.stages_path), {})
    assert {s["status"] for s in stages} == {"input", "unmeasured"}


def test_a_stage_turns_green_only_when_its_metric_exists(settings):
    partial = {"retrieval_recall": {"k": 3, "n": 4}}
    stages = by_id(evaluate_stages(load_catalog(settings.stages_path), partial))
    assert stages["search"]["status"] == "measured" and stages["screen"]["status"] == "unmeasured"


def test_reviewers_without_the_family_flag_are_plain_measured(settings):
    metrics = {**METRICS, "agreement": {**METRICS["agreement"], "same_family": False}}
    assert by_id(evaluate_stages(load_catalog(settings.stages_path), metrics))["reviewers"]["status"] == "measured"


def test_merge_takes_each_key_from_the_newest_report_that_has_it():
    newest = {"retrieval_recall": {"k": 1, "n": 2}, "strategies": {"x": 1}}
    older = {"retrieval_recall": {"k": 9, "n": 9}, "agreement": {"n": 5}}
    merged = merge_metrics([newest, older])
    assert merged["retrieval_recall"]["k"] == 1 and merged["agreement"]["n"] == 5 and merged["strategies"] == {"x": 1}
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/test_web_stages.py -v`
Expected: FAIL, `ModuleNotFoundError: No module named 'research_agent.web.stages'`

- [ ] **Step 3: Write `stages.yaml`**

```yaml
stages:
  - id: topic
    title: Topic
    kind: input
    summary: The field's topic sentence and the criteria papers are judged against.
    limits: In this version each field has a single criterion, built from the topic sentence.
  - id: plan
    title: Plan
    summary: A language model turns the topic into up to three literature search queries.
    limits: Query quality has not been measured.
  - id: search
    title: Search
    summary: Europe PMC is searched with the planned queries and duplicate records are merged.
    limits: One page of results per query; abstracts only, no full text.
    measured_by: [retrieval_recall.k, retrieval_recall.n]
    headline: "recall {retrieval_recall.k}/{retrieval_recall.n}"
    data_link: evals
  - id: dedup
    title: Deduplicate
    summary: Records are merged by DOI, or by title and year when a DOI is missing. Code only.
    limits: Verified by unit tests, not measured on real data.
  - id: screen
    title: Screen
    summary: >-
      Decides which papers are worth reading further. Tier 1, Jev, answers the criteria as yes/no
      probabilities and decides when it is confident; tier 2, Claude, screens the rest. A paper is dropped
      automatically only when Jev is very sure.
    limits: Works on the abstract only, so a paper whose abstract never names the method can be lost.
    measured_by: [strategies.cascade.recall.k, strategies.cascade.recall.n]
    headline: "recall {strategies.cascade.recall.k}/{strategies.cascade.recall.n}"
    data_link: papers
  - id: extract
    title: Extract
    summary: Claims are extracted with quotes that must appear exactly in the abstract; anything else is rejected.
    limits: Abstract-level claims only.
    measured_by: [agreement.n]
    headline: "{agreement.n} papers, quotes verified"
    data_link: papers
  - id: reviewers
    title: Reviewers A and B
    summary: Two independent reviews of each kept paper, one supportive and one critical, scored 0 to 4.
    limits: Both reviewers are currently the same model family, so their agreement overstates independence.
    measured_by: [agreement.verdict.kappa]
    headline: "kappa {agreement.verdict.kappa:.2f}"
    caveat_when: agreement.same_family
    caveat: one model family
    data_link: evals
  - id: adjudicate
    title: Adjudicate
    summary: A stronger model resolves reviewer disagreements against the abstract.
    limits: Fires rarely, so its quality is hard to measure.
    measured_by: [agreement.adjudication_rate.k, agreement.adjudication_rate.n]
    headline: "fired {agreement.adjudication_rate.k} of {agreement.adjudication_rate.n}"
    data_link: papers
  - id: rank
    title: Rank
    summary: A score computed in code from the reviews (relevance 40%, methods 30%, support 30%).
    limits: The inputs are model-assigned scores that have not been validated against ground truth.
    data_link: papers
```

- [ ] **Step 4: Implement `stages.py`**

```python
"""Stage catalog for the System map. Status is computed from measurements, never written by hand."""

import re
from pathlib import Path

import yaml

PLACEHOLDER = re.compile(r"\{([a-z0-9_.]+)(?::([^}]*))?\}")


def load_catalog(path):
    return yaml.safe_load(Path(path).read_text())["stages"]


def lookup(data, dotted):
    node = data
    for part in dotted.split("."):
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    return node


def format_headline(template, metrics):
    """Fill `{path}` / `{path:.2f}` placeholders; None when any value is missing."""
    missing = False

    def fill(match):
        nonlocal missing
        value = lookup(metrics, match.group(1))
        if value is None:
            missing = True
            return ""
        return format(value, match.group(2) or "")

    text = PLACEHOLDER.sub(fill, template)
    return None if missing else text


def merge_metrics(reports):
    """`reports` is newest first; each top-level key comes from the newest report that has it."""
    merged = {}
    for report in reports:
        for key, value in report.items():
            merged.setdefault(key, value)
    return merged


def evaluate_stages(catalog, metrics):
    result = []
    for entry in catalog:
        stage = {
            "id": entry["id"], "title": entry["title"], "summary": entry["summary"].strip(),
            "limits": entry.get("limits", ""), "data_link": entry.get("data_link"),
            "status": "unmeasured", "headline": None, "caveat": None,
        }
        if entry.get("kind") == "input":
            stage["status"] = "input"
        elif entry.get("measured_by") and all(lookup(metrics, p) is not None for p in entry["measured_by"]):
            stage["status"] = "measured"
            stage["headline"] = format_headline(entry["headline"], metrics) if entry.get("headline") else None
            if entry.get("caveat_when") and lookup(metrics, entry["caveat_when"]):
                stage["status"], stage["caveat"] = "caveat", entry.get("caveat")
        result.append(stage)
    return result
```

- [ ] **Step 5: Run**

Run: `pytest tests/test_web_stages.py -v`
Expected: 7 passed

- [ ] **Step 6: Commit**

```bash
ruff format src tests && ruff check . && pytest -q && git add -A
git commit -m "Add the stage catalog with status computed from measurements" -m "Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---
### Task 9: Read API for fields, runs, stages and evals

**Files:**
- Modify: `src/research_agent/web/api/schemas.py`, `src/research_agent/web/api/app.py`, `tests/conftest.py`
- Create: `src/research_agent/web/api/routers/fields.py`, `runs.py`, `stages.py`, `evals.py`
- Test: `tests/test_web_read_api.py`

- [ ] **Step 1: Add a shared `imported` fixture to `tests/conftest.py`**

```python
@pytest.fixture
def imported(db, tmp_path):
    """A demo research run and a toy eval run imported into the database (folders live in the roots)."""
    from research_agent.web.importer.evals import import_eval_run
    from research_agent.web.importer.research import import_research_run
    from web_fixtures import make_demo_run, make_eval_run

    research = import_research_run(db, make_demo_run(tmp_path / "runs" / "demo"))
    eval_dir, _gold, report = make_eval_run(tmp_path)
    evaluated = import_eval_run(db, eval_dir)
    db.commit()
    return {"research": research.run_id, "eval": evaluated.run_id, "report": report}
```

- [ ] **Step 2: Write the failing tests**

`tests/test_web_read_api.py`:

```python
import json
import uuid

import pytest


def get(client, path, **params):
    return client.get(f"/api/v1{path}", params=params)


@pytest.mark.parametrize("path", ["/fields", "/runs", "/stages", "/evals"])
def test_read_endpoints_need_a_session(client, path):
    r = get(client, path)
    assert r.status_code == 401 and r.json()["code"] == "unauthorized"


def test_fields_list_with_latest_criteria(sign_in, imported):
    client, _ = sign_in("viewer")
    fields = get(client, "/fields").json()
    assert {f["topic"] for f in fields} == {"retrieval augmented generation", "deep learning CT-FFR"}
    for f in fields:
        assert [c["key"] for c in f["criteria"]] == ["topic_match"] and f["criteria"][0]["version"] == 1
    assert get(client, f"/fields/{fields[0]['id']}").json()["id"] == fields[0]["id"]
    assert get(client, f"/fields/{uuid.uuid4()}").status_code == 404


def test_runs_list_filter_and_detail_counts(sign_in, imported):
    client, _ = sign_in("viewer")
    runs = get(client, "/runs").json()
    assert {r["kind"] for r in runs} == {"research", "eval"}
    assert {r["kind"]: r["paper_count"] for r in runs} == {"research": 6, "eval": 12}
    assert [r["kind"] for r in get(client, "/runs", kind="eval").json()] == ["eval"]
    detail = get(client, f"/runs/{imported['eval']}").json()
    assert detail["gold_set_name"] == "toy" and detail["status"] == "done"
    counts = detail["counts"]
    assert counts == {
        "screened": 12,
        "kept": imported["report"]["strategies"]["cascade"]["kept"],  # the UI number equals the report number
        "dropped": 12 - imported["report"]["strategies"]["cascade"]["kept"],
        "escalated": 5,
        "in_sr": 4,
    }
    assert get(client, f"/runs/{uuid.uuid4()}").status_code == 404
    assert get(client, "/runs/not-a-uuid").status_code == 422


def test_stages_are_computed_from_the_imported_eval_data(sign_in, imported):
    client, _ = sign_in("viewer")
    stages = {s["id"]: s for s in get(client, "/stages").json()}
    assert stages["topic"]["status"] == "input"
    assert stages["search"]["status"] == "measured" and stages["search"]["headline"] == "recall 4/4"
    assert stages["screen"]["status"] == "measured" and stages["screen"]["headline"] == "recall 3/4"
    assert stages["adjudicate"]["status"] == "measured" and stages["adjudicate"]["headline"] == "fired 6 of 6"
    assert stages["plan"]["status"] == "unmeasured"
    assert stages["rank"]["status"] == "unmeasured" and stages["rank"]["limits"]


def test_stages_without_eval_data_are_never_green(sign_in):
    client, _ = sign_in("viewer")
    assert {s["status"] for s in get(client, "/stages").json()} == {"input", "unmeasured"}


def test_evals_list_and_detail_equal_the_stored_report(sign_in, imported, tmp_path):
    client, _ = sign_in("viewer")
    (summary,) = get(client, "/evals").json()
    assert summary["gold_set"]["name"] == "toy" and summary["run_id"] == str(imported["eval"])
    head = summary["headline"]
    assert head["cascade_recall"] == {"k": 3, "n": 4} and head["retrieval_recall"] == {"k": 4, "n": 4}
    assert head["recommended"] is not None and head["screened"] == 12
    detail = get(client, f"/evals/{summary['id']}").json()
    assert detail["metrics"] == json.loads((tmp_path / "evals" / "toy" / "metrics.json").read_text())
    assert detail["agreement"]["n"] == 6
    assert get(client, f"/evals/{uuid.uuid4()}").status_code == 404
```

- [ ] **Step 3: Run to verify failure**

Run: `pytest tests/test_web_read_api.py -v`
Expected: FAIL (routes return 404 / 401 mismatches).

- [ ] **Step 4: Extend `api/schemas.py`**

Append:

```python
from datetime import datetime
from typing import Any, Literal


class CriterionOut(Model):
    id: uuid.UUID
    key: str
    question: str
    version: int
    position: int


class FieldOut(Model):
    id: uuid.UUID
    name: str
    topic: str
    criteria: list[CriterionOut]


class RunCounts(Model):
    screened: int
    kept: int
    dropped: int
    escalated: int
    in_sr: int


class RunOut(Model):
    id: uuid.UUID
    field_id: uuid.UUID
    field_name: str
    kind: str
    status: str
    finished_at: datetime | None
    created_at: datetime
    gold_set_name: str | None
    paper_count: int
    error: str | None
    models: dict[str, str]


class RunDetailOut(RunOut):
    manifest: dict[str, Any]
    counts: RunCounts


class StageOut(Model):
    id: str
    title: str
    summary: str
    limits: str
    status: Literal["input", "measured", "caveat", "unmeasured"]
    headline: str | None
    caveat: str | None
    data_link: str | None


class GoldSetOut(Model):
    id: uuid.UUID
    name: str
    citation: str


class Ratio(Model):
    k: int
    n: int


class Recommended(Model):
    min_confidence: float
    exclude_min_confidence: float


class EvalHeadline(Model):
    retrieval_recall: Ratio | None
    cascade_recall: Ratio | None
    recommended: Recommended | None
    kappa: float | None
    same_family: bool | None
    screened: int | None


class EvalSummaryOut(Model):
    id: uuid.UUID
    gold_set: GoldSetOut
    run_id: uuid.UUID
    created_at: datetime
    headline: EvalHeadline


class EvalDetailOut(Model):
    id: uuid.UUID
    gold_set: GoldSetOut
    run_id: uuid.UUID
    created_at: datetime
    metrics: dict[str, Any]
    agreement: dict[str, Any] | None
```

- [ ] **Step 5: Implement the routers**

`api/routers/fields.py`:

```python
import uuid

from fastapi import APIRouter, Depends
from sqlalchemy import select

from ...db.models import Criterion, Field
from ..deps import get_db, require_role
from ..errors import ApiError
from ..schemas import CriterionOut, FieldOut

router = APIRouter(prefix="/fields", tags=["fields"])


def field_out(db, field):
    latest = {}
    rows = db.scalars(select(Criterion).where(Criterion.field_id == field.id).order_by(Criterion.position, Criterion.version.desc()))
    for row in rows:
        latest.setdefault(row.key, row)  # newest version of each key
    return FieldOut(
        id=field.id, name=field.name, topic=field.topic,
        criteria=[CriterionOut.model_validate(c) for c in sorted(latest.values(), key=lambda c: c.position)],
    )


@router.get("", response_model=list[FieldOut])
def list_fields(user=Depends(require_role("viewer")), db=Depends(get_db)):
    return [field_out(db, f) for f in db.scalars(select(Field).order_by(Field.name))]


@router.get("/{field_id}", response_model=FieldOut)
def get_field(field_id: uuid.UUID, user=Depends(require_role("viewer")), db=Depends(get_db)):
    field = db.get(Field, field_id)
    if field is None:
        raise ApiError(404, "not_found", "No such field")
    return field_out(db, field)
```

`api/routers/runs.py`:

```python
import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select

from ...db.models import Field, GoldLabel, GoldSet, Run, Screening
from ..deps import get_db, require_role
from ..errors import ApiError
from ..schemas import RunCounts, RunDetailOut, RunOut

router = APIRouter(prefix="/runs", tags=["runs"])


def _run_out(db, run, cls=RunOut, **extra):
    field = db.get(Field, run.field_id)
    gold = db.get(GoldSet, run.gold_set_id) if run.gold_set_id else None
    paper_count = db.scalar(select(func.count()).select_from(Screening).where(Screening.run_id == run.id))
    models = {k: v for k, v in (run.manifest.get("models") or {}).items() if isinstance(v, str)}
    return cls(
        id=run.id, field_id=run.field_id, field_name=field.name, kind=run.kind, status=run.status,
        finished_at=run.finished_at, created_at=run.created_at, gold_set_name=gold.name if gold else None,
        paper_count=paper_count, error=run.error, models=models, **extra,
    )


def counts_for(db, run):
    rows = db.execute(select(Screening.decision, Screening.jev_decision).where(Screening.run_id == run.id)).all()
    in_sr = 0
    if run.gold_set_id:
        in_sr = db.scalar(
            select(func.count()).select_from(GoldLabel)
            .join(Screening, Screening.paper_id == GoldLabel.paper_id)
            .where(Screening.run_id == run.id, GoldLabel.gold_set_id == run.gold_set_id, GoldLabel.label == "include")
        )
    kept = sum(1 for decision, _ in rows if decision != "exclude")
    return RunCounts(
        screened=len(rows), kept=kept, dropped=len(rows) - kept,
        escalated=sum(1 for _, jev in rows if jev == "escalate"), in_sr=in_sr,
    )


@router.get("", response_model=list[RunOut])
def list_runs(
    kind: str | None = Query(None, pattern="^(research|eval)$"), field_id: uuid.UUID | None = None,
    user=Depends(require_role("viewer")), db=Depends(get_db),
):
    stmt = select(Run).order_by(Run.created_at.desc())
    if kind:
        stmt = stmt.where(Run.kind == kind)
    if field_id:
        stmt = stmt.where(Run.field_id == field_id)
    return [_run_out(db, r) for r in db.scalars(stmt)]


@router.get("/{run_id}", response_model=RunDetailOut)
def get_run(run_id: uuid.UUID, user=Depends(require_role("viewer")), db=Depends(get_db)):
    run = db.get(Run, run_id)
    if run is None:
        raise ApiError(404, "not_found", "No such run")
    return _run_out(db, run, RunDetailOut, manifest=run.manifest, counts=counts_for(db, run))
```

`api/routers/stages.py`:

```python
from fastapi import APIRouter, Depends, Request
from sqlalchemy import select

from ...db.models import EvalReport
from ...stages import evaluate_stages, load_catalog, merge_metrics
from ..deps import get_db, get_settings, require_role
from ..schemas import StageOut

router = APIRouter(prefix="/stages", tags=["stages"])


@router.get("", response_model=list[StageOut])
def list_stages(user=Depends(require_role("viewer")), db=Depends(get_db), settings=Depends(get_settings)):
    reports = [r.metrics for r in db.scalars(select(EvalReport).order_by(EvalReport.created_at.desc()))]
    return evaluate_stages(load_catalog(settings.stages_path), merge_metrics(reports))
```

`api/routers/evals.py`:

```python
import uuid

from fastapi import APIRouter, Depends
from sqlalchemy import select

from ...db.models import EvalReport, GoldSet
from ..deps import get_db, require_role
from ..errors import ApiError
from ..schemas import EvalDetailOut, EvalHeadline, EvalSummaryOut, GoldSetOut

router = APIRouter(prefix="/evals", tags=["evals"])


def _ratio(rate):
    return {"k": rate["k"], "n": rate["n"]} if rate else None


def headline(metrics):
    recommended = metrics.get("recommended")
    agreement = metrics.get("agreement") or {}
    return EvalHeadline(
        retrieval_recall=_ratio(metrics.get("retrieval_recall")),
        cascade_recall=_ratio(((metrics.get("strategies") or {}).get("cascade") or {}).get("recall")),
        recommended=(
            {"min_confidence": recommended["min_confidence"], "exclude_min_confidence": recommended["exclude_min_confidence"]}
            if recommended else None
        ),
        kappa=(agreement.get("verdict") or {}).get("kappa"),
        same_family=agreement.get("same_family"),
        screened=(metrics.get("counts") or {}).get("screened"),
    )


def _gold(db, report):
    return GoldSetOut.model_validate(db.get(GoldSet, report.gold_set_id))


@router.get("", response_model=list[EvalSummaryOut])
def list_evals(user=Depends(require_role("viewer")), db=Depends(get_db)):
    return [
        EvalSummaryOut(id=r.id, gold_set=_gold(db, r), run_id=r.run_id, created_at=r.created_at, headline=headline(r.metrics))
        for r in db.scalars(select(EvalReport).order_by(EvalReport.created_at.desc()))
    ]


@router.get("/{eval_id}", response_model=EvalDetailOut)
def get_eval(eval_id: uuid.UUID, user=Depends(require_role("viewer")), db=Depends(get_db)):
    report = db.get(EvalReport, eval_id)
    if report is None:
        raise ApiError(404, "not_found", "No such eval report")
    return EvalDetailOut(
        id=report.id, gold_set=_gold(db, report), run_id=report.run_id, created_at=report.created_at,
        metrics=report.metrics, agreement=report.agreement,
    )
```

In `api/app.py` import `fields, runs, stages, evals` and include each router with `prefix=API_PREFIX`.

- [ ] **Step 6: Run**

Run: `pytest tests/test_web_read_api.py -v`
Expected: 8 passed (the parametrized test counts as 4). If the `screen` headline is not `recall 3/4`, the imported eval report differs from the fixture's default thresholds; check `web_fixtures.JEV_P`.

- [ ] **Step 7: Commit**

```bash
ruff format src tests && ruff check . && pytest -q && git add -A
git commit -m "Add read API for fields, runs, stages and evals" -m "Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 10: The paper table

**Files:**
- Modify: `src/research_agent/web/api/schemas.py`
- Create: `src/research_agent/web/papers.py`, `src/research_agent/web/api/routers/papers.py`
- Modify: `src/research_agent/web/api/app.py`
- Test: `tests/test_web_papers.py`

One row per paper, one cell per stage. Cell states are never conflated: `null` = the stage does not apply to this paper (a dash in the UI); `{"missing": true}` = the data was expected and is not there (hatched in the UI). Rule: downstream data (extract, reviews) is *expected* only for research runs, for papers that were not dropped and were not skipped for lack of an abstract; eval runs only have downstream data for the agreement sample, so the absence there is `null`. Rank absence is always `null` (only the top papers are ranked).

- [ ] **Step 1: Write the failing tests**

`tests/test_web_papers.py`:

```python
import pytest
from sqlalchemy import delete, select

from research_agent.web.db.models import EvidenceClaim, Paper


def table(client, run_id, **params):
    return client.get(f"/api/v1/runs/{run_id}/papers", params=params)


def rows_by_source(response):
    return {r["paper"]["source_id"]: r for r in response.json()["items"]}


def test_needs_a_session_and_a_real_run(client, sign_in, imported):
    assert table(client, imported["eval"]).status_code == 401
    viewer, _ = sign_in("viewer")
    assert table(viewer, "00000000-0000-0000-0000-000000000000").status_code == 404


def test_eval_run_rows_carry_every_stage_cell(sign_in, imported):
    viewer, _ = sign_in("viewer")
    body = table(viewer, imported["eval"], page_size=50).json()
    assert body["total"] == 12 and body["page"] == 1 and len(body["items"]) == 12
    rows = {r["paper"]["source_id"]: r for r in body["items"]}
    lost = rows["MED:3"]  # Jev p=0.03: auto-dropped although the SR included it
    assert lost["in_sr"] is True and lost["found_by"] == "query"
    assert lost["screen"] == {
        "tier": "jev", "decision": "exclude", "jev_decision": "exclude", "llm_decision": "include",
        "criteria": {"topic_match": 0.03},
    }
    assert lost["extract"] is None and lost["reviews"] is None and lost["rank"] is None  # dropped: not applicable
    escalated = rows["MED:2"]
    assert escalated["screen"]["tier"] == "llm" and escalated["screen"]["jev_decision"] == "escalate"
    assert rows["MED:5"]["in_sr"] is False
    assert rows["MED:9"]["extract"] is None  # kept by Jev but outside the agreement sample: not applicable, not missing


def test_agreement_sample_rows_show_claims_and_reviews(sign_in, imported):
    viewer, _ = sign_in("viewer")
    row = rows_by_source(table(viewer, imported["eval"]))["MED:1"]
    assert row["extract"] == {"claims": 1, "quotes_verified": True}
    assert row["reviews"] == {"a": "include", "b": "include", "adjudicated": True, "adjudicator": "include"}


def test_research_run_rows_and_the_missing_versus_not_applicable_distinction(sign_in, imported, db):
    viewer, _ = sign_in("viewer")
    body = table(viewer, imported["research"]).json()
    assert body["total"] == 6
    row = rows_by_source(table(viewer, imported["research"]))["demo:1"]
    assert row["in_sr"] is None and row["found_by"] == "query"
    assert row["extract"]["claims"] == 1 and row["reviews"]["adjudicated"] is True and row["rank"]["position"] >= 1
    paper = db.scalar(select(Paper).where(Paper.source_id == "demo:2"))
    db.execute(delete(EvidenceClaim).where(EvidenceClaim.paper_id == paper.id))
    db.commit()
    gone = rows_by_source(table(viewer, imported["research"]))["demo:2"]
    assert gone["extract"] == {"missing": True}  # expected in a research run, not there: hatched, not a dash


@pytest.mark.parametrize(
    "params,expected",
    [
        ({"decision": "exclude"}, 6),
        ({"decision": "include"}, 6),
        ({"tier": "jev"}, 7),
        ({"tier": "llm"}, 5),
        ({"escalated": "true"}, 5),
        ({"escalated": "false"}, 7),
        ({"in_sr": "true"}, 4),
        ({"in_sr": "false"}, 8),
        ({"criterion": "topic_match", "p_min": 0.9}, 3),
        ({"criterion": "topic_match", "p_max": 0.05}, 4),
        ({"criterion": "topic_match", "p_min": 0.4, "p_max": 0.6}, 5),
    ],
)
def test_filters(sign_in, imported, params, expected):
    viewer, _ = sign_in("viewer")
    assert table(viewer, imported["eval"], **params).json()["total"] == expected


def test_sorting_and_paging(sign_in, imported):
    viewer, _ = sign_in("viewer")
    by_title = [r["paper"]["title"] for r in table(viewer, imported["eval"]).json()["items"]]
    assert by_title == sorted(by_title, key=str.lower)
    top = table(viewer, imported["eval"], sort="criterion:topic_match", direction="desc").json()["items"][0]
    assert top["paper"]["source_id"] == "MED:1"
    third = table(viewer, imported["eval"], page_size=5, page=3).json()
    assert third["total"] == 12 and len(third["items"]) == 2 and third["page"] == 3 and third["page_size"] == 5
    ranked = table(viewer, imported["research"], sort="score", direction="desc").json()["items"]
    assert ranked[0]["rank"]["position"] == 1


@pytest.mark.parametrize("params", [{"page_size": 201}, {"page": 0}, {"sort": "drop table"}, {"decision": "maybe"}, {"tier": "x"}])
def test_bad_parameters_are_rejected(sign_in, imported, params):
    viewer, _ = sign_in("viewer")
    r = table(viewer, imported["eval"], **params)
    assert r.status_code == 422 and r.json()["code"] == "validation_error"
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/test_web_papers.py -v`
Expected: FAIL (the route does not exist).

- [ ] **Step 3: Add the row schemas (append to `api/schemas.py`)**

```python
class PaperRef(Model):
    id: uuid.UUID
    source_id: str
    title: str
    year: int | None
    doi: str


class ScreenCell(Model):
    tier: str
    decision: str
    jev_decision: str | None
    llm_decision: str | None
    criteria: dict[str, float]


class ExtractCell(Model):
    claims: int
    quotes_verified: bool


class MissingCell(Model):
    missing: Literal[True]


class ReviewsCell(Model):
    a: str | None
    b: str | None
    adjudicated: bool
    adjudicator: str | None


class RankCell(Model):
    score: float
    position: int


class PaperRow(Model):
    paper: PaperRef
    found_by: str
    in_sr: bool | None
    screen: ScreenCell
    extract: ExtractCell | MissingCell | None
    reviews: ReviewsCell | MissingCell | None
    rank: RankCell | None


class PaperPage(Model):
    items: list[PaperRow]
    total: int
    page: int
    page_size: int
```

- [ ] **Step 4: Implement `papers.py` (the query and the row assembly)**

```python
"""The paper table: one run's papers joined with every stage, filtered, sorted and paged in SQL."""

from collections import defaultdict
from dataclasses import dataclass

from sqlalchemy import and_, exists, func, or_, select
from sqlalchemy.orm import aliased

from .db.models import (
    Criterion, CriterionScore, EvidenceClaim, GoldLabel, Paper, Ranking, Review, Screening,
)


@dataclass
class PaperQuery:
    page: int = 1
    page_size: int = 50
    sort: str = "title"
    direction: str = "asc"
    decision: str | None = None
    tier: str | None = None
    escalated: bool | None = None
    in_sr: bool | None = None
    criterion: str | None = None
    p_min: float | None = None
    p_max: float | None = None


def _criterion_probability(key):
    return (
        select(CriterionScore.probability)
        .join(Criterion, Criterion.id == CriterionScore.criterion_id)
        .where(CriterionScore.screening_id == Screening.id, Criterion.key == key)
        .limit(1)
        .scalar_subquery()
    )


def expects_downstream(run, screening):
    """Extraction and reviews are expected only in research runs, for papers that were kept and had an abstract."""
    return run.kind == "research" and screening.decision != "exclude" and screening.tier != "rule"


def build_row(run, screening, paper, scores, claims, verdicts, rank, label):
    a, b, adjudicator = verdicts
    expected = expects_downstream(run, screening)
    if claims:
        extract = {"claims": claims, "quotes_verified": True}
    else:
        extract = {"missing": True} if expected else None
    if a is not None or b is not None:
        reviews = {"a": a, "b": b, "adjudicated": adjudicator is not None, "adjudicator": adjudicator}
    else:
        reviews = {"missing": True} if expected else None
    return {
        "paper": {"id": paper.id, "source_id": paper.source_id, "title": paper.title, "year": paper.year, "doi": paper.doi},
        "found_by": screening.found_by,
        "in_sr": None if run.gold_set_id is None else label == "include",
        "screen": {
            "tier": screening.tier, "decision": screening.decision, "jev_decision": screening.jev_decision,
            "llm_decision": screening.llm_decision, "criteria": scores,
        },
        "extract": extract,
        "reviews": reviews,
        "rank": {"score": rank[0], "position": rank[1]} if rank[0] is not None else None,
    }


def paper_table(db, run, q):
    ra, rb, rj, gl = aliased(Review), aliased(Review), aliased(Review), aliased(GoldLabel)
    claims = (
        select(EvidenceClaim.paper_id.label("paper_id"), func.count().label("n"))
        .where(EvidenceClaim.run_id == run.id)
        .group_by(EvidenceClaim.paper_id)
        .subquery()
    )

    def review_join(alias, role):
        return and_(alias.run_id == Screening.run_id, alias.paper_id == Screening.paper_id, alias.role == role)

    stmt = (
        select(Screening, Paper, ra.verdict, rb.verdict, rj.verdict, claims.c.n, Ranking.score, Ranking.position, gl.label)
        .join(Paper, Paper.id == Screening.paper_id)
        .outerjoin(ra, review_join(ra, "a"))
        .outerjoin(rb, review_join(rb, "b"))
        .outerjoin(rj, review_join(rj, "adjudicator"))
        .outerjoin(claims, claims.c.paper_id == Screening.paper_id)
        .outerjoin(Ranking, and_(Ranking.run_id == Screening.run_id, Ranking.paper_id == Screening.paper_id))
        .outerjoin(gl, and_(gl.gold_set_id == run.gold_set_id, gl.paper_id == Screening.paper_id))
        .where(Screening.run_id == run.id)
    )
    if q.decision:
        stmt = stmt.where(Screening.decision == q.decision)
    if q.tier:
        stmt = stmt.where(Screening.tier == q.tier)
    if q.escalated is True:
        stmt = stmt.where(Screening.jev_decision == "escalate")
    elif q.escalated is False:
        stmt = stmt.where(or_(Screening.jev_decision.is_(None), Screening.jev_decision != "escalate"))
    if q.in_sr is True:
        stmt = stmt.where(gl.label == "include")
    elif q.in_sr is False:
        stmt = stmt.where(or_(gl.label.is_(None), gl.label != "include"))
    if q.criterion:
        conditions = [CriterionScore.screening_id == Screening.id, Criterion.key == q.criterion]
        if q.p_min is not None:
            conditions.append(CriterionScore.probability >= q.p_min)
        if q.p_max is not None:
            conditions.append(CriterionScore.probability <= q.p_max)
        stmt = stmt.where(
            exists().where(CriterionScore.criterion_id == Criterion.id, *conditions).correlate(Screening)
        )

    total = db.scalar(
        select(func.count()).select_from(stmt.with_only_columns(Screening.id, maintain_column_froms=True).subquery())
    )
    if q.sort == "title":
        key = func.lower(Paper.title)
    elif q.sort == "year":
        key = Paper.year
    elif q.sort == "score":
        key = Ranking.score
    else:
        key = _criterion_probability(q.sort.split(":", 1)[1])
    ordering = key.desc().nulls_last() if q.direction == "desc" else key.asc().nulls_last()
    rows = db.execute(stmt.order_by(ordering, Paper.source_id).limit(q.page_size).offset((q.page - 1) * q.page_size)).all()

    scores = defaultdict(dict)
    ids = [r[0].id for r in rows]
    if ids:
        for screening_id, name, probability in db.execute(
            select(CriterionScore.screening_id, Criterion.key, CriterionScore.probability)
            .join(Criterion, Criterion.id == CriterionScore.criterion_id)
            .where(CriterionScore.screening_id.in_(ids))
        ):
            scores[screening_id][name] = probability
    items = [
        build_row(run, s, p, scores[s.id], n or 0, (va, vb, vj), (score, position), label)
        for s, p, va, vb, vj, n, score, position, label in rows
    ]
    return items, total
```

- [ ] **Step 5: Implement the router `api/routers/papers.py`**

```python
import uuid
from typing import Literal

from fastapi import APIRouter, Depends, Query

from ...db.models import Run
from ...papers import PaperQuery, paper_table
from ..deps import get_db, get_settings, require_role
from ..errors import ApiError
from ..schemas import PaperPage

router = APIRouter(prefix="/runs", tags=["papers"])


@router.get("/{run_id}/papers", response_model=PaperPage)
def list_papers(
    run_id: uuid.UUID,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1),
    sort: str = Query("title", pattern=r"^(title|year|score|criterion:[a-z0-9_]+)$"),
    direction: Literal["asc", "desc"] = "asc",
    decision: Literal["include", "exclude", "uncertain"] | None = None,
    tier: Literal["jev", "llm", "rule"] | None = None,
    escalated: bool | None = None,
    in_sr: bool | None = None,
    criterion: str | None = Query(None, pattern=r"^[a-z0-9_]+$"),
    p_min: float | None = Query(None, ge=0, le=1),
    p_max: float | None = Query(None, ge=0, le=1),
    user=Depends(require_role("viewer")),
    db=Depends(get_db),
    settings=Depends(get_settings),
):
    if page_size > settings.max_page_size:
        raise ApiError(422, "validation_error", f"page_size must be at most {settings.max_page_size}")
    run = db.get(Run, run_id)
    if run is None:
        raise ApiError(404, "not_found", "No such run")
    query = PaperQuery(page, page_size, sort, direction, decision, tier, escalated, in_sr, criterion, p_min, p_max)
    items, total = paper_table(db, run, query)
    return PaperPage(items=items, total=total, page=page, page_size=page_size)
```

Include the router in `api/app.py` (`from .routers import ... papers` and `app.include_router(papers.router, prefix=API_PREFIX)`).

- [ ] **Step 6: Run**

Run: `pytest tests/test_web_papers.py -v`
Expected: all pass. Notes for the implementer: (a) if the `total` query fails with duplicate column names, keep `with_only_columns(..., maintain_column_froms=True)` and verify the joins survive (print the SQL); (b) SQLAlchemy renders `gl.gold_set_id == None` as `IS NULL` when the run has no gold set, which never matches a real row, so `in_sr` becomes `None` for research runs by design; (c) the filter counts in the parametrized test come from the fixture data: Jev drops papers 3, 5, 6, 12; the demo LLM drops 7 and 8; escalated are 2, 7, 8, 10, 11.

- [ ] **Step 7: Commit**

```bash
ruff format src tests && ruff check . && pytest -q && git add -A
git commit -m "Add the paper table endpoint with filters, sorting and paging" -m "Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 11: The paper drawer and raw calls

**Files:**
- Modify: `src/research_agent/web/api/schemas.py`, `src/research_agent/web/papers.py`, `src/research_agent/web/api/routers/papers.py`
- Test: `tests/test_web_drawer.py`

- [ ] **Step 1: Write the failing tests**

`tests/test_web_drawer.py`:

```python
import uuid

from sqlalchemy import select

from research_agent.web.db.models import Paper, Run


def paper_id(db, source_id):
    return db.scalar(select(Paper.id).where(Paper.source_id == source_id))


def drawer(client, run, paper):
    return client.get(f"/api/v1/runs/{run}/papers/{paper}")


def test_drawer_for_a_paper_the_screen_dropped(sign_in, imported, db):
    viewer, _ = sign_in("viewer")
    body = drawer(viewer, imported["eval"], paper_id(db, "MED:3")).json()
    assert body["paper"]["source_id"] == "MED:3" and body["paper"]["abstract"]
    assert body["in_sr"] is True and body["label_source"] == "sr_included_list" and body["found_by"] == "query"
    screening = body["screening"]
    assert (screening["tier"], screening["decision"], screening["jev_decision"]) == ("jev", "exclude", "exclude")
    assert screening["criteria"][0]["key"] == "topic_match" and screening["criteria"][0]["probability"] == 0.03
    assert screening["criteria"][0]["question"] and "Jev" in screening["reason"]
    assert body["claims"] == [] and body["reviews"] == [] and body["rank"] is None


def test_drawer_for_a_reviewed_paper(sign_in, imported, db):
    viewer, _ = sign_in("viewer")
    body = drawer(viewer, imported["eval"], paper_id(db, "MED:1")).json()
    assert len(body["claims"]) == 1 and body["claims"][0]["quote"] in body["paper"]["abstract"]
    assert [r["role"] for r in body["reviews"]] == ["a", "b", "adjudicator"]
    assert body["reviews"][0]["detail"]["assessment"] and body["reviews"][2]["detail"]["reason"]
    assert all(r["call_key"] for r in body["reviews"])


def test_drawer_of_a_research_run_has_a_rank(sign_in, imported, db):
    viewer, _ = sign_in("viewer")
    body = drawer(viewer, imported["research"], paper_id(db, "demo:1")).json()
    assert body["in_sr"] is None and body["label_source"] is None and body["rank"]["position"] >= 1


def test_drawer_404s(sign_in, imported, db):
    viewer, _ = sign_in("viewer")
    assert drawer(viewer, imported["eval"], uuid.uuid4()).status_code == 404
    assert drawer(viewer, uuid.uuid4(), paper_id(db, "MED:1")).status_code == 404
    assert drawer(viewer, imported["eval"], paper_id(db, "demo:1")).status_code == 404  # not part of that run


def test_raw_calls_are_for_members_and_confined(sign_in, imported, db):
    viewer, _ = sign_in("viewer")
    member, _ = sign_in("member")
    key = drawer(viewer, imported["eval"], paper_id(db, "MED:2")).json()["screening"]["call_key"]
    url = f"/api/v1/runs/{imported['eval']}/calls/{key}"
    assert viewer.get(url).status_code == 403
    call = member.get(url).json()
    assert call["role"] == "screen" and call["input"]["payload"]["paper"]["id"] == "MED:2" and call["output"]["decision"]
    bad = member.get(f"/api/v1/runs/{imported['eval']}/calls/not-hex")
    assert bad.status_code == 422 and bad.json()["code"] == "invalid_call_key"
    unknown = member.get(f"/api/v1/runs/{imported['eval']}/calls/{'0' * 64}")
    assert unknown.status_code == 404 and unknown.json()["code"] == "call_not_found"
    run = db.get(Run, imported["eval"])
    run.folder = "/etc"
    db.commit()
    gone = member.get(url)
    assert gone.status_code == 409 and gone.json()["code"] == "no_audit_trail"


def test_a_jev_decided_paper_exposes_the_jev_call(sign_in, imported, db):
    viewer, _ = sign_in("viewer")
    member, _ = sign_in("member")
    key = drawer(viewer, imported["eval"], paper_id(db, "MED:1")).json()["screening"]["call_key"]
    call = member.get(f"/api/v1/runs/{imported['eval']}/calls/{key}").json()
    assert call["role"] == "jev_screen" and "questions" in call["input"]
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/test_web_drawer.py -v`
Expected: FAIL (routes missing).

- [ ] **Step 3: Add the drawer schemas (append to `api/schemas.py`)**

```python
class PaperDetail(Model):
    id: uuid.UUID
    source_id: str
    title: str
    abstract: str
    year: int | None
    doi: str


class CriterionScoreOut(Model):
    key: str
    question: str
    probability: float
    jev_version: str


class ScreeningOut(Model):
    tier: str
    decision: str
    jev_decision: str | None
    llm_decision: str | None
    reason: str
    call_key: str | None
    criteria: list[CriterionScoreOut]


class ClaimOut(Model):
    statement: str
    quote: str
    call_key: str | None


class ReviewOut(Model):
    role: str
    verdict: str
    relevance: int
    methods: int
    support: int
    detail: dict[str, Any]
    call_key: str | None


class DrawerOut(Model):
    paper: PaperDetail
    found_by: str
    in_sr: bool | None
    label_source: str | None
    screening: ScreeningOut
    claims: list[ClaimOut]
    reviews: list[ReviewOut]
    rank: RankCell | None


class CallOut(Model):
    key: str
    role: str
    model: str
    prompt_version: str
    input: dict[str, Any]
    output: dict[str, Any]
```

- [ ] **Step 4: Add `paper_drawer` to `papers.py`**

Add the missing imports (`Paper` and the others already imported; add `Run`) and append:

```python
ROLE_ORDER = {"a": 0, "b": 1, "adjudicator": 2}


def paper_drawer(db, run, paper):
    screening = db.scalar(select(Screening).where(Screening.run_id == run.id, Screening.paper_id == paper.id))
    if screening is None:
        return None
    scores = db.execute(
        select(Criterion.key, Criterion.question, CriterionScore.probability, CriterionScore.jev_version)
        .join(CriterionScore, CriterionScore.criterion_id == Criterion.id)
        .where(CriterionScore.screening_id == screening.id)
        .order_by(Criterion.position, Criterion.key)
    ).all()
    label = db.scalar(select(GoldLabel).where(GoldLabel.gold_set_id == run.gold_set_id, GoldLabel.paper_id == paper.id)) if run.gold_set_id else None
    claims = db.scalars(select(EvidenceClaim).where(EvidenceClaim.run_id == run.id, EvidenceClaim.paper_id == paper.id).order_by(EvidenceClaim.created_at, EvidenceClaim.id))
    reviews = sorted(
        db.scalars(select(Review).where(Review.run_id == run.id, Review.paper_id == paper.id)), key=lambda r: ROLE_ORDER[r.role]
    )
    rank = db.scalar(select(Ranking).where(Ranking.run_id == run.id, Ranking.paper_id == paper.id))
    return {
        "paper": {"id": paper.id, "source_id": paper.source_id, "title": paper.title, "abstract": paper.abstract, "year": paper.year, "doi": paper.doi},
        "found_by": screening.found_by,
        "in_sr": None if run.gold_set_id is None else (label is not None and label.label == "include"),
        "label_source": label.label_source if label else None,
        "screening": {
            "tier": screening.tier, "decision": screening.decision, "jev_decision": screening.jev_decision,
            "llm_decision": screening.llm_decision, "reason": screening.reason, "call_key": screening.call_key,
            "criteria": [{"key": k, "question": q, "probability": p, "jev_version": v} for k, q, p, v in scores],
        },
        "claims": [{"statement": c.statement, "quote": c.quote, "call_key": c.call_key} for c in claims],
        "reviews": [
            {"role": r.role, "verdict": r.verdict, "relevance": r.relevance, "methods": r.methods, "support": r.support,
             "detail": r.detail, "call_key": r.call_key}
            for r in reviews
        ],
        "rank": {"score": rank.score, "position": rank.position} if rank else None,
    }
```

- [ ] **Step 5: Add the two routes to `api/routers/papers.py`**

Add imports (`from ...callstore import CallStoreError, read_call, safe_folder`, `from ...db.models import Paper, Run`, `from ...papers import paper_drawer`, and `CallOut, DrawerOut` from schemas) and append:

```python
@router.get("/{run_id}/papers/{paper_id}", response_model=DrawerOut)
def get_paper(run_id: uuid.UUID, paper_id: uuid.UUID, user=Depends(require_role("viewer")), db=Depends(get_db)):
    run, paper = db.get(Run, run_id), db.get(Paper, paper_id)
    if run is None or paper is None:
        raise ApiError(404, "not_found", "No such run or paper")
    drawer = paper_drawer(db, run, paper)
    if drawer is None:
        raise ApiError(404, "not_found", "This paper is not part of the run")
    return drawer


@router.get("/{run_id}/calls/{call_key}", response_model=CallOut)
def get_call(
    run_id: uuid.UUID, call_key: str, user=Depends(require_role("member")), db=Depends(get_db), settings=Depends(get_settings),
):
    run = db.get(Run, run_id)
    if run is None:
        raise ApiError(404, "not_found", "No such run")
    if not HEX64.match(call_key):
        raise ApiError(422, "invalid_call_key", "call key must be 64 lowercase hex characters")
    try:
        folder = safe_folder(run.folder or "", [settings.runs_dir, settings.evals_dir])
        return read_call(folder, call_key)
    except CallStoreError as exc:
        if "not found" in str(exc):
            raise ApiError(404, "call_not_found", "No such call in this run's audit trail") from None
        raise ApiError(409, "no_audit_trail", "This run's audit trail is not available") from None
```

(`from ...callstore import HEX64` as well.)

- [ ] **Step 6: Run**

Run: `pytest tests/test_web_drawer.py -v`
Expected: 6 passed

- [ ] **Step 7: Commit**

```bash
ruff format src tests && ruff check . && pytest -q && git add -A
git commit -m "Add the paper drawer and confined raw-call endpoint" -m "Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---
### Task 12: Security guards, headers and secrets

**Files:**
- Modify: `src/research_agent/web/api/app.py`
- Test: `tests/test_web_guards.py`

- [ ] **Step 1: Write the failing tests**

`tests/test_web_guards.py`:

```python
import logging

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from research_agent.web.api.app import API_PREFIX, create_app
from research_agent.web.api.deps import get_db

PUBLIC = {("POST", f"{API_PREFIX}/auth/login")}
ROLES = ["viewer", "member", "admin"]
RANK = {"viewer": 0, "member": 1, "admin": 2}


def guards(dependant):
    found = []
    for dep in dependant.dependencies:
        if getattr(dep.call, "role", None):
            found.append(dep.call.role)
        found += guards(dep)
    return found


def test_every_route_declares_a_role_or_is_explicitly_public(app):
    unguarded = set()
    for route in app.routes:
        if isinstance(route, APIRoute):
            for method in route.methods:
                if not guards(route.dependant):
                    unguarded.add((method, route.path))
    assert unguarded == PUBLIC, f"routes without a role guard: {unguarded - PUBLIC}"


def matrix(imported, paper_id):
    run, eval_run = imported["research"], imported["eval"]
    return [
        ("GET", "/auth/me", "viewer"),
        ("GET", "/users", "admin"),
        ("GET", "/fields", "viewer"),
        ("GET", "/runs", "viewer"),
        ("GET", f"/runs/{run}", "viewer"),
        ("GET", f"/runs/{eval_run}/papers", "viewer"),
        ("GET", f"/runs/{eval_run}/papers/{paper_id}", "viewer"),
        ("GET", f"/runs/{eval_run}/calls/{'0' * 64}", "member"),
        ("GET", "/stages", "viewer"),
        ("GET", "/evals", "viewer"),
        ("POST", "/users", "admin"),
    ]


@pytest.mark.parametrize("role", ROLES)
def test_role_matrix(app, users, imported, db, role):
    from sqlalchemy import select

    from research_agent.web.db.models import Paper

    paper_id = db.scalar(select(Paper.id).where(Paper.source_id == "MED:1"))
    signed = TestClient(app)
    login = signed.post("/api/v1/auth/login", json={"email": f"{role}@example.org", "password": "correct horse battery"})
    csrf = {"X-CSRF-Token": login.json()["csrf_token"]}
    anonymous = TestClient(app)
    for method, path, minimum in matrix(imported, paper_id):
        url = f"{API_PREFIX}{path}"
        kwargs = {"json": {}} if method == "POST" else {}
        assert anonymous.request(method, url, **kwargs).status_code == 401, (method, path)
        allowed = RANK[role] >= RANK[minimum]
        status = signed.request(method, url, headers=csrf, **kwargs).status_code
        if allowed:
            assert status not in (401, 403), (role, method, path, status)
        else:
            assert status == 403, (role, method, path, status)
        if allowed and method == "POST":
            assert signed.request(method, url, **kwargs).status_code == 403, "state change without CSRF must fail"


def test_security_headers_are_on_every_response(client, sign_in):
    for response in (client.get("/api/v1/auth/me"), client.get("/api/v1/nope")):
        assert response.headers["x-content-type-options"] == "nosniff"
        assert response.headers["cache-control"] == "no-store"
        assert "frame-ancestors 'none'" in response.headers["content-security-policy"]
        assert response.headers["referrer-policy"] == "no-referrer"


def test_secrets_never_appear_in_responses_logs_or_error_bodies(settings, db, users, imported, monkeypatch, caplog):
    sentinel = "sk-ant-SENTINEL-1234567890abcdef"
    monkeypatch.setenv("ANTHROPIC_API_KEY", sentinel)
    monkeypatch.setenv("TYPESAFE_API_KEY", sentinel)
    application = create_app(settings, session_factory=lambda: db)
    application.dependency_overrides[get_db] = lambda: db

    @application.get("/api/v1/boom")
    def boom():
        raise RuntimeError(f"provider said no, key {sentinel}")

    client = TestClient(application, raise_server_exceptions=False)
    login = client.post("/api/v1/auth/login", json={"email": "member@example.org", "password": "correct horse battery"})
    seen = [login.text, str(login.headers)]
    for path in ("/auth/me", "/fields", "/runs", "/stages", "/evals", "/nope"):
        r = client.get(f"/api/v1{path}")
        seen += [r.text, str(r.headers)]
    with caplog.at_level(logging.DEBUG):
        crash = client.get("/api/v1/boom")
    assert crash.status_code == 500 and crash.json()["code"] == "internal_error"
    assert crash.json()["message"] == "Unexpected error" and "provider" not in crash.text
    seen.append(crash.text)
    assert not any(sentinel in text for text in seen)
    # The server log records the failure for operators; the response never carries it.
    assert any("unhandled error" in record.getMessage() for record in caplog.records)
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/test_web_guards.py -v`
Expected: `test_security_headers_are_on_every_response` FAILS (headers missing). The guard and matrix tests should already pass because every router uses `require_role`; if `test_every_route_declares_a_role_or_is_explicitly_public` fails, a router is missing its guard, which is exactly what it exists to catch.

- [ ] **Step 3: Add the security-headers middleware in `api/errors.py`**

Inside `install_error_handlers`, after the request-id middleware, add:

```python
    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Cache-Control"] = "no-store"
        response.headers["Content-Security-Policy"] = "default-src 'none'; frame-ancestors 'none'"
        response.headers["Referrer-Policy"] = "no-referrer"
        return response
```

(These headers are for the JSON API. The single-page app gets its own stricter Content-Security-Policy from the web server in plan 3.)

- [ ] **Step 4: Run**

Run: `pytest tests/test_web_guards.py -v`
Expected: 5 passed (the matrix test is parametrized over 3 roles). If the 500 case leaks the exception text, the generic handler in `errors.py` is not being used: check that `@app.exception_handler(Exception)` is registered.

- [ ] **Step 5: Commit**

```bash
ruff format src tests && ruff check . && pytest -q && git add -A
git commit -m "Add route-guard enumeration, role matrix, security headers and secret-leak tests" -m "Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 13: The `research-web` command line

**Files:**
- Modify: `tests/conftest.py`
- Create: `src/research_agent/web/cli.py`
- Test: `tests/test_web_cli.py`

Commands: `migrate`, `create-admin`, `import` (paths or `--all`), `openapi`, `dev`. `serve` and the worker arrive with plan 2.

- [ ] **Step 1: Add a `fresh_db_url` fixture to `tests/conftest.py`**

The CLI commits, so its tests need a database that is discarded afterwards (the per-test rollback fixture cannot see committed data). Append:

```python
@pytest.fixture
def fresh_db_url(pg_url, pg_engine):
    """A brand-new migrated database on the shared server, dropped after the test."""
    import uuid

    from research_agent.web.db.migrate import upgrade

    name = f"t_{uuid.uuid4().hex[:10]}"
    with pg_engine.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
        connection.execute(sa.text(f'create database "{name}"'))
    url = sa.engine.make_url(pg_url).set(database=name).render_as_string(hide_password=False)
    upgrade(url)
    yield url
    with pg_engine.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
        connection.execute(sa.text(f'drop database "{name}" with (force)'))
```

- [ ] **Step 2: Write the failing tests**

`tests/test_web_cli.py`:

```python
import json

import pytest
import sqlalchemy as sa
from sqlalchemy import func, select

from research_agent.web.cli import detect_kind, find_import_targets, main
from research_agent.web.db.models import Paper, Run, User
from research_agent.web.settings import load_settings
from web_fixtures import make_demo_run, make_eval_run


@pytest.fixture
def cli_settings(fresh_db_url, tmp_path):
    make_demo_run(tmp_path / "runs" / "demo")
    make_eval_run(tmp_path)
    return load_settings(
        {
            "RESEARCH_WEB_DATABASE_URL": fresh_db_url,
            "RESEARCH_RUNS_DIR": str(tmp_path / "runs"),
            "RESEARCH_EVALS_DIR": str(tmp_path / "evals"),
            "RESEARCH_GOLD_DIR": str(tmp_path / "gold"),
        }
    )


def scalar(url, statement):
    engine = sa.create_engine(url)
    try:
        with engine.connect() as connection:
            return connection.scalar(statement)
    finally:
        engine.dispose()


def test_detect_kind_and_targets(cli_settings, tmp_path):
    assert detect_kind(tmp_path / "runs" / "demo") == "research"
    assert detect_kind(tmp_path / "evals" / "toy") == "eval"
    assert detect_kind(tmp_path) is None
    targets = find_import_targets(cli_settings)
    assert [(kind, path.name) for kind, path in targets] == [("research", "demo"), ("eval", "toy")]


def test_import_all_is_idempotent_and_reports_each_run(cli_settings, capsys):
    assert main(["import", "--all"], settings=cli_settings) == 0
    out = capsys.readouterr().out
    assert "created" in out and "demo" in out and "toy" in out
    assert scalar(cli_settings.database_url, select(func.count()).select_from(Run)) == 2
    assert scalar(cli_settings.database_url, select(func.count()).select_from(Paper)) == 6 + 12
    assert main(["import", "--all"], settings=cli_settings) == 0
    assert capsys.readouterr().out.count("unchanged") == 2


def test_import_of_a_bad_folder_fails_and_continues(cli_settings, tmp_path, capsys):
    broken = tmp_path / "runs" / "broken"
    broken.mkdir()
    (broken / "report.json").write_text(json.dumps({"state": {}, "manifest": {}}))
    assert main(["import", "--all"], settings=cli_settings) == 1
    out = capsys.readouterr().out
    assert "FAILED" in out and "broken" in out and "created" in out  # the good runs were still imported


def test_create_admin_reads_the_password_from_the_environment(cli_settings, monkeypatch):
    monkeypatch.setenv("RESEARCH_WEB_ADMIN_PASSWORD", "correct horse battery")
    assert main(["create-admin", "--email", "Root@Example.org", "--name", "Root"], settings=cli_settings) == 0
    assert scalar(cli_settings.database_url, select(User.role).where(User.email == "root@example.org")) == "admin"
    assert main(["create-admin", "--email", "root@example.org", "--name", "Root"], settings=cli_settings) == 1  # exists
    monkeypatch.setenv("RESEARCH_WEB_ADMIN_PASSWORD", "short")
    assert main(["create-admin", "--email", "b@example.org", "--name", "B"], settings=cli_settings) == 1


def test_openapi_dump_lists_the_routes_and_no_secrets(cli_settings, tmp_path):
    out = tmp_path / "openapi.json"
    assert main(["openapi", "-o", str(out)], settings=cli_settings) == 0
    schema = json.loads(out.read_text())
    assert "/api/v1/auth/login" in schema["paths"] and "/api/v1/runs/{run_id}/papers" in schema["paths"]
    assert "PaperRow" in schema["components"]["schemas"] and cli_settings.database_url not in out.read_text()


def test_migrate_is_repeatable(cli_settings):
    assert main(["migrate"], settings=cli_settings) == 0
    assert main(["migrate"], settings=cli_settings) == 0
```

- [ ] **Step 3: Run to verify failure**

Run: `pytest tests/test_web_cli.py -v`
Expected: FAIL, `ModuleNotFoundError: No module named 'research_agent.web.cli'`

- [ ] **Step 4: Implement `cli.py`**

```python
"""research-web: migrate, create-admin, import, openapi and a local dev server."""

import argparse
import getpass
import json
import os
import sys
from pathlib import Path

from .api.app import create_app
from .auth import AuthError, create_user
from .db.migrate import upgrade
from .db.session import make_engine, make_session_factory
from .importer.common import ImportFailed
from .importer.evals import import_eval_run
from .importer.research import import_research_run
from .settings import load_settings


def detect_kind(folder):
    folder = Path(folder)
    if (folder / "report.json").is_file():
        return "research"
    if (folder / "manifest.json").is_file() and (folder / "metrics.json").is_file():
        return "eval"
    return None


def find_import_targets(settings):
    targets = []
    for root in (settings.runs_dir, settings.evals_dir):
        if root.is_dir():
            for child in sorted(root.iterdir()):
                kind = detect_kind(child) if child.is_dir() else None
                if kind:
                    targets.append((kind, child))
    return targets


def run_imports(settings, targets):
    """Import each folder in its own transaction; a failure is reported and does not stop the others."""
    factory = make_session_factory(make_engine(settings.database_url))
    failures = 0
    for kind, path in targets:
        with factory() as db:
            try:
                if kind == "research":
                    result = import_research_run(db, path)
                else:
                    result = import_eval_run(db, path, gold_dir=settings.gold_dir)
                db.commit()
                print(f"{result.status:9} {kind:8} {path.name}")
                for warning in result.warnings:
                    print(f"          warning: {warning}")
            except ImportFailed as exc:
                db.rollback()
                failures += 1
                print(f"FAILED    {kind:8} {path.name}: {exc}")
    return 1 if failures else 0


def cmd_import(args, settings):
    if args.all:
        targets = find_import_targets(settings)
    else:
        targets = []
        for raw in args.paths:
            kind = detect_kind(raw)
            if kind is None:
                print(f"FAILED    unknown   {raw}: neither a research run (report.json) nor an eval run (manifest.json + metrics.json)")
                return 1
            targets.append((kind, Path(raw).resolve()))
    return run_imports(settings, targets)


def read_password():
    password = os.environ.get("RESEARCH_WEB_ADMIN_PASSWORD")
    if password:
        return password
    first = getpass.getpass("Password: ")
    if first != getpass.getpass("Repeat: "):
        raise AuthError("passwords do not match")
    return first


def ensure_admin(settings, email, name):
    factory = make_session_factory(make_engine(settings.database_url))
    with factory() as db:
        user = create_user(
            db, email=email, name=name, role="admin", password=read_password(),
            min_password_length=settings.min_password_length,
        )
        db.commit()
        return user.email


def cmd_create_admin(args, settings):
    try:
        print(f"created admin {ensure_admin(settings, args.email, args.name)}")
    except AuthError as exc:
        print(f"FAILED: {exc}")
        return 1
    return 0


def cmd_openapi(args, settings):
    Path(args.output).write_text(json.dumps(create_app(settings).openapi(), indent=2))
    print(f"wrote {args.output}")
    return 0


def cmd_migrate(args, settings):
    upgrade(settings.database_url)
    print("database is up to date")
    return 0


def cmd_dev(args, settings):
    """Local development: an embedded PostgreSQL in .web-dev/, migrations, optional import, then the API."""
    import pgserver
    import uvicorn

    data = Path(args.data_dir)
    data.mkdir(parents=True, exist_ok=True)
    server = pgserver.get_server(data, cleanup_mode="stop")
    url = server.get_uri().replace("postgresql://", "postgresql+psycopg://", 1)
    env = dict(os.environ, RESEARCH_WEB_DATABASE_URL=url, RESEARCH_WEB_COOKIE_SECURE="false")
    dev_settings = load_settings(env)
    upgrade(url)
    if args.admin_email:
        try:
            print(f"created admin {ensure_admin(dev_settings, args.admin_email, args.admin_name)}")
        except AuthError as exc:
            print(f"admin not created: {exc}")
    if args.import_all:
        run_imports(dev_settings, find_import_targets(dev_settings))
    print(f"API on http://{args.host}:{args.port}/api/v1 (Ctrl-C to stop; data in {data})")
    uvicorn.run(create_app(dev_settings), host=args.host, port=args.port, log_level="info")
    return 0


def build_parser():
    parser = argparse.ArgumentParser(prog="research-web", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("migrate", help="apply database migrations").set_defaults(func=cmd_migrate)
    p = sub.add_parser("create-admin", help="create an admin (password from RESEARCH_WEB_ADMIN_PASSWORD or a prompt)")
    p.add_argument("--email", required=True)
    p.add_argument("--name", required=True)
    p.set_defaults(func=cmd_create_admin)
    p = sub.add_parser("import", help="import run and eval folders into the database")
    p.add_argument("paths", nargs="*")
    p.add_argument("--all", action="store_true", help="every folder under the runs and evals directories")
    p.set_defaults(func=cmd_import)
    p = sub.add_parser("openapi", help="write the OpenAPI schema (used to generate the frontend types)")
    p.add_argument("-o", "--output", required=True)
    p.set_defaults(func=cmd_openapi)
    p = sub.add_parser("dev", help="local development server with an embedded PostgreSQL")
    p.add_argument("--data-dir", default=".web-dev/pgdata")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8000)
    p.add_argument("--admin-email")
    p.add_argument("--admin-name", default="Admin")
    p.add_argument("--import-all", action="store_true")
    p.set_defaults(func=cmd_dev)
    return parser


def main(argv=None, settings=None):
    args = build_parser().parse_args(argv)
    if args.command == "import" and not args.all and not args.paths:
        print("give one or more folders, or --all")
        return 1
    if settings is None and args.command != "dev":
        settings = load_settings()
    return args.func(args, settings)


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 5: Run**

Run: `pip install -e '.[dev,live,ui,web,web-dev]' -q && pytest tests/test_web_cli.py -v`
Expected: 6 passed. Then `research-web --help` must list `migrate`, `create-admin`, `import`, `openapi`, `dev`.

- [ ] **Step 6: Commit**

```bash
ruff format src tests && ruff check . && pytest -q && git add -A
git commit -m "Add the research-web command line (migrate, create-admin, import, openapi, dev)" -m "Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 14: Verify on the real data, and document

**Files:**
- Create: `docs/web-app.md`
- Modify: `CLAUDE.md`

This task is verification against the user's real runs and evals (`runs/live-01`, `evals/mlffrct-2024`, `evals/aiffr-slr-2023`, `gold/*.json`). They are git-ignored, so it is a manual check, not a test.

- [ ] **Step 1: Start the dev server with the real data**

In one terminal (the password comes from the environment so it never appears on a command line):

```bash
export RESEARCH_WEB_ADMIN_PASSWORD='choose-a-long-passphrase'
research-web dev --import-all --admin-email you@example.org --admin-name "Your Name"
```

Expected output: `created admin you@example.org`, then one line per folder, in this order and with these statuses on a first run: `created research live-01`, `created eval aiffr-slr-2023`, `created eval mlffrct-2024`, then `API on http://127.0.0.1:8000/api/v1`. Warnings are allowed (for example a missing raw call); any `FAILED` line is a bug to investigate.

- [ ] **Step 2: Check the numbers over HTTP**

In a second terminal:

```bash
rm -f .web-dev/jar && curl -s -c .web-dev/jar -X POST http://127.0.0.1:8000/api/v1/auth/login \
  -H 'content-type: application/json' \
  -d "{\"email\":\"you@example.org\",\"password\":\"$RESEARCH_WEB_ADMIN_PASSWORD\"}" | python3 -c "import sys,json; print(json.load(sys.stdin)['user'])"
curl -s -b .web-dev/jar http://127.0.0.1:8000/api/v1/runs | python3 -c "
import sys, json
for r in json.load(sys.stdin): print(r['kind'], r['field_name'][:40], r['paper_count'], r['gold_set_name'])"
```

Expected: three runs. For the eval runs, `GET /api/v1/runs/{id}` must give these counts (they equal the reports the eval CLI printed earlier):

| Run | screened | kept | escalated | in_sr |
|---|---|---|---|---|
| mlffrct-2024 | 151 | 112 | 82 | 16 |
| aiffr-slr-2023 | 141 | 129 | 82 | 19 |
| live-01 (research) | 5 | 5 | 2 | 0 |

(`live-01`: five papers, three decided by Jev and two escalated to the LLM; one of those two is `uncertain`, which counts as kept, so nothing was dropped. Its Papers table has no SR label, so `in_sr` is `null`.)

Then check the System map and one table page:

```bash
curl -s -b .web-dev/jar http://127.0.0.1:8000/api/v1/stages | python3 -c "
import sys, json
for s in json.load(sys.stdin): print(f\"{s['status']:10} {s['title']:18} {s['headline']} {s['caveat'] or ''}\")"
RUN=$(curl -s -b .web-dev/jar http://127.0.0.1:8000/api/v1/runs?kind=eval | python3 -c "import sys,json; print([r['id'] for r in json.load(sys.stdin) if r['gold_set_name']=='mlffrct-2024'][0])")
curl -s -b .web-dev/jar "http://127.0.0.1:8000/api/v1/runs/$RUN/papers?in_sr=true&decision=exclude" | python3 -c "
import sys, json
b = json.load(sys.stdin); print(b['total']); [print(i['paper']['title'][:70], i['screen']['criteria']) for i in b['items']]"
```

Expected: the stages with a measurement are `measured`, Reviewers is `caveat` with "one model family", `Plan`, `Deduplicate` and `Rank` are `unmeasured`. The System map takes each number from the most recently imported eval that has it; `--all` imports alphabetically, so mlffrct-2024 is newest and the headlines read `recall 15/16` (Search and Screen), `kappa 0.9x` (Reviewers; the eval report prints 0.945), `fired 1 of 36` (Adjudicate). The last command must print `1` and the ΔCT-FFR paper (Jev 0.06), the real paper the screen lost.

- [ ] **Step 3: Check the raw call for that paper and the failure paths**

```bash
PAPER=$(curl -s -b .web-dev/jar "http://127.0.0.1:8000/api/v1/runs/$RUN/papers?in_sr=true&decision=exclude" | python3 -c "import sys,json; print(json.load(sys.stdin)['items'][0]['paper']['id'])")
curl -s -b .web-dev/jar "http://127.0.0.1:8000/api/v1/runs/$RUN/papers/$PAPER" | python3 -c "
import sys, json
d = json.load(sys.stdin); print(d['screening']['reason']); print([r['role']+':'+r['verdict'] for r in d['reviews']]); print(d['screening']['call_key'][:12])"
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8000/api/v1/runs      # 401: no cookie
curl -s -o /dev/null -w '%{http_code}\n' -b .web-dev/jar http://127.0.0.1:8000/docs       # 404: docs are off
```

Expected: the reason mentions Jev `topic_match=0.06`; the reviews list is `a:uncertain`, `b:exclude`, `adjudicator:uncertain` (the real reviewer split from the agreement run); the last two commands print `401` and `404`.

- [ ] **Step 4: Stop the server and write `docs/web-app.md`**

Stop it with Ctrl-C (the embedded PostgreSQL stops with it and keeps its data in `.web-dev/`). Then create `docs/web-app.md` with these sections, each a few lines of plain prose plus the exact commands above:

1. **What this is** (one paragraph: the backend of the web app; the frontend and worker come in later plans).
2. **Requirements**: `pip install -e '.[dev,live,ui,web,web-dev]'`; no Docker or system PostgreSQL is needed for development.
3. **Run it locally**: the `research-web dev` command from Step 1, with the environment variable for the admin password.
4. **Commands**: a table of `migrate`, `create-admin`, `import`, `openapi`, `dev` with one line each.
5. **How the numbers get in**: the importers read run and eval folders; re-import is safe; a changed gold set is refused; where the System map's numbers come from and the "most recently imported eval wins per metric" limitation.
6. **Security notes**: no default password; keys never enter the API; docs endpoints are off; roles.
7. **Deployment**: one sentence that Docker Compose files arrive in plan 2 and cannot be run on a machine without Docker.

In `CLAUDE.md`, under "Comenzi", add one line: `research-web dev --import-all --admin-email <email>` (server local, PostgreSQL embedded) and a pointer to `docs/web-app.md`.

- [ ] **Step 5: Final verification and commit**

Run: `ruff check . && pytest -q`
Expected: everything green.

```bash
git add docs/web-app.md CLAUDE.md
git commit -m "Document the web backend and verify it on the real runs and evals" -m "Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

## Self-review against the spec

**Spec coverage (slice 1, backend part)**
- Data model: all 15 tables (`users`, `sessions`, `fields`, `criteria`, `papers`, `runs`, `screenings`, `criterion_scores`, `evidence_claims`, `reviews`, `rankings`, `gold_sets`, `gold_labels`, `eval_reports`, `jobs`) → Task 1. `jobs` exists now so one migration covers the slice; its logic is plan 2.
- API: auth (login/logout/me), users (adds the missing `GET /users`), fields, runs list/detail, paper table, drawer, raw calls, stages, evals → Tasks 3, 4, 9, 10, 11. `POST /runs`, `POST /runs/{id}/resume`, `GET /jobs/{id}`, `POST /imports` are plan 2 by design.
- Error shape and default deny → Tasks 3 and 12 (route-guard enumeration). Idempotency-Key belongs to `POST /runs` (plan 2).
- Sign-in, sessions, CSRF, rate limit, roles, no default password → Tasks 2, 3, 4, 13. Security headers → Task 12. Keys never reach the API → Task 12 sentinel test (and there are no LLM keys anywhere in this plan's code).
- Paper table cell states (null vs missing) and every filter and sort in the spec → Task 10. Drawer and confined raw calls (hex keys, folder confinement) → Tasks 5 and 11.
- Importers: idempotent, one transaction per run, refusal on changed gold, warnings for missing data, eval runs show both `jev_decision` and `llm_decision` with the cascade at default thresholds → Tasks 6 and 7, including the consistency test against `build_report`.
- Stage catalog: status computed, green only with a measurement → Task 8.
- Testing: real PostgreSQL, importer fixtures, consistency test, security tests → Tasks 0, 6, 7, 12.
- **Deliberately not here (plans 2 and 3):** worker, jobs API, Docker Compose, frontend, Playwright, CI.

**Placeholder scan:** none. Task 14 is a manual verification with exact commands and expected values; where a number cannot be known in advance (`live-01`) the step says to read it from `report.md`.

**Consistency:** `ImportResult(run_id, status, warnings)` and `import_research_run` / `import_eval_run` signatures match the contracts section and the CLI; `CallIndex.key/jev_key/empty`, `read_call`, `safe_folder`, `HEX64` are used with the names defined in Task 5; `require_role(...).role` is what the guard test reads; `PaperQuery` field order matches the router call; `merge_metrics/evaluate_stages/load_catalog` match the stages router.

**Known limits, stated up front:** the System map shows each metric from the most recently imported eval that has it; the rate limiter is per API process; `POST /imports` and Docker are plan 2; nothing here can be verified against Docker on this machine.
