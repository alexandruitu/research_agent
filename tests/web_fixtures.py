"""Real (offline) runs for web tests: a demo-mode research run and a toy eval run."""

import json
from pathlib import Path

from eval_helpers import StubEvaluator, jev_client, make_gold

from research_agent.agents import Evaluator
from research_agent.eval.agreement import run_agreement
from research_agent.eval.gold import write_gold
from research_agent.eval.report import build_report, write_report
from research_agent.eval.screen import run_screen, write_manifest
from research_agent.jev import JevScreener
from research_agent.runner import run_research
from research_agent.schemas import Contract
from research_agent.storage import Store

JEV_P = {
    1: 0.97,
    2: 0.5,
    3: 0.03,
    4: 0.9,
    5: 0.01,
    6: 0.02,
    7: 0.5,
    8: 0.5,
    9: 0.95,
    10: 0.5,
    11: 0.5,
    12: 0.04,
}
LLM_EXCLUDE = {"MED:7", "MED:8"}


def make_demo_run(directory, topic="retrieval augmented generation", max_papers=6):
    """A real research run in demo mode (synthetic papers, no network)."""
    run_research(directory, contract=Contract(topic=topic, mode="demo", max_papers=max_papers))
    return Path(directory)


def add_jev_block(directory, paper_id, probability=0.93):
    """Rewrite report.json so one paper looks Jev-decided (demo mode never uses Jev)."""
    path = Path(directory) / "report.json"
    data = json.loads(path.read_text())
    data["state"]["screens"][paper_id] = {
        "decision": "include",
        "reason": f"Jev: topic_match p={probability:.2f} (jev-1.13.0)",
        "tier": "jev",
        "jev": {
            "decision": "include",
            "probabilities": {"topic_match": probability},
            "model_version": "jev-1.13.0",
            "min_confidence": 0.6,
            "exclude_min_confidence": 0.9,
            "cached": False,
        },
    }
    path.write_text(json.dumps(data))


def make_eval_run(
    base,
    name="toy",
    positive_ids=(1, 2, 3, 4),
    jev_p=None,
    llm_exclude=None,
    with_agreement=True,
    no_abstract=(),
):
    """A real eval run: toy gold, Jev (mock HTTP) + demo LLM screen on every paper, agreement, report.
    Papers numbered in `no_abstract` have no abstract, so they are never screened (as on real gold sets)."""
    base = Path(base)
    gold_path = base / "gold" / f"{name}.json"
    gold = make_gold(n=12, positive_ids=positive_ids, name=name)
    for candidate in gold.candidates:
        if int(candidate.id.split(":")[1]) in no_abstract:
            candidate.abstract, candidate.flags = "", ["no_abstract"]
    gold = write_gold(gold, gold_path)
    run = base / "evals" / name
    store = Store(run)
    jev = JevScreener(store, "k", client=jev_client(JEV_P if jev_p is None else jev_p))
    excluded = LLM_EXCLUDE if llm_exclude is None else llm_exclude
    result = run_screen(gold, store, StubEvaluator(store, exclude=excluded), jev)
    write_manifest(
        run, gold_path=gold_path, gold=gold, mode="demo", models={}, jev_model="jev-latest", screened=result
    )
    if with_agreement:
        run_agreement(gold, run, Evaluator(store), limit=2)
    report = build_report(run)
    write_report(run, report)
    return run, gold_path, report
