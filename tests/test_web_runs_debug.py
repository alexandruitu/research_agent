"""Debugging a run: the redacted worker.log tail with the failed stage and retry lines; the calls summary."""

import json
import sqlite3
from pathlib import Path

import pytest

from research_agent.web.db.models import Run

SECRET = "sk-ant-api03-THIS-MUST-NEVER-LEAVE-THE-WORKER"


@pytest.fixture
def research(imported, db, users):
    run = db.get(Run, imported["research"])
    run.created_by = users["member"].id
    db.commit()
    return run


def test_log_tail_is_redacted_and_names_the_failure(sign_in, research, db, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", SECRET)
    folder = Path(research.folder)
    lines = [f"line {i}" for i in range(50)]
    lines += [
        "review:methodologist: attempt 1 failed (ValidationError: missing quote); retrying",
        f"calling with key {SECRET}",
        "review:methodologist: attempt 3 failed (ValidationError: missing quote)",
    ]
    (folder / "worker.log").write_text("\n".join(lines) + "\n")
    (folder / "progress.json").write_text(
        json.dumps(
            {
                "status": "failed",
                "stages": {"plan": "completed", "review": "failed"},
                "error_type": "ValidationError",
                "message": "A reviewer answer had no quote.",
            }
        )
    )
    research.status = "failed"
    db.commit()
    member, _ = sign_in("member")
    body = member.get(f"/api/v1/runs/{research.id}/log", params={"lines": 10}).json()
    assert SECRET not in json.dumps(body) and "***" in body["text"]
    assert body["text"].count("\n") <= 10 and body["truncated"] is True
    assert body["failed_stage"] == "review" and "no quote" in body["reason"]
    assert [a for a in body["attempts"] if "attempt 3" in a]
    download = member.get(f"/api/v1/runs/{research.id}/log", params={"download": "true"})
    assert download.status_code == 200 and "attachment" in download.headers["content-disposition"]
    assert SECRET not in download.text and "line 0" in download.text


def test_viewers_cannot_read_logs_or_calls(sign_in, research):
    viewer, _ = sign_in("viewer")
    assert viewer.get(f"/api/v1/runs/{research.id}/log").status_code == 403
    assert viewer.get(f"/api/v1/runs/{research.id}/calls").status_code == 403


def test_a_run_without_a_log_says_so(sign_in, research):
    member, _ = sign_in("member")
    body = member.get(f"/api/v1/runs/{research.id}/log").json()
    assert body["text"] == "" and body["exists"] is False


def test_calls_summary_groups_by_role_and_model_with_an_estimate(sign_in, research):
    with sqlite3.connect(Path(research.folder) / "research.sqlite") as db:
        db.executemany(
            "insert into calls values (?, ?, ?, ?, ?, ?)",
            [
                (f"k{i}", "review:methodologist", "anthropic:claude-sonnet-5", "m1.3", "x" * 4000, "y" * 400)
                for i in range(3)
            ]
            + [("j1", "jev_screen", "jev-latest", "m1.3", "z" * 100, "{}")],
        )
    member, _ = sign_in("member")
    body = member.get(f"/api/v1/runs/{research.id}/calls").json()
    rows = {(r["role"], r["model"]): r for r in body["rows"]}
    review = rows[("review:methodologist", "anthropic:claude-sonnet-5")]
    assert review["calls"] == 3 and review["stage"] == "review" and review["provider"] == "anthropic"
    assert review["input_chars"] == 12000 and review["cost_usd"] > 0
    assert review["cache_hits"] is None and review["seconds"] is None  # not recorded by the call cache
    assert rows[("jev_screen", "jev-latest")]["provider"] == "typesafe"
    assert body["totals"]["calls"] >= 4 and body["totals"]["cost_usd"] >= review["cost_usd"]
    assert body["estimate"] is True
