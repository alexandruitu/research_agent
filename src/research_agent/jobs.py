"""Launch isolated local workers. Credentials are passed in memory via child environment."""

import os
import subprocess
import sys
import threading
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from .runner import is_running, read_json
from .schemas import Contract

PROJECT = Path(__file__).resolve().parents[2]
MODEL_ENV = {
    "default": "RESEARCH_MODEL",
    "review_a": "RESEARCH_REVIEWER_A_MODEL",
    "review_b": "RESEARCH_REVIEWER_B_MODEL",
    "adjudicate": "RESEARCH_ADJUDICATOR_MODEL",
}
PROCESSES = {}
GUARD = threading.Lock()


def root_directory():
    root = Path(os.getenv("RESEARCH_RUNS_DIR", str(PROJECT / "runs"))).resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


def new_directory(root):
    return Path(root) / (datetime.now(UTC).strftime("%Y%m%d-%H%M%S") + "-" + uuid4().hex[:8])


def launch(path, contract=None, models=None, credentials=None, resume=False, stop_after=None):
    path = Path(path).resolve()
    with GUARD:
        process = PROCESSES.get(str(path))
        if (process and process.poll() is None) or is_running(path):
            raise ValueError("Această cercetare rulează deja.")
        args = [sys.executable, "-m", "research_agent.cli", "--run-dir", str(path)]
        if resume:
            if not (path / "manifest.json").exists():
                raise ValueError("Nu există un checkpoint de reluat.")
            args += ["--resume"]
        else:
            contract = Contract.model_validate(contract)
            args += [contract.topic, "--mode", contract.mode, "--max-papers", str(contract.max_papers)]
        if stop_after:
            args += ["--stop-after", stop_after]
        env = os.environ.copy()
        for key, value in (models or {}).items():
            resolved = value.strip() or (models or {}).get("default", "").strip()
            if resolved:
                env[MODEL_ENV[key]] = resolved
        for key, value in (credentials or {}).items():
            if key in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY") and value:
                env[key] = value
        path.mkdir(parents=True, exist_ok=True)
        # No shell; no API keys in command arguments, files or progress logs.
        process = subprocess.Popen(
            args,
            env=env,
            cwd=PROJECT,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        PROCESSES[str(path)] = process
        return process


def status(path):
    path = Path(path).resolve()
    data = read_json(path / "progress.json", {})
    with GUARD:
        process = PROCESSES.get(str(path))
        exitcode = process.poll() if process else None
        active = process is not None and exitcode is None
    if active or is_running(path):
        return dict(data, status="running")
    if data.get("status") == "running":
        return dict(data, status="interrupted")
    if data:
        return data
    if (path / "report.json").exists():
        return {"status": "completed", "stages": {}}
    if process is not None and exitcode is not None:
        return {
            "status": "failed",
            "message": "Pornirea a eșuat. Verifică modelele și configurația; apoi încearcă din nou.",
        }
    return {"status": "paused"}


def list_runs(root):
    paths = list(Path(root).glob("*/manifest.json"))
    example = PROJECT / "examples/demo/manifest.json"
    if example.exists():
        paths.append(example)
    result = []
    for manifest_path in paths:
        manifest = read_json(manifest_path)
        if manifest:
            result.append((manifest_path.parent, manifest))
    return sorted(result, key=lambda row: row[0].name, reverse=True)
