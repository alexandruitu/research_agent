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
    folder = lambda name, default: Path(env.get(name) or PROJECT / default).resolve()
    return Settings(
        database_url=url,
        runs_dir=folder("RESEARCH_RUNS_DIR", "runs"),
        evals_dir=folder("RESEARCH_EVALS_DIR", "evals"),
        gold_dir=folder("RESEARCH_GOLD_DIR", "gold"),
        stages_path=Path(__file__).with_name("stages.yaml"),
        cookie_secure=env.get("RESEARCH_WEB_COOKIE_SECURE", "true").strip().lower() != "false",
    )
