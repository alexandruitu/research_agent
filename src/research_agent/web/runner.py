"""Running the existing pipeline in a child process, safely."""

import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote, urlsplit

MAX_ERROR = 300
MIN_SECRET = 8  # shorter values are not redacted: replacing them would mangle ordinary text
# The child needs provider keys but nothing of the web app: no database, no admin password, no web settings.
DROPPED_PREFIXES = ("RESEARCH_WEB_",)
DROPPED_FROM_CHILD = ("DATABASE_URL", "PGPASSWORD")
SECRET_SUFFIXES = ("_API_KEY", "_PASSWORD", "_SECRET", "_TOKEN")
SECRET_NAMES = ("PGPASSWORD",)
DATABASE_URLS = ("RESEARCH_WEB_DATABASE_URL", "DATABASE_URL")


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
    args += ["--mode", spec.mode, "--max-papers", str(spec.max_papers)] + (["--jev"] if spec.jev else [])
    return args + ["--", spec.topic]  # after `--` a topic such as "--run-dir=..." can never be read as a flag


def child_environment():
    env = {
        k: v
        for k, v in os.environ.items()
        if k not in DROPPED_FROM_CHILD and not k.startswith(DROPPED_PREFIXES)
    }
    env["PYTHONUNBUFFERED"] = "1"
    return env


def spawn(spec, env, log_path):
    """Start the child. Its output goes to a log file in the run folder, never into the database."""
    Path(spec.run_dir).mkdir(parents=True, exist_ok=True)
    log = open(log_path, "ab")  # noqa: SIM115 -- owned by the child for its lifetime
    try:
        return subprocess.Popen(
            build_command(spec), env=env, stdout=log, stderr=subprocess.STDOUT, start_new_session=True
        )
    finally:
        log.close()  # the child holds its own copy of the descriptor


def read_progress(run_dir):
    try:
        return json.loads((Path(run_dir) / "progress.json").read_text())
    except (OSError, ValueError):
        return {}


def progress_snapshot(run_dir):
    data = read_progress(run_dir)
    return {
        "status": data.get("status"),
        "stages": data.get("stages", {}),
        "updated_at": data.get("updated_at"),
    }


def failure_message(run_dir, exit_code):
    """Built only from the pipeline's own sanitized progress fields; never from process output."""
    data = read_progress(run_dir)
    if data.get("status") == "failed":
        failed = [stage for stage, state in (data.get("stages") or {}).items() if state == "failed"]
        where = f"failed at stage '{failed[0]}': " if failed else "failed: "
        return (where + f"{data.get('error_type', 'Error')}: {data.get('message', 'no details')}")[:MAX_ERROR]
    return f"the run process exited with code {exit_code}"


def _secret_values():
    """Values of key, password, secret and token variables, and the database URLs with their passwords."""
    values = set()
    for name, value in os.environ.items():
        if name.endswith(SECRET_SUFFIXES) or name in SECRET_NAMES:
            values.add(value)
    for name in DATABASE_URLS:
        url = os.environ.get(name, "")
        values.add(url)
        try:
            password = urlsplit(url).password or ""
        except ValueError:
            password = ""
        values.update((password, unquote(password)))
    return sorted((v for v in values if len(v) >= MIN_SECRET), key=len, reverse=True)


def redact(text):
    """`text` with the values of every secret variable (see `_secret_values`) replaced by ***."""
    for value in _secret_values():
        text = text.replace(value, "***")
    return text


def sanitize_error(exc):
    """`Type: message`, redacted (see `redact`), cut to 300."""
    return redact(f"{type(exc).__name__}: {exc}")[:MAX_ERROR]
