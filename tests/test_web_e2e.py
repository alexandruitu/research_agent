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

    started = client.post(
        "/api/v1/runs", json={"field_id": field_id, "max_papers": 3, "mode": "demo"}, headers=csrf
    )
    assert started.status_code == 202
    job_id, run_id = started.json()["job"]["id"], started.json()["run_id"]
    assert client.get(f"/api/v1/jobs/{job_id}").json()["status"] == "queued"

    Worker(settings, factory).drain()  # the real child process runs the real (demo) pipeline

    job = client.get(f"/api/v1/jobs/{job_id}").json()
    assert (
        job["status"] == "done" and job["error"] is None and job["progress"]["stages"]["rank"] == "completed"
    )
    run = client.get(f"/api/v1/runs/{run_id}").json()
    assert run["status"] == "done" and run["counts"]["screened"] == 3 and run["paper_count"] == 3
    table = client.get(f"/api/v1/runs/{run_id}/papers").json()
    assert table["total"] == 3 and all(row["screen"]["tier"] == "llm" for row in table["items"])
    assert (
        tmp_path / "runs" / run_id.replace("-", "") / "worker.log"
    ).exists()  # process output stays on disk, not in the DB
