"""Environment-driven settings. No secrets live here except the database URL."""

import math
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
    allow_demo: bool = False
    max_papers_cap: int = 12
    max_active_jobs_per_user: int = 2
    job_stale_seconds: int = 120
    job_max_attempts: int = 3
    worker_poll_seconds: float = 2.0
    progress_poll_seconds: float = 2.0


def _number(env, name, default, cast=int, low=None, high=None):
    raw = env.get(name)
    if raw is None or raw == "":
        return default
    try:
        value = cast(raw)
    except ValueError:
        raise SettingsError(f"{name} must be a number, got {raw!r}") from None
    if not math.isfinite(value):
        raise SettingsError(f"{name} must be a finite number, got {raw!r}")
    if (low is not None and value < low) or (high is not None and value > high):
        raise SettingsError(f"{name} must be between {low} and {high}, got {value}")
    return value


def load_settings(env: Mapping[str, str] | None = None) -> Settings:
    env = os.environ if env is None else env
    url = env.get("RESEARCH_WEB_DATABASE_URL", "")
    if not url:
        raise SettingsError("Set RESEARCH_WEB_DATABASE_URL")
    folder = lambda name, default: Path(env.get(name) or PROJECT / default).resolve()
    settings = Settings(
        database_url=url,
        runs_dir=folder("RESEARCH_RUNS_DIR", "runs"),
        evals_dir=folder("RESEARCH_EVALS_DIR", "evals"),
        gold_dir=folder("RESEARCH_GOLD_DIR", "gold"),
        stages_path=Path(__file__).with_name("stages.yaml"),
        cookie_secure=env.get("RESEARCH_WEB_COOKIE_SECURE", "true").strip().lower() != "false",
        allow_demo=env.get("RESEARCH_WEB_ALLOW_DEMO", "false").strip().lower() == "true",
        max_papers_cap=_number(env, "RESEARCH_WEB_MAX_PAPERS", 12, low=1, high=30),
        max_active_jobs_per_user=_number(env, "RESEARCH_WEB_MAX_ACTIVE_JOBS", 2, low=1, high=20),
        job_stale_seconds=_number(env, "RESEARCH_WEB_JOB_STALE_SECONDS", 120, low=5),
        job_max_attempts=_number(env, "RESEARCH_WEB_JOB_MAX_ATTEMPTS", 3, low=1, high=10),
        worker_poll_seconds=_number(env, "RESEARCH_WEB_WORKER_POLL_SECONDS", 2.0, cast=float, low=0.01),
        progress_poll_seconds=_number(env, "RESEARCH_WEB_PROGRESS_POLL_SECONDS", 2.0, cast=float, low=0.01),
    )
    if settings.progress_poll_seconds * 3 >= settings.job_stale_seconds:
        # a running job heartbeats once per progress poll; it must never look stale between two beats
        raise SettingsError(
            "RESEARCH_WEB_PROGRESS_POLL_SECONDS times 3 must be less than RESEARCH_WEB_JOB_STALE_SECONDS"
        )
    return settings
