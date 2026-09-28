"""Characterization test: a legacy (positional topic, no criteria) run keeps today's screening decisions.

The baseline in fixtures/legacy_screens.json was generated from the code before slice 2
(commit 5909658) with `python tests/test_legacy_screens.py --write`.
"""

import json
import sys
from pathlib import Path

import pytest
from eval_helpers import StubEvaluator, europepmc, jev_client, row

from research_agent.agents import Evaluator
from research_agent.connectors import DemoConnector, EuropePMC
from research_agent.graph import build_graph
from research_agent.jev import JevScreener
from research_agent.schemas import Contract
from research_agent.storage import Store

BASELINE = Path(__file__).parent / "fixtures" / "legacy_screens.json"


def summary(result):
    return {
        "screens": {
            pid: {
                "decision": s["decision"],
                "reason": s["reason"],
                "tier": s["tier"],
                "jev": (s.get("jev") or {}).get("decision"),
            }
            for pid, s in sorted(result["screens"].items())
        },
        "ranking": [[r["paper_id"], r["score"]] for r in result["ranking"]],
    }


def demo_run(tmp_path):
    store = Store(tmp_path)
    contract = Contract(topic="retrieval augmented generation").model_dump()
    return build_graph(DemoConnector(store), Evaluator(store)).invoke({"contract": contract})


def jev_run(tmp_path):
    store = Store(tmp_path)
    rows = [row(i) for i in range(1, 9)] + [row(9, abstract="")]
    connector = EuropePMC(store, europepmc({"*": rows}))
    jev = JevScreener(
        store,
        "k",
        client=jev_client({1: 0.99, 2: 0.01, 3: 0.5, 4: 0.9, 5: 0.03}),
        sleep=lambda _s: None,
    )
    evaluator = StubEvaluator(store, exclude={"MED:3"})
    contract = Contract(topic="deep learning CT-FFR", max_papers=12).model_dump()
    return build_graph(connector, evaluator, jev=jev).invoke({"contract": contract})


RUNS = {"demo": demo_run, "jev": jev_run}


@pytest.mark.parametrize("name", sorted(RUNS))
def test_legacy_topic_runs_keep_todays_decisions(tmp_path, name):
    assert summary(RUNS[name](tmp_path)) == json.loads(BASELINE.read_text())[name]


if __name__ == "__main__" and sys.argv[1:] == ["--write"]:
    import tempfile

    with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as b:
        data = {"demo": summary(demo_run(Path(a))), "jev": summary(jev_run(Path(b)))}
    BASELINE.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
