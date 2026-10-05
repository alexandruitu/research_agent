"""Worker eval jobs in tests: research-eval runs in-process (demo mode, no network, no keys)."""

import json

import langchain.chat_models
import pytest

from research_agent.eval import cli


class Done:
    def __init__(self, code):
        self.returncode = code

    def poll(self):
        return self.returncode

    def terminate(self):  # pragma: no cover - never running
        pass


def in_process(calls=None):
    """A spawn_eval seam: runs `research-eval` argv with eval.cli.main(dotenv=False) synchronously."""

    def spawn(command, env, log_path, cwd=None):
        assert command[1:3] == ["-m", "research_agent.eval.cli"] and "PYTHON_DOTENV_DISABLED" in env
        argv = command[3:]
        if calls is not None:
            calls.append(argv)
        return Done(cli.main(argv, dotenv=False))

    return spawn


def forbid_models(monkeypatch):
    monkeypatch.setattr(
        langchain.chat_models, "init_chat_model", lambda *a, **k: pytest.fail("no model calls")
    )


def review_dict(reviewers=("methodologist", "clinician", "statistician")):
    import tempfile
    from pathlib import Path

    from eval_helpers import small_review

    from research_agent.schemas import read_review

    with tempfile.TemporaryDirectory() as scratch:
        path = small_review(Path(scratch) / "review.json", reviewers)
        return json.loads(json.dumps(read_review(path).model_dump(mode="json", by_alias=True)))
