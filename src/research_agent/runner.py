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
from .connectors import AllSourcesFailed, DemoConnector, EuropePMC, SourceUnavailable, domain_connector
from .fulltext import FULLTEXT_VERSION, FullText
from .graph import build_graph
from .jev import DEFAULT_MODEL, JEV_SCREEN_VERSION, JevScreener, JevThresholds
from .report import write_report
from .schemas import Contract
from .scoring import SCORE_VERSION
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


SEARCH_KEYS = ("search_warnings", "sources_used", "sources_skipped")


def search_summary(values):
    """Partial-search record of a field run's discover stage ({} before discover or for legacy runs)."""
    return {k: values[k] for k in SEARCH_KEYS if k in (values or {})}


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


def copy_review(path, contract, review_file, uploads):
    """review.json in the run folder is the exact file the run was started with (or the validated spec)."""
    target = Path(path) / "review.json"
    if review_file is not None:
        shutil.copyfile(review_file, target)
    else:
        target.write_text(json.dumps(contract.review.model_dump(), ensure_ascii=False, indent=2))
    return {
        "file": "review.json",
        "sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
        "panel": [{"key": r.key, "name": r.name, "version": r.version} for r in contract.review.panel],
        "uploads": [str(Path(u)) for u in uploads],
    }


def review_models(review):
    """Per-role models from review.json; they override the env models (live_models)."""
    overrides = {role: model for role, model in review.models.model_dump().items() if model}
    overrides.update({f"review:{r.key}": r.model for r in review.panel if r.model})
    if review.editor.model:
        overrides["editor"] = review.editor.model
    return overrides


def run_models(contract):
    if contract.mode != "live":
        return {}
    if contract.review is None:
        return live_models()
    return live_models(review_models(contract.review), [r.key for r in contract.review.panel])


def completed_stages(values, contract):
    """Stages whose output is in the committed checkpoint (not a previous process's display state)."""
    done = {name: "completed" for name, field in FIELDS.items() if field in values}
    if contract.review is not None:
        for name in ("review_a", "review_b", "adjudicate"):
            done.pop(name, None)  # panel runs write these legacy keys empty; the stages never ran
        if "texts" in values:
            done["fulltext"] = "completed"
        for reviewer in contract.review.panel:
            if reviewer.key in (values.get("panel") or {}):
                done[f"review_{reviewer.key}"] = "completed"
        if "editor_decisions" in values:
            done["editor"] = "completed"
        if "review" in values:
            done["score"] = "completed"
    return done


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


class RunRefused(ValueError):
    """The run cannot start or resume in this folder; the message is safe to show."""


def record_refusal(path, message):
    """Write the refusal to progress.json so the web shows it instead of an older failure."""
    target = Path(path) / "progress.json"
    try:
        data = json.loads(target.read_text()) if target.exists() else {}
    except (OSError, ValueError):
        data = {}
    data.update(
        status="failed",
        stages={"start": "failed"},
        error_type="RunRefused",
        message=message,
        updated_at=datetime.now(UTC).isoformat(),
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(data, indent=2))


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
            # {stage: {started_at, finished_at}}; a resume keeps the times of stages that ran before
            "timings": (read_json(self.path, {}) or {}).get("timings") or {},
        }

    def write(self, **updates):
        with self.lock:
            self.data.update(updates)
            self.data["updated_at"] = datetime.now(UTC).isoformat()
            atomic_json(self.path, self.data)

    def observe(self, name, status):
        with self.lock:
            now = datetime.now(UTC).isoformat()
            self.data["stages"][name] = status
            timing = self.data["timings"].setdefault(name, {})
            if status == "running":
                timing.clear()
                timing["started_at"] = now
            else:
                timing["finished_at"] = now
            self.data["updated_at"] = now
            atomic_json(self.path, self.data)


def run_research(
    path,
    contract=None,
    models=None,
    resume=False,
    stop_after=None,
    on_event=None,
    domain_file=None,
    review_file=None,
    uploads=(),
):
    path = Path(path)
    path.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("LANGGRAPH_STRICT_MSGPACK", "true")
    with run_lock(path):
        manifest_path = path / "manifest.json"
        if resume:
            manifest = read_json(manifest_path)
            if not manifest:
                raise RunRefused("There is no saved research in this folder.")
            if manifest["prompt_version"] != PROMPT_VERSION:
                raise RunRefused("The prompt version changed; start a new research run.")
            saved = Contract.model_validate(manifest["contract"])
            if contract and contract.topic != saved.topic:
                raise RunRefused("The topic cannot be changed when resuming.")
            contract, models = saved, manifest["models"]
            uploads = (manifest.get("review") or {}).get("uploads", [])
        else:
            if manifest_path.exists():
                raise RunRefused("This research already exists; resume it or choose a new folder.")
            contract = Contract.model_validate(contract)
            models = models or run_models(contract)
            manifest = {
                "contract": contract.model_dump(),
                "models": {
                    **(models or {"all": "synthetic-demo-v1"}),
                    **({"jev": DEFAULT_MODEL} if contract.jev else {}),
                },
                "jev_screen_version": JEV_SCREEN_VERSION if contract.jev else None,
                "domain": copy_domain(path, contract, domain_file) if contract.domain else None,
                "review": copy_review(path, contract, review_file, uploads) if contract.review else None,
                "prompt_version": PROMPT_VERSION,
                "score_version": SCORE_VERSION if contract.review else "m1.1",
                **({"fulltext_version": FULLTEXT_VERSION} if contract.review else {}),
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
            fulltext = (
                FullText(
                    store,
                    contract.review.fulltext.model_dump(),
                    mode=contract.mode,
                    uploads=[path / "uploads", *uploads],
                )
                if contract.review
                else None
            )
            panel = contract.review.model_dump()["panel"] if contract.review else None
            config = {"configurable": {"thread_id": "research-v1"}, "max_concurrency": 5}
            with SqliteSaver.from_conn_string(str(path / "checkpoints.sqlite")) as saver:
                graph = build_graph(
                    connector,
                    evaluator,
                    saver,
                    [stop_after] if stop_after else [],
                    progress.observe,
                    jev,
                    fulltext=fulltext,
                    panel=panel,
                )
                snapshot = graph.get_state(config)
                # Reconstruct committed progress rather than trusting a previous process's display state.
                progress.write(
                    stages=completed_stages(snapshot.values, contract), **search_summary(snapshot.values)
                )
                if resume and snapshot.values and not snapshot.next:
                    result = snapshot.values
                else:
                    initial = None if resume and snapshot.values else {"contract": contract.model_dump()}
                    for event in graph.stream(initial, config, stream_mode="updates"):
                        if search := search_summary((event or {}).get("discover")):
                            progress.write(**search)
                        if on_event:
                            on_event(event)
                    snapshot = graph.get_state(config)
                    if snapshot.next:
                        progress.write(status="paused", next=list(snapshot.next))
                        return None
                    result = snapshot.values
                if search := search_summary(result):
                    manifest["search"] = search
                    atomic_json(manifest_path, manifest)
                store.save_papers("research-v1", result["papers"])
                write_report(result, path, manifest)
            progress.write(status="completed", count=len(result["ranking"]))
            return result
        except Exception as exc:
            # No raw provider exception: it can contain credentials or request bodies. A source failure
            # names only the source.
            progress.write(
                **({"search_warnings": exc.warnings} if isinstance(exc, AllSourcesFailed) else {}),
                status="failed",
                error_type=type(exc).__name__,
                message=exc.message if isinstance(exc, SourceUnavailable) else FAILED,
            )
            raise
