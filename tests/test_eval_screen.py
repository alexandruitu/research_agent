from pathlib import Path

import pytest
from eval_helpers import StubEvaluator, jev_client, make_gold

from research_agent.agents import PROMPT_VERSION
from research_agent.eval.gold import write_gold
from research_agent.eval.screen import read_manifest, run_screen, write_manifest
from research_agent.jev import JevScreener
from research_agent.storage import Store


def test_screens_every_candidate_with_abstract_on_both_tiers(tmp_path):
    gold = make_gold(n=5)
    gold.candidates[4].abstract = ""  # no abstract: skipped, as in the pipeline
    store = Store(tmp_path)
    evaluator = StubEvaluator(store)
    jev = JevScreener(store, "k", client=jev_client({}))
    result = run_screen(gold, store, evaluator, jev)
    assert result == {"screened": 4, "jev_model_versions": ["jev-1.13.0"]}
    assert evaluator.screen_calls == 4
    with store.connect() as db:
        assert db.execute("SELECT count(*) FROM calls WHERE role='jev_screen'").fetchone()[0] == 4


def test_second_run_makes_no_new_calls(tmp_path):
    gold = make_gold(n=4)
    store = Store(tmp_path)
    client = jev_client({})
    run_screen(gold, store, StubEvaluator(store), JevScreener(store, "k", client=client))
    assert len(client.calls) == 4
    again = StubEvaluator(store)
    run_screen(gold, store, again, JevScreener(store, "k", client=client))
    assert again.screen_calls == 0 and len(client.calls) == 4


def test_error_midway_keeps_the_cache_usable(tmp_path):
    gold = make_gold(n=5)
    store = Store(tmp_path)

    class Failing(StubEvaluator):
        def _demo(self, role, payload):
            if role == "screen" and payload["paper"]["id"] == "MED:3":
                raise RuntimeError("provider down")
            return super()._demo(role, payload)

    client = jev_client({})
    with pytest.raises(RuntimeError):
        run_screen(gold, store, Failing(store), JevScreener(store, "k", client=client))
    resumed = StubEvaluator(store)
    run_screen(gold, store, resumed, JevScreener(store, "k", client=client))
    assert resumed.screen_calls == 3  # MED:1 and MED:2 were cached; 3..5 run


def test_manifest_roundtrip(tmp_path):
    gold = write_gold(make_gold(), tmp_path / "g.json")
    write_manifest(
        tmp_path / "run",
        gold_path=tmp_path / "g.json",
        gold=gold,
        mode="demo",
        models={"screen": "m-1"},
        jev_model="jev-latest",
        screened={"screened": 3, "jev_model_versions": ["jev-1.13.0"]},
    )
    m = read_manifest(tmp_path / "run")
    assert m["gold_sha256"] == gold.content_sha256 and m["mode"] == "demo"
    assert m["jev_model_versions"] == ["jev-1.13.0"] and m["prompt_version"] == PROMPT_VERSION
    assert Path(m["gold_path"]).is_absolute() and m["gold_path"] == str((tmp_path / "g.json").resolve())
    assert m["models"] == {"screen": "m-1"}
    with pytest.raises(ValueError, match="no eval run"):
        read_manifest(tmp_path / "missing")


def _manifest(run, gold, path):
    return write_manifest(
        run,
        gold_path=path,
        gold=gold,
        mode="demo",
        models={},
        jev_model="jev-latest",
        screened={"screened": 1, "jev_model_versions": []},
    )


def test_run_dir_holding_a_different_gold_set_is_refused(tmp_path):
    first = write_gold(make_gold(name="one"), tmp_path / "one.json")
    second = write_gold(make_gold(name="two"), tmp_path / "two.json")
    run = tmp_path / "run"
    _manifest(run, first, tmp_path / "one.json")
    _manifest(run, first, tmp_path / "one.json")  # same gold: a resume, allowed
    with pytest.raises(ValueError, match="different gold set; use a new --run-dir"):
        _manifest(run, second, tmp_path / "two.json")
    assert read_manifest(run)["gold_sha256"] == first.content_sha256  # the old manifest is untouched
