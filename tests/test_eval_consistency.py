from eval_helpers import StubEvaluator, jev_client, make_gold

from research_agent.agents import Evaluator
from research_agent.eval.gold import gold_paper
from research_agent.eval.metrics import cascade_decision
from research_agent.eval.report import load_records
from research_agent.eval.screen import run_screen
from research_agent.graph import build_graph
from research_agent.jev import JevScreener, JevThresholds
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


def test_offline_replay_equals_the_real_screening_node(tmp_path):
    gold = make_gold(n=12, positive_ids=(1, 2, 3, 4))
    papers = [gold_paper(c, gold) for c in gold.candidates]

    class Fixed:
        def search(self, query, limit):
            return [p.model_copy(deep=True) for p in papers]

    store = Store(tmp_path)
    jev = JevScreener(store, "k", client=jev_client(JEV_P))
    # 1. The real pipeline graph screens the same papers (this fills Jev + escalated-LLM cache entries).
    result = build_graph(Fixed(), StubEvaluator(store, exclude={"MED:7", "MED:8"}), jev=jev).invoke(
        {"contract": Contract(topic=gold.topic, max_papers=12).model_dump()}
    )
    tiers = [s["tier"] for s in result["screens"].values()]
    assert "jev" in tiers and "llm" in tiers  # the fixture exercises both tiers

    # 2. The harness screens the gold set. Pipeline-escalated papers must already be cached: same keys.
    harness = StubEvaluator(store, exclude={"MED:7", "MED:8"})
    run_screen(gold, store, harness, jev)
    assert harness.screen_calls == 12 - tiers.count("llm")

    # 3. Offline replay decides exactly like the pipeline did.
    records, _ = load_records(gold, store, Evaluator(store, offline=True), JevScreener(store, "offline"))
    assert len(records) == 12
    for r in records:
        expected = result["screens"][r["id"]]
        assert cascade_decision(r["probabilities"], r["llm"], JevThresholds()) == (
            expected["decision"],
            expected["tier"],
        )
