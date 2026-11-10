"""Environment-driven settings. No secrets live here except the database URL."""

import math
import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[3]


SECRETS_KEY_ENV = "RESEARCH_SECRETS_KEY"


class SettingsError(ValueError):
    pass


def check_secrets_key(value):
    """A Fernet key (32 url-safe base64 bytes). The message never repeats the value."""
    from cryptography.fernet import Fernet

    try:
        Fernet(value)
    except (ValueError, TypeError):
        raise SettingsError(
            f"{SECRETS_KEY_ENV} is not a valid Fernet key (generate one with "
            "`python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'`)"
        ) from None


@dataclass(frozen=True)
class Settings:
    database_url: str
    runs_dir: Path
    evals_dir: Path
    gold_dir: Path
    stages_path: Path
    uploads_dir: Path = PROJECT / "uploads"  # uploaded PDFs, by sha256; outside any web root
    cache_dir: Path = PROJECT / "cache"  # worker-side call caches that belong to no run (field assist)
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
    job_timeout_seconds: float = 3600.0
    # Fernet key for user_secrets. `research-web serve` and `worker` refuse to start without it; `dev`
    # generates one into .web-dev/. Never logged (repr=False) and never sent to a client.
    secrets_key: str | None = field(default=None, repr=False)
    # Development mode: set only by `research-web dev` (RESEARCH_WEB_DEV_MODE=true). Only then may the
    # worker's own provider keys (.env) stand in for a key the user has not saved.
    dev_mode: bool = False
    signup_max_attempts: int = 5  # sign-ups per IP per window (every attempt counts)
    signup_window_seconds: int = 3600
    login_ip_max_attempts: int = 30  # failed logins per IP (any email) per login window
    # the built frontend (web/dist); when set, `serve` also serves it (the Docker image sets it)
    static_dir: Path | None = None


def _number(env, name, default, cast=int, low=None, high=None, positive=False):
    raw = env.get(name)
    if raw is None or raw == "":
        return default
    try:
        value = cast(raw)
    except ValueError:
        raise SettingsError(f"{name} must be a number, got {raw!r}") from None
    if not math.isfinite(value):
        raise SettingsError(f"{name} must be a finite number, got {raw!r}")
    if positive and value <= 0:
        raise SettingsError(f"{name} must be greater than 0, got {value}")
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
        uploads_dir=folder("RESEARCH_UPLOADS_DIR", "uploads"),
        cache_dir=folder("RESEARCH_CACHE_DIR", "cache"),
        cookie_secure=env.get("RESEARCH_WEB_COOKIE_SECURE", "true").strip().lower() != "false",
        allow_demo=env.get("RESEARCH_WEB_ALLOW_DEMO", "false").strip().lower() == "true",
        max_papers_cap=_number(env, "RESEARCH_WEB_MAX_PAPERS", 12, low=1, high=30),
        max_active_jobs_per_user=_number(env, "RESEARCH_WEB_MAX_ACTIVE_JOBS", 2, low=1, high=20),
        job_stale_seconds=_number(env, "RESEARCH_WEB_JOB_STALE_SECONDS", 120, low=5),
        job_max_attempts=_number(env, "RESEARCH_WEB_JOB_MAX_ATTEMPTS", 3, low=1, high=10),
        worker_poll_seconds=_number(env, "RESEARCH_WEB_WORKER_POLL_SECONDS", 2.0, cast=float, low=0.01),
        progress_poll_seconds=_number(env, "RESEARCH_WEB_PROGRESS_POLL_SECONDS", 2.0, cast=float, low=0.01),
        job_timeout_seconds=_number(
            env, "RESEARCH_WEB_JOB_TIMEOUT_SECONDS", 3600.0, cast=float, positive=True
        ),
        secrets_key=(env.get(SECRETS_KEY_ENV) or "").strip() or None,
        dev_mode=env.get("RESEARCH_WEB_DEV_MODE", "false").strip().lower() == "true",
        signup_max_attempts=_number(env, "RESEARCH_WEB_SIGNUP_MAX_ATTEMPTS", 5, low=1, high=1000),
        session_idle_hours=_number(env, "RESEARCH_WEB_SESSION_IDLE_HOURS", 8, low=1, high=24 * 30),
        session_absolute_days=_number(env, "RESEARCH_WEB_SESSION_DAYS", 7, low=1, high=90),
        login_max_attempts=_number(env, "RESEARCH_WEB_LOGIN_MAX_ATTEMPTS", 5, low=1, high=100),
        login_window_seconds=_number(env, "RESEARCH_WEB_LOGIN_WINDOW_SECONDS", 300, low=10, high=86_400),
        login_ip_max_attempts=_number(env, "RESEARCH_WEB_LOGIN_IP_MAX_ATTEMPTS", 30, low=1, high=10_000),
        static_dir=Path(env["RESEARCH_WEB_STATIC_DIR"]).resolve()
        if env.get("RESEARCH_WEB_STATIC_DIR")
        else None,
    )
    if settings.secrets_key:
        check_secrets_key(settings.secrets_key)
    if settings.progress_poll_seconds * 3 >= settings.job_stale_seconds:
        # a running job heartbeats once per progress poll; it must never look stale between two beats
        raise SettingsError(
            "RESEARCH_WEB_PROGRESS_POLL_SECONDS times 3 must be less than RESEARCH_WEB_JOB_STALE_SECONDS"
        )
    return settings
