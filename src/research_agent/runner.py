"""Shared CLI/UI execution with checkpoint persistence and atomic progress snapshots."""

import fcntl
import hashlib
import json
import os
import shutil
import threading
from contextlib import contextmanager
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path

from langgraph.checkpoint.sqlite import SqliteSaver

from .agents import PROMPT_VERSION, Evaluator, live_models
from .connectors import DemoConnector, EuropePMC, SourceUnavailable, domain_connector
from .graph import build_graph
from .jev import DEFAULT_MODEL, JEV_SCREEN_VERSION, JevScreener, JevThresholds
from .report import write_report
from .schemas import Contract
from .storage import Store

STAGES = {
    "plan": "Planificare căutare",
    "discover": "Căutare în surse",
    "normalize": "Deduplicare",
    "screen": "Screening",
    "extract": "Extragere dovezi",
    "review_a": "Evaluator A",
    "review_b": "Evaluator B · critic",
    "adjudicate": "Adjudecare",
    "rank": "Clasament",
}
FIELDS = dict(
    zip(
        STAGES,
        [
            "plan",
            "discovered",
            "papers",
            "screens",
            "evidence",
            "reviews_a",
            "reviews_b",
            "decisions",
            "ranking",
        ],
    )
)


FAILED = (
    "The stage did not finish. Check source access, the key and the configured model, then resume the run. "
    "The checkpoint is kept."
)


def make_connector(contract, store):
    if contract.domain is not None:
        return domain_connector(contract.domain, store, contract.mode)
    return DemoConnector(store) if contract.mode == "demo" else EuropePMC(store)


def copy_domain(path, contract, domain_file):
    """domain.json in the run folder is the exact file the run was started with (or the validated spec)."""
    target = Path(path) / "domain.json"
    if domain_file is not None:
        shutil.copyfile(domain_file, target)
    else:
        target.write_text(json.dumps(contract.domain.model_dump(), ensure_ascii=False, indent=2))
    field = contract.domain.field
    return {
        "file": "domain.json",
        "sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
        "field": field.model_dump() if field else None,
    }


def read_json(path, default=None):
    try:
        return json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return default


def atomic_json(path, data):
    path = Path(path)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2))
    temporary.replace(path)


class RunLocked(ValueError):
    """Another process holds the run folder's lock."""


@contextmanager
def run_lock(path):
    with (Path(path) / ".run.lock").open("a") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RunLocked("This research is already running.") from None
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def is_running(path):
    lock = Path(path) / ".run.lock"
    if not lock.exists():
        return False
    with lock.open("a") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return True
        fcntl.flock(handle, fcntl.LOCK_UN)
    return False


class Progress:
    def __init__(self, path):
        self.path = Path(path) / "progress.json"
        self.lock = threading.Lock()
        self.data = {
            "status": "running",
            "stages": {},
            "started_at": datetime.now(UTC).isoformat(),
            "pid": os.getpid(),
        }

    def write(self, **updates):
        with self.lock:
            self.data.update(updates)
            self.data["updated_at"] = datetime.now(UTC).isoformat()
            atomic_json(self.path, self.data)

    def observe(self, name, status):
        with self.lock:
            self.data["stages"][name] = status
            self.data["updated_at"] = datetime.now(UTC).isoformat()
            atomic_json(self.path, self.data)


def run_research(
    path, contract=None, models=None, resume=False, stop_after=None, on_event=None, domain_file=None
):
    path = Path(path)
    path.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("LANGGRAPH_STRICT_MSGPACK", "true")
    with run_lock(path):
        manifest_path = path / "manifest.json"
        if resume:
            manifest = read_json(manifest_path)
            if not manifest:
                raise ValueError("There is no saved research in this folder.")
            if manifest["prompt_version"] != PROMPT_VERSION:
                raise ValueError("The prompt version changed; start a new research run.")
            saved = Contract.model_validate(manifest["contract"])
            if contract and contract.topic != saved.topic:
                raise ValueError("The topic cannot be changed when resuming.")
            contract, models = saved, manifest["models"]
        else:
            if manifest_path.exists():
                raise ValueError("This research already exists; resume it or choose a new folder.")
            contract = Contract.model_validate(contract)
            models = models or (live_models() if contract.mode == "live" else {})
            manifest = {
                "contract": contract.model_dump(),
                "models": {
                    **(models or {"all": "synthetic-demo-v1"}),
                    **({"jev": DEFAULT_MODEL} if contract.jev else {}),
                },
                "jev_screen_version": JEV_SCREEN_VERSION if contract.jev else None,
                "domain": copy_domain(path, contract, domain_file) if contract.domain else None,
                "prompt_version": PROMPT_VERSION,
                "score_version": "m1.1",
                "packages": {
                    p: version(p)
                    for p in ["langgraph", "langgraph-checkpoint-sqlite", "pydantic", "langchain"]
                },
            }
            atomic_json(manifest_path, manifest)
        progress = Progress(path)
        progress.write()
        try:
            store = Store(path)
            evaluator = Evaluator(store, contract.mode, models)
            connector = make_connector(contract, store)
            jev = (
                JevScreener.from_env(
                    store, JevThresholds(contract.jev_min_confidence, contract.jev_exclude_min_confidence)
                )
                if contract.jev
                else None
            )
            config = {"configurable": {"thread_id": "research-v1"}, "max_concurrency": 2}
            with SqliteSaver.from_conn_string(str(path / "checkpoints.sqlite")) as saver:
                graph = build_graph(
                    connector, evaluator, saver, [stop_after] if stop_after else [], progress.observe, jev
                )
                snapshot = graph.get_state(config)
                # Reconstruct committed progress rather than trusting a previous process's display state.
                progress.write(
                    stages={name: "completed" for name, field in FIELDS.items() if field in snapshot.values}
                )
                if resume and snapshot.values and not snapshot.next:
                    result = snapshot.values
                else:
                    initial = None if resume and snapshot.values else {"contract": contract.model_dump()}
                    for event in graph.stream(initial, config, stream_mode="updates"):
                        if on_event:
                            on_event(event)
                    snapshot = graph.get_state(config)
                    if snapshot.next:
                        progress.write(status="paused", next=list(snapshot.next))
                        return None
                    result = snapshot.values
                store.save_papers("research-v1", result["papers"])
                write_report(result, path, manifest)
            progress.write(status="completed", count=len(result["ranking"]))
            return result
        except Exception as exc:
            # No raw provider exception: it can contain credentials or request bodies. A source failure
            # names only the source.
            progress.write(
                status="failed",
                error_type=type(exc).__name__,
                message=exc.source if isinstance(exc, SourceUnavailable) else FAILED,
            )
            raise
