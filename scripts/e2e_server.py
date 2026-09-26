"""Serve the API, a worker and a small synthetic dataset for the browser tests. No network, no API keys.

Run from `web/` by Playwright (`python ../scripts/e2e_server.py`) with the project's virtualenv active.
The passwords below are test values for a throwaway local database under .web-dev/e2e.
"""

import os
import shutil
import sys
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))  # web_fixtures and eval_helpers live with the tests

from research_agent.web.api.app import create_app
from research_agent.web.auth import create_user
from research_agent.web.cli import find_import_targets, run_imports, stop_on_signals
from research_agent.web.db.migrate import upgrade
from research_agent.web.db.session import make_engine, make_session_factory
from research_agent.web.settings import load_settings
from research_agent.web.worker import Worker

BASE = ROOT / ".web-dev" / "e2e"
PASSWORD = "e2e-test-password-1"  # keep in step with web/e2e/users.ts
USERS = {
    "viewer@example.org": ("Vera Viewer", "viewer"),
    "member@example.org": ("Mia Member", "member"),
    "admin@example.org": ("Ada Admin", "admin"),
}


def environment(database_url, base):
    return {
        "RESEARCH_WEB_DATABASE_URL": database_url,
        "RESEARCH_RUNS_DIR": str(Path(base) / "runs"),
        "RESEARCH_EVALS_DIR": str(Path(base) / "evals"),
        "RESEARCH_GOLD_DIR": str(Path(base) / "gold"),
        "RESEARCH_WEB_COOKIE_SECURE": "false",
        "RESEARCH_WEB_ALLOW_DEMO": "true",
        "RESEARCH_WEB_WORKER_POLL_SECONDS": "0.2",
        # a heartbeat per progress poll; 0.2 s stays far below the default stale limit (120 s)
        "RESEARCH_WEB_PROGRESS_POLL_SECONDS": "0.2",
        "RESEARCH_WEB_JOB_TIMEOUT_SECONDS": "300",
    }


def build_dataset(base):
    """A demo research run and a toy eval set (paper MED:3 is in the SR and dropped by Jev)."""
    from web_fixtures import make_demo_run, make_eval_run

    base = Path(base)
    make_demo_run(base / "runs" / "demo")
    make_eval_run(base)  # writes base/evals/toy and base/gold/toy.json


def seed(settings):
    upgrade(settings.database_url)
    factory = make_session_factory(make_engine(settings.database_url))
    with factory() as db:
        for email, (name, role) in USERS.items():
            create_user(
                db,
                email=email,
                name=name,
                role=role,
                password=PASSWORD,
                min_password_length=settings.min_password_length,
            )
        db.commit()
    if run_imports(settings, find_import_targets(settings)) != 0:
        raise SystemExit("importing the browser test dataset failed")


def main():
    import pgserver
    import uvicorn

    os.environ["PYTHON_DOTENV_DISABLED"] = "1"  # demo runs only: never load the repository .env
    if BASE.exists():
        shutil.rmtree(BASE)
    BASE.mkdir(parents=True)
    build_dataset(BASE)
    server = pgserver.get_server(BASE / "pg", cleanup_mode="stop")
    url = server.get_uri().replace("postgresql://", "postgresql+psycopg://", 1)
    settings = load_settings(environment(url, BASE))
    seed(settings)
    worker = Worker(settings)
    thread = threading.Thread(target=worker.run_forever, name="e2e-worker")
    # uvicorn re-raises the signal it stopped on: without this handler that kills the process before the
    # worker and the database are stopped, leaving a postgres running in .web-dev/e2e
    with stop_on_signals(worker):
        thread.start()
        try:
            uvicorn.run(create_app(settings), host="127.0.0.1", port=8000, log_level="warning")
        finally:
            worker.request_stop()  # a running child is stopped and its job goes back to the queue
            thread.join()
            server.cleanup()


if __name__ == "__main__":
    main()
