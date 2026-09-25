import json

import pytest
from eval_helpers import make_gold

from research_agent.agents import Evaluator
from research_agent.eval.agreement import run_agreement, sample_papers
from research_agent.storage import Store


def test_sample_takes_all_positives_and_a_seeded_number_of_negatives():
    gold = make_gold(n=12, positive_ids=(1, 2, 3))
    a = sample_papers(gold, limit=4, seed=0)
    assert [c.id for c in a] == [c.id for c in sample_papers(gold, limit=4, seed=0)]  # deterministic
    assert {c.id for c in a if c.label == "include"} == {"MED:1", "MED:2", "MED:3"}
    assert sum(c.label == "not_included" for c in a) == 4
    assert len(sample_papers(gold, limit=100, seed=0)) == 12  # limit above the pool takes all


def test_papers_without_abstract_are_never_sampled():
    gold = make_gold(n=4, positive_ids=(1,))
    gold.candidates[0].abstract = ""
    assert "MED:1" not in {c.id for c in sample_papers(gold, limit=10)}


def test_run_agreement_writes_reviews_and_adjudication(tmp_path):
    gold = make_gold(n=6, positive_ids=(1, 2))
    path = run_agreement(gold, tmp_path, Evaluator(Store(tmp_path)), limit=2)
    data = json.loads(path.read_text())
    assert (data["seed"], data["limit"]) == (0, 2)
    assert len(data["papers"]) == 4  # 2 positives + 2 sampled negatives
    entry = data["papers"]["MED:1"]
    assert entry["label"] == "include" and entry["adjudicated"] is True  # demo A/B methods differ by 2
    assert entry["review_a"]["verdict"] == "include" and "relevance" in entry["review_b"]


def _count(store, role):
    with store.connect() as db:
        return db.execute("SELECT count(*) FROM calls WHERE role=?", (role,)).fetchone()[0]


def test_extract_failure_propagates_and_leaves_no_agreement_file(tmp_path):
    gold = make_gold(n=4, positive_ids=(1,))
    gold.candidates[0].abstract = "No sentence break and no final period"  # demo quote is not a substring
    with pytest.raises(ValueError, match="not an exact span"):
        run_agreement(gold, tmp_path, Evaluator(Store(tmp_path)), limit=1)
    assert not (tmp_path / "agreement.json").exists()


def test_failing_role_propagates_and_leaves_no_agreement_file(tmp_path):
    class Broken(Evaluator):
        def _demo(self, role, payload):
            if role == "extract":
                raise RuntimeError("model down")
            return super()._demo(role, payload)

    with pytest.raises(RuntimeError, match="model down"):
        run_agreement(make_gold(n=4, positive_ids=(1,)), tmp_path, Broken(Store(tmp_path)), limit=1)
    assert not (tmp_path / "agreement.json").exists()


def test_disagreement_records_an_adjudicate_call(tmp_path):
    store = Store(tmp_path)
    path = run_agreement(make_gold(n=4, positive_ids=(1,)), tmp_path, Evaluator(store), limit=1)
    assert _count(store, "adjudicate") > 0
    assert all(p["adjudicated"] for p in json.loads(path.read_text())["papers"].values())


def test_agreeing_reviewers_make_no_adjudicate_call(tmp_path):
    class Agree(Evaluator):
        def _demo(self, role, payload):
            return super()._demo("review_a" if role == "review_b" else role, payload)

    store = Store(tmp_path)
    path = run_agreement(make_gold(n=4, positive_ids=(1,)), tmp_path, Agree(store), limit=1)
    assert _count(store, "adjudicate") == 0
    assert not any(p["adjudicated"] for p in json.loads(path.read_text())["papers"].values())


def test_agreement_json_is_written_atomically(tmp_path):
    run_agreement(make_gold(n=4, positive_ids=(1,)), tmp_path, Evaluator(Store(tmp_path)), limit=1)
    assert [p.name for p in tmp_path.glob("agreement.json*")] == ["agreement.json"]
