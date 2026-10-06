"""progress.json records when each stage started and finished (shown as the run timeline in the web)."""

import json

from research_agent.runner import Progress
from research_agent.web.runner import progress_snapshot


def test_observe_records_start_and_finish(tmp_path):
    progress = Progress(tmp_path)
    progress.write()
    progress.observe("plan", "running")
    data = json.loads((tmp_path / "progress.json").read_text())
    assert data["timings"]["plan"]["started_at"] and "finished_at" not in data["timings"]["plan"]
    progress.observe("plan", "completed")
    progress.observe("search", "running")
    progress.observe("search", "failed")
    data = json.loads((tmp_path / "progress.json").read_text())
    plan, search = data["timings"]["plan"], data["timings"]["search"]
    assert plan["started_at"] <= plan["finished_at"] <= search["started_at"] <= search["finished_at"]
    snapshot = progress_snapshot(tmp_path)
    assert snapshot["timings"] == data["timings"] and snapshot["started_at"] == data["started_at"]


def test_a_resumed_run_keeps_the_timings_of_earlier_stages(tmp_path):
    first = Progress(tmp_path)
    first.observe("plan", "running")
    first.observe("plan", "completed")
    again = Progress(tmp_path)  # a resume starts a new Progress in the same folder
    again.write()
    again.observe("search", "running")
    data = json.loads((tmp_path / "progress.json").read_text())
    assert set(data["timings"]) == {"plan", "search"}
