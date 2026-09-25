# Eval Harness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build `research-eval`, an offline-reproducible harness that measures screening recall (LLM-only, Jev-only, cascade), calibrates the two Jev thresholds, and measures reviewer agreement, against gold sets built from published systematic reviews.

**Architecture:** New package `src/research_agent/eval/` beside the LangGraph pipeline. Pure metric functions (`metrics.py`) are separate from I/O modules (`gold`, `resolve`, `screen`, `agreement`, `report`, `cli`). All model output is cached in the existing `calls` table, so `report` replays the cascade at any threshold pair offline via a cache-only read path (`MissingCall` on a miss). Spec: `docs/superpowers/specs/2026-09-25-eval-harness-design.md`.

**Tech Stack:** Python 3.12, pydantic v2, httpx, PyYAML, pytest (`httpx.MockTransport` for every network call), argparse, ruff (line length 110).

**Conventions used in every task**
- Work in the repo root with the venv active: `cd /Users/alexandruitu/Projects/research_agent && . .venv/bin/activate`.
- Branch: `feat/eval-harness`.
- Commit with the trailer `Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>` (shown as the second `-m` in every commit step).
- After each task: `ruff format src tests && ruff check .` then `pytest -q` must be green before committing.
- Tests never touch the network or need API keys (only the marked live smoke test does, and it skips without a key).

## File structure

| File | Responsibility |
|---|---|
| `src/research_agent/storage.py` (modify) | add `MissingCall` |
| `src/research_agent/agents.py` (modify) | `Evaluator(offline=True)` raises `MissingCall` on cache miss |
| `src/research_agent/jev.py` (modify) | pure `decide_from_probabilities`, `_request`, `cached_probabilities` |
| `src/research_agent/eval/__init__.py` | package marker |
| `src/research_agent/eval/metrics.py` | pure: Wilson, rate, κ, weighted κ, cascade replay, sweep, recommend |
| `src/research_agent/eval/gold.py` | gold schema, SR spec, hash, load/write, `gold_paper` |
| `src/research_agent/eval/resolve.py` | match SR studies to Europe PMC records, `build_gold` |
| `src/research_agent/eval/screen.py` | run Jev + LLM screen over a gold set, run manifest |
| `src/research_agent/eval/agreement.py` | reviewer A/B sample run |
| `src/research_agent/eval/report.py` | offline metrics, markdown/JSON output |
| `src/research_agent/eval/cli.py` | `research-eval` entry point, `errors.log` |
| `tests/eval_helpers.py` | shared fixtures: Europe PMC mock, Jev mock, `make_gold`, `StubEvaluator` |
| `tests/test_eval_*.py` | one file per module, plus consistency and CLI smoke |

---

### Task 0: Setup, dependency, spec amendments

**Files:**
- Modify: `pyproject.toml`, `.gitignore`, `docs/superpowers/specs/2026-09-25-eval-harness-design.md`
- Create: `src/research_agent/eval/__init__.py`, `tests/eval_helpers.py`

- [ ] **Step 1: Declare PyYAML, the script entry and the pytest marker in `pyproject.toml`**

In `dependencies`, append `"pyyaml>=6,<7"` to the list. Under `[project.scripts]` add `research-eval = "research_agent.eval.cli:main"`. Replace the `[tool.pytest.ini_options]` block with:

```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
markers = ["live: needs real API keys; skipped when they are absent"]
```

- [ ] **Step 2: Ignore generated eval artefacts**

Append to `.gitignore`:

```
evals/
gold/
```

(Gold files contain publisher abstracts and are rebuilt from the committed `sr_specs/*.yaml`; run dirs hold sqlite caches.)

- [ ] **Step 3: Create the package and shared test helpers**

`src/research_agent/eval/__init__.py`:

```python
"""Evaluation harness: gold sets, screening recall, threshold calibration, reviewer agreement."""
```

`tests/eval_helpers.py`:

```python
"""Shared fixtures for the eval-harness tests. All network access is mocked."""

import json
import re

import httpx

from research_agent.agents import Evaluator
from research_agent.eval.gold import GoldCandidate, GoldSet
from research_agent.schemas import Screen


def row(i, title=None, doi=None, abstract=None, year="2024"):
    """One Europe PMC result row."""
    return {
        "source": "MED",
        "id": str(i),
        "title": title or f"Paper {i} title",
        "pubYear": year,
        "doi": doi if doi is not None else f"10.1000/p{i}",
        "abstractText": abstract if abstract is not None else f"Abstract {i} on the topic. Second sentence.",
    }


def europepmc(rows_by_query):
    """Mock Europe PMC client. `rows_by_query` is a dict (with optional '*' default) or a callable."""

    def handler(request):
        query = request.url.params["query"]
        if callable(rows_by_query):
            rows = rows_by_query(query)
        else:
            rows = rows_by_query.get(query, rows_by_query.get("*", []))
        return httpx.Response(200, json={"resultList": {"result": rows}})

    return httpx.Client(transport=httpx.MockTransport(handler))


def jev_client(p_by_index):
    """Mock TypeSafe client: probability keyed by the N in the title 'Paper N title' (default 0.5)."""
    calls = []

    def handler(request):
        body = json.loads(request.content)
        index = int(re.search(r"Paper (\d+) title", body["state"]["title"]).group(1))
        calls.append(index)
        p = p_by_index.get(index, 0.5)
        return httpx.Response(
            200, json={"model": "jev-1.13.0", "answers": {"topic_match": {"type": "noul", "noul": p}}}
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    client.calls = calls
    return client


def make_gold(n=12, positive_ids=(1, 2, 3, 4), name="toy"):
    candidates = [
        GoldCandidate(
            id=f"MED:{i}",
            doi=f"10.1000/p{i}",
            title=f"Paper {i} title",
            abstract=f"Abstract {i} on the topic. Second sentence.",
            year="2024",
            label="include" if i in positive_ids else "not_included",
        )
        for i in range(1, n + 1)
    ]
    return GoldSet(
        name=name,
        citation="Test et al. 2026",
        topic="deep learning CT-FFR",
        query="ctffr",
        built_at="2026-09-25T00:00:00+00:00",
        candidates=candidates,
    )


class StubEvaluator(Evaluator):
    """Demo evaluator whose LLM screen excludes chosen ids and counts its screen calls."""

    def __init__(self, store, exclude=(), **kwargs):
        super().__init__(store, **kwargs)
        self.exclude = set(exclude)
        self.screen_calls = 0

    def _demo(self, role, payload):
        if role == "screen":
            self.screen_calls += 1
            if payload["paper"]["id"] in self.exclude:
                return Screen(decision="exclude", reason="off topic")
        return super()._demo(role, payload)
```

(`tests/eval_helpers.py` imports `research_agent.eval.gold`, which does not exist yet; it is first imported in Task 5, so nothing breaks before then.)

- [ ] **Step 4: Amend the spec (five clarifications found while planning)**

In `docs/superpowers/specs/2026-09-25-eval-harness-design.md`:

1. In "Inputs and file formats", after the sentence listing candidate fields, add: `via` (`query` | `lookup`: whether the record came from the topic query or from a direct lookup of an SR-included study). Retrieval recall counts only `via == "query"` positives as found.
2. In the `report` command row and metric 6, replace `--holdout other.json` / "second SR" with: `--holdout evals/other` takes the **run directory** of a second, already-screened SR.
3. In the `agreement` command row, replace "a sample of negatives" with: `--limit N` is the number of negatives sampled (default 40); all positives with an abstract are always included; `agreement` reads mode and models from the run manifest, so it takes no `--mode`.
4. In "Architecture", state that `build_gold` and `GoldBuildError` live in `resolve.py`.
5. Under "Inputs", state that `gold/` and `evals/` are git-ignored and `sr_specs/*.yaml` are committed.

- [ ] **Step 5: Reinstall, confirm the suite is unchanged, commit**

Run: `pip install -e '.[dev,live,ui]' -q && pytest -q`
Expected: `43 passed`

```bash
git add pyproject.toml .gitignore src/research_agent/eval/__init__.py tests/eval_helpers.py docs/superpowers/specs/2026-09-25-eval-harness-design.md
git commit -m "Scaffold eval package; declare PyYAML; amend spec" -m "Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 1: Wilson interval and rate

**Files:**
- Create: `src/research_agent/eval/metrics.py`
- Test: `tests/test_eval_metrics.py`

- [ ] **Step 1: Write the failing tests**

```python
import pytest

from research_agent.eval.metrics import rate, wilson


def test_wilson_known_values():
    low, high = wilson(40, 40)
    assert low == pytest.approx(0.912, abs=2e-3)
    assert high == pytest.approx(1.0, abs=1e-9)
    low, high = wilson(0, 10)
    assert low == pytest.approx(0.0, abs=1e-9)
    assert high == pytest.approx(0.277, abs=2e-3)


def test_wilson_zero_trials_is_none():
    assert wilson(0, 0) is None


def test_rate_carries_interval_and_handles_zero_denominator():
    r = rate(36, 40)
    assert r["value"] == 0.9 and (r["k"], r["n"]) == (36, 40)
    assert r["ci"][0] < 0.9 < r["ci"][1]
    empty = rate(0, 0)
    assert empty["value"] is None and empty["ci"] is None and "zero" in empty["reason"]
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/test_eval_metrics.py -v`
Expected: FAIL, `ModuleNotFoundError: No module named 'research_agent.eval.metrics'`

- [ ] **Step 3: Implement**

`src/research_agent/eval/metrics.py`:

```python
"""Pure evaluation metrics: no I/O, no network, no models."""

import math

Z95 = 1.959964


def wilson(k, n, z=Z95):
    """Wilson score interval for k successes in n trials; None when n == 0."""
    if n == 0:
        return None
    p = k / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (max(0.0, centre - half), min(1.0, centre + half))


def rate(k, n):
    """k of n with a Wilson interval. A zero denominator gives value None plus a reason, never 100%."""
    if n == 0:
        return {"k": k, "n": n, "value": None, "ci": None, "reason": "zero denominator"}
    return {"k": k, "n": n, "value": k / n, "ci": wilson(k, n), "reason": None}
```

- [ ] **Step 4: Run to verify pass**

Run: `pytest tests/test_eval_metrics.py -v`
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
ruff format src tests && ruff check . && git add src/research_agent/eval/metrics.py tests/test_eval_metrics.py
git commit -m "Add Wilson interval and rate metrics" -m "Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 2: Cohen's and weighted kappa

**Files:**
- Modify: `src/research_agent/eval/metrics.py`
- Test: `tests/test_eval_metrics.py`

- [ ] **Step 1: Write the failing tests (append)**

```python
from research_agent.eval.metrics import cohen_kappa, weighted_kappa


def test_cohen_kappa_textbook_example():
    a = ["yes"] * 25 + ["no"] * 25
    # 20 both yes, 5 A-yes/B-no, 10 A-no/B-yes, 15 both no
    b = ["yes"] * 20 + ["no"] * 5 + ["yes"] * 10 + ["no"] * 15
    r = cohen_kappa(a, b)
    assert r["agreement"] == pytest.approx(0.7)
    assert r["kappa"] == pytest.approx(0.4)
    assert r["prevalence"]["yes"] == pytest.approx(0.55)
    assert r["prevalence"]["no"] == pytest.approx(0.45)


def test_cohen_kappa_single_class_is_none_with_reason():
    r = cohen_kappa(["x", "x"], ["x", "x"])
    assert r["kappa"] is None and "single class" in r["reason"]
    assert r["agreement"] == 1.0


def test_cohen_kappa_rejects_bad_input():
    with pytest.raises(ValueError):
        cohen_kappa([], [])
    with pytest.raises(ValueError):
        cohen_kappa(["a"], ["a", "b"])


def test_weighted_kappa():
    assert weighted_kappa([0, 1, 2, 3, 4], [0, 1, 2, 3, 4])["kappa"] == pytest.approx(1.0)
    assert weighted_kappa([0, 4, 0, 4], [4, 0, 4, 0])["kappa"] == pytest.approx(-1.0)
    constant = weighted_kappa([2, 2, 2], [2, 2, 2])
    assert constant["kappa"] is None and "single class" in constant["reason"]
    # An off-by-one costs less than an off-by-three.
    near = weighted_kappa([0, 1, 2, 3, 4, 2], [1, 2, 2, 3, 3, 2])["kappa"]
    far = weighted_kappa([0, 1, 2, 3, 4, 2], [3, 4, 2, 0, 1, 2])["kappa"]
    assert near > far
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/test_eval_metrics.py -v`
Expected: FAIL, `ImportError: cannot import name 'cohen_kappa'`

- [ ] **Step 3: Implement (append to `metrics.py`, and add `from itertools import product` to the imports)**

```python
def _check_pairs(a, b):
    if len(a) != len(b) or not a:
        raise ValueError("kappa needs two equal-length, non-empty label lists")


def cohen_kappa(a, b):
    """Cohen's kappa for two raters. Reports raw agreement and prevalence, because kappa collapses
    when one class dominates. Single-class input gives kappa None plus a reason."""
    _check_pairs(a, b)
    n = len(a)
    labels = sorted(set(a) | set(b), key=str)
    observed = sum(x == y for x, y in zip(a, b, strict=True)) / n
    expected = sum((a.count(label) / n) * (b.count(label) / n) for label in labels)
    result = {
        "n": n,
        "agreement": observed,
        "prevalence": {label: (a.count(label) + b.count(label)) / (2 * n) for label in labels},
    }
    if expected == 1:
        return {**result, "kappa": None, "reason": "single class: kappa undefined"}
    return {**result, "kappa": (observed - expected) / (1 - expected), "reason": None}


def weighted_kappa(a, b, levels=range(5)):
    """Quadratic-weighted kappa for ordinal scores (default 0..4)."""
    _check_pairs(a, b)
    levels = list(levels)
    k = len(levels)
    index = {value: i for i, value in enumerate(levels)}
    n = len(a)
    observed = [[0.0] * k for _ in range(k)]
    for x, y in zip(a, b, strict=True):
        observed[index[x]][index[y]] += 1 / n
    rows = [sum(r) for r in observed]
    cols = [sum(observed[i][j] for i in range(k)) for j in range(k)]
    num = den = 0.0
    for i, j in product(range(k), repeat=2):
        weight = ((i - j) / (k - 1)) ** 2
        num += weight * observed[i][j]
        den += weight * rows[i] * cols[j]
    if den == 0:
        return {"n": n, "kappa": None, "reason": "single class: kappa undefined"}
    return {"n": n, "kappa": 1 - num / den, "reason": None}
```

- [ ] **Step 4: Run to verify pass**

Run: `pytest tests/test_eval_metrics.py -v`
Expected: 7 passed

- [ ] **Step 5: Commit**

```bash
ruff format src tests && ruff check . && git add src/research_agent/eval/metrics.py tests/test_eval_metrics.py
git commit -m "Add Cohen's and quadratic-weighted kappa" -m "Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 3: Offline read paths (Jev, Evaluator) and a pure decision function

**Files:**
- Modify: `src/research_agent/storage.py`, `src/research_agent/agents.py`, `src/research_agent/jev.py`
- Test: `tests/test_jev.py`, `tests/test_pipeline.py` (append)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_jev.py`:

```python
def test_decide_from_probabilities_is_the_screener_rule(tmp_path):
    from research_agent.jev import decide_from_probabilities

    thresholds = JevThresholds()
    s = JevScreener(Store(tmp_path), "k", thresholds=thresholds)
    for p in (0.0, 0.05, 0.06, 0.5, 0.79, 0.8, 1.0):
        assert decide_from_probabilities({"q": p}, thresholds) == s.decide({"q": p})


def test_cached_probabilities_read_without_http(tmp_path):
    from research_agent.storage import MissingCall

    api = Api(0.7)
    screener(tmp_path, api).screen(TOPIC, PAPER)
    offline = JevScreener(Store(tmp_path), "no-key")  # no client: any HTTP attempt would hit the network
    probabilities, version = offline.cached_probabilities(TOPIC, PAPER)
    assert probabilities == {"topic_match": 0.7} and version == "jev-1.13.0"
    with pytest.raises(MissingCall):
        offline.cached_probabilities("another topic", PAPER)
```

Append to `tests/test_pipeline.py`:

```python
def test_offline_evaluator_serves_cache_and_raises_on_miss(tmp_path):
    from research_agent.schemas import Screen
    from research_agent.storage import MissingCall

    store = Store(tmp_path)
    payload = {"topic": "t", "paper": {"id": "x"}}
    Evaluator(store).ask("screen", Screen, payload)  # demo call fills the cache
    offline = Evaluator(store, offline=True)
    assert offline.ask("screen", Screen, payload).decision == "include"
    with pytest.raises(MissingCall):
        offline.ask("screen", Screen, {"topic": "other", "paper": {"id": "x"}})
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/test_jev.py tests/test_pipeline.py -q`
Expected: 3 failures (`ImportError` for `decide_from_probabilities` / `MissingCall`, `TypeError` for `offline`)

- [ ] **Step 3: Implement**

`src/research_agent/storage.py`: add above `class Store`:

```python
class MissingCall(LookupError):
    """A call needed by an offline computation is not in the cache."""
```

`src/research_agent/agents.py`: add `from .storage import MissingCall` to the imports; change the constructor to

```python
    def __init__(self, store, mode="demo", models=None, offline=False):
        self.store = store
        self.mode = mode
        self.models = models or {}
        self.offline = offline
```

and directly after the `if cached is not None: return ...` block in `ask` add:

```python
        if self.offline:
            raise MissingCall(f"{role} call not in cache ({key[:12]})")
```

`src/research_agent/jev.py`: add `from .storage import MissingCall` to the imports. Add this module-level function after `confidence`:

```python
def decide_from_probabilities(probabilities, thresholds):
    """Any confident 'no' excludes; include only when every criterion is confidently 'yes'."""
    if any(p < 0.5 and confidence(p) >= thresholds.exclude_min_confidence for p in probabilities.values()):
        return "exclude"
    if all(p > 0.5 and confidence(p) >= thresholds.min_confidence for p in probabilities.values()):
        return "include"
    return "escalate"
```

In `JevScreener`, replace the body of `decide` with `return decide_from_probabilities(probabilities, self.thresholds)`. Add a `_request` method, and replace the first five lines of `screen` (from the `# Evidence only` comment through the `key = digest(...)` line) with `key, inputs, questions = self._request(topic, paper)`:

```python
    def _request(self, topic, paper):
        # Evidence only: never a prior verdict or conclusion.
        state = {"title": paper["title"], "abstract": paper["abstract"]}
        questions = self.criteria or default_criteria(topic)
        inputs = {"model": self.model, "state": state, "questions": questions}
        key = digest({"role": "jev_screen", "version": JEV_SCREEN_VERSION, "inputs": inputs})
        return key, inputs, questions

    def cached_probabilities(self, topic, paper):
        """Raw probabilities and API model version from the cache only; never calls the API."""
        key, _inputs, questions = self._request(topic, paper)
        raw = self.store.cached(key)
        if raw is None:
            raise MissingCall(f"jev_screen call not in cache ({key[:12]})")
        response = self._parse(raw, questions)
        return {q: response.answers[q].noul for q in questions}, response.model
```

- [ ] **Step 4: Run to verify pass (whole suite, since `screen` was refactored)**

Run: `pytest -q`
Expected: 46 passed

- [ ] **Step 5: Commit**

```bash
ruff format src tests && ruff check . && git add -A
git commit -m "Add cache-only read paths and a pure Jev decision function" -m "Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 4: Cascade replay, sweep and recommendation

**Files:**
- Modify: `src/research_agent/eval/metrics.py`
- Test: `tests/test_eval_metrics.py`

A **record** is a dict with keys `id`, `title`, `label` (`include` | `not_included`), `probabilities` (`{question: p}`), `llm` (`include` | `uncertain` | `exclude`). Only candidates with an abstract become records.

- [ ] **Step 1: Write the failing tests (append)**

```python
from research_agent.eval.metrics import (
    INCLUDE_GRID,
    cascade_decision,
    evaluate,
    recommend,
    sweep,
)
from research_agent.jev import JevThresholds


def rec(i, label, p, llm="include"):
    return {"id": f"MED:{i}", "title": f"Paper {i}", "label": label, "probabilities": {"topic_match": p}, "llm": llm}


RECORDS = [
    rec(1, "include", 0.97),  # jev include
    rec(2, "include", 0.50),  # escalate -> llm include
    rec(3, "include", 0.03),  # jev exclude at default thresholds: the miss
    rec(4, "include", 0.90),
    rec(5, "not_included", 0.01),
    rec(6, "not_included", 0.50, llm="exclude"),
    rec(7, "not_included", 0.95),
    rec(8, "not_included", 0.50, llm="exclude"),
]


def test_cascade_uses_jev_when_confident_else_llm():
    t = JevThresholds()
    assert cascade_decision({"q": 0.97}, "exclude", t) == ("include", "jev")
    assert cascade_decision({"q": 0.5}, "exclude", t) == ("exclude", "llm")


def test_evaluate_cascade_counts_misses_and_workload():
    out = evaluate(RECORDS, "cascade", JevThresholds())
    assert (out["recall"]["k"], out["recall"]["n"]) == (3, 4)
    assert [m["id"] for m in out["missed"]] == ["MED:3"]
    assert out["missed"][0]["tier"] == "jev"
    assert (out["auto_include"], out["auto_exclude"], out["escalated"]) == (3, 2, 3)
    assert out["calls_saved"] == 5


def test_llm_only_and_jev_only_baselines():
    llm = evaluate(RECORDS, "llm_only", JevThresholds())
    assert llm["recall"]["k"] == 4 and llm["calls_saved"] == 0
    jev = evaluate(RECORDS, "jev_only", JevThresholds())
    assert [m["id"] for m in jev["missed"]] == ["MED:3"]  # 'escalate' counts as kept
    assert jev["calls_saved"] == 8
    with pytest.raises(ValueError):
        evaluate(RECORDS, "nonsense", JevThresholds())


def test_sweep_respects_constraint_and_recall_is_monotone_in_exclude_threshold():
    rows = sweep(RECORDS)
    assert all(r["exclude_min_confidence"] >= r["min_confidence"] for r in rows)
    for include in INCLUDE_GRID:
        recalls = [r["recall"]["value"] for r in rows if r["min_confidence"] == include]
        assert recalls == sorted(recalls)  # rows are ordered by ascending exclude threshold


def test_recommend_picks_most_calls_saved_meeting_target():
    rows = sweep(RECORDS)
    best = recommend(rows, target=0.98)
    assert best["recall"]["value"] == 1.0
    assert best["exclude_min_confidence"] >= 0.95  # p=0.03 needs the stricter exclude bar
    assert all(r["calls_saved"] <= best["calls_saved"] for r in rows if r["recall"]["value"] >= 0.98)


def test_recommend_says_none_when_no_pair_meets_target():
    rows = sweep([rec(1, "include", 0.5, llm="exclude")])
    assert recommend(rows, target=0.98) is None
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/test_eval_metrics.py -v`
Expected: FAIL, `ImportError: cannot import name 'INCLUDE_GRID'`

- [ ] **Step 3: Implement (append to `metrics.py`; add `from collections import Counter` is not needed, use the imports below)**

Add to the imports at the top of the file: `from ..jev import JevThresholds, decide_from_probabilities`. Append:

```python
INCLUDE_GRID = [round(i / 10, 1) for i in range(1, 10)]
EXCLUDE_GRID = [0.5, 0.6, 0.7, 0.8, 0.9, 0.95, 0.99]
STRATEGIES = ("llm_only", "jev_only", "cascade")


def cascade_decision(probabilities, llm_decision, thresholds):
    """The shipped cascade: a confident Jev verdict decides, otherwise the LLM screen does."""
    verdict = decide_from_probabilities(probabilities, thresholds)
    return (verdict, "jev") if verdict != "escalate" else (llm_decision, "llm")


def _decide(record, strategy, thresholds):
    if strategy == "llm_only":
        return record["llm"], "llm"
    if strategy == "jev_only":
        return decide_from_probabilities(record["probabilities"], thresholds), "jev"
    if strategy == "cascade":
        return cascade_decision(record["probabilities"], record["llm"], thresholds)
    raise ValueError(f"unknown strategy {strategy!r}")


def evaluate(records, strategy, thresholds):
    """Recall on SR-included papers plus workload. 'Kept' means not excluded, as in the pipeline."""
    decided = [(r, *_decide(r, strategy, thresholds)) for r in records]
    positives = [r for r in records if r["label"] == "include"]
    missed = [
        {"id": r["id"], "title": r["title"], "probabilities": r["probabilities"], "decision": d, "tier": t}
        for r, d, t in decided
        if r["label"] == "include" and d == "exclude"
    ]
    n = len(records)
    if strategy == "llm_only":
        auto_include = auto_exclude = 0
        escalated, calls_saved = n, 0
    else:
        verdicts = [decide_from_probabilities(r["probabilities"], thresholds) for r in records]
        auto_include, auto_exclude = verdicts.count("include"), verdicts.count("exclude")
        escalated = verdicts.count("escalate")
        calls_saved = n if strategy == "jev_only" else n - escalated
    return {
        "recall": rate(len(positives) - len(missed), len(positives)),
        "missed": missed,
        "auto_include": auto_include,
        "auto_exclude": auto_exclude,
        "escalated": escalated,
        "calls_saved": calls_saved,
    }


def sweep(records, includes=INCLUDE_GRID, excludes=EXCLUDE_GRID):
    """Cascade outcome for every allowed threshold pair (exclude must be >= include: recall first)."""
    rows = []
    for include, exclude in product(includes, excludes):
        if exclude < include:
            continue
        out = evaluate(records, "cascade", JevThresholds(include, exclude))
        rows.append(
            {
                "min_confidence": include,
                "exclude_min_confidence": exclude,
                "recall": out["recall"],
                "missed": len(out["missed"]),
                "calls_saved": out["calls_saved"],
                "auto_include": out["auto_include"],
                "auto_exclude": out["auto_exclude"],
                "escalated": out["escalated"],
            }
        )
    return rows


def recommend(rows, target):
    """Most calls saved with point-estimate recall >= target; ties: fewer missed, stricter exclude.
    None when no pair meets the target: never silently pick the 'least bad' pair."""
    ok = [r for r in rows if r["recall"]["value"] is not None and r["recall"]["value"] >= target]
    if not ok:
        return None
    return min(ok, key=lambda r: (-r["calls_saved"], r["missed"], -r["exclude_min_confidence"]))
```

- [ ] **Step 4: Run to verify pass**

Run: `pytest tests/test_eval_metrics.py -v`
Expected: 13 passed

- [ ] **Step 5: Commit**

```bash
ruff format src tests && ruff check . && git add -A
git commit -m "Add cascade replay, threshold sweep and recommended pair" -m "Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 5: Gold schema, SR spec, integrity hash

**Files:**
- Create: `src/research_agent/eval/gold.py`
- Test: `tests/test_eval_gold.py`

- [ ] **Step 1: Write the failing tests**

```python
import json

import pytest

from research_agent.eval.gold import (
    GoldCandidate,
    GoldIntegrityError,
    GoldSet,
    StudyRef,
    gold_paper,
    load_gold,
    load_sr_spec,
    write_gold,
)
from research_agent.schemas import Paper


def gold():
    return GoldSet(
        name="toy",
        citation="Test 2026",
        topic="deep learning CT-FFR",
        query="ctffr",
        built_at="2026-09-25T00:00:00+00:00",
        candidates=[
            GoldCandidate(id="MED:1", doi="10.1/a", title="A", abstract="Abstract A.", year="2024", label="include"),
            GoldCandidate(id="MED:2", title="B", label="not_included", flags=["no_abstract"]),
        ],
    )


def test_roundtrip_and_hash(tmp_path):
    path = tmp_path / "toy.json"
    written = write_gold(gold(), path)
    assert written.content_sha256
    assert load_gold(path) == written


def test_tampered_gold_is_rejected(tmp_path):
    path = tmp_path / "toy.json"
    write_gold(gold(), path)
    data = json.loads(path.read_text())
    data["candidates"][0]["label"] = "not_included"
    path.write_text(json.dumps(data))
    with pytest.raises(GoldIntegrityError):
        load_gold(path)


def test_unknown_field_is_rejected(tmp_path):
    path = tmp_path / "toy.json"
    write_gold(gold(), path)
    data = json.loads(path.read_text())
    data["candidates"][0]["surprise"] = 1
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError):
        load_gold(path)


def test_sr_spec_yaml(tmp_path):
    path = tmp_path / "sr.yaml"
    path.write_text(
        "name: toy-sr\n"
        "citation: Test et al. 2026\n"
        "topic: deep learning CT-FFR\n"
        "query: '\"fractional flow reserve\" AND \"deep learning\"'\n"
        "included:\n"
        "  - doi: 10.1000/ABC\n"
        "  - title: Some study\n"
        "    year: 2021\n"
    )
    spec = load_sr_spec(path)
    assert len(spec.included) == 2
    assert spec.included[1].year == "2021"  # YAML int coerced to str


def test_study_ref_requires_an_identifier():
    with pytest.raises(ValueError):
        StudyRef()


def test_gold_paper_matches_the_pipeline_paper_shape():
    g = gold()
    paper = gold_paper(g.candidates[0], g)
    assert Paper.model_validate(paper.model_dump()) == paper
    assert paper.provenance[0].connector == "gold" and paper.provenance[0].query == "ctffr"
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/test_eval_gold.py -v`
Expected: FAIL, `ModuleNotFoundError: No module named 'research_agent.eval.gold'`

- [ ] **Step 3: Implement `src/research_agent/eval/gold.py`**

```python
"""Gold-set schema. One gold file = one systematic review, frozen with a content hash."""

import json
from pathlib import Path
from typing import Literal

import yaml
from pydantic import Field, field_validator, model_validator

from ..connectors import digest
from ..schemas import Model, Paper, Source

GOLD_VERSION = 1


class GoldIntegrityError(ValueError):
    """The gold file changed after it was frozen, or has an unsupported version."""


class StudyRef(Model):
    """One SR-included study, as listed in sr.yaml."""

    doi: str = ""
    title: str = ""
    year: str = ""

    @field_validator("doi", "title", "year", mode="before")
    @classmethod
    def _text(cls, value):
        return "" if value is None else str(value)

    @model_validator(mode="after")
    def _identifiable(self):
        if not (self.doi or self.title):
            raise ValueError("included study needs a doi or a title")
        return self


class SRSpec(Model):
    name: str = Field(pattern=r"^[A-Za-z0-9._-]+$")
    citation: str
    topic: str = Field(min_length=3)
    query: str = Field(min_length=3)
    included: list[StudyRef] = Field(min_length=1)


def load_sr_spec(path):
    return SRSpec.model_validate(yaml.safe_load(Path(path).read_text()))


class GoldCandidate(Model):
    id: str
    doi: str = ""
    title: str
    abstract: str = ""
    year: str = ""
    label: Literal["include", "not_included"]
    label_source: Literal["sr_included_list", "expert"] = "sr_included_list"
    via: Literal["query", "lookup"] = "query"
    flags: list[str] = Field(default_factory=list)


class UnmatchedStudy(Model):
    """An SR-included study that could not be resolved (matches empty) or was ambiguous."""

    reference: StudyRef
    matches: list[str] = Field(default_factory=list)


class GoldSet(Model):
    version: int = GOLD_VERSION
    name: str
    citation: str
    topic: str
    query: str
    built_at: str
    content_sha256: str = ""
    candidates: list[GoldCandidate]
    unresolved: list[UnmatchedStudy] = Field(default_factory=list)
    ambiguous: list[UnmatchedStudy] = Field(default_factory=list)


def content_hash(gold):
    return digest(gold.model_dump(exclude={"content_sha256"}))


def write_gold(gold, path):
    """Freeze (stamp the content hash) and write. Returns the frozen gold set."""
    gold = gold.model_copy(update={"content_sha256": content_hash(gold)})
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(gold.model_dump(), ensure_ascii=False, indent=2))
    return gold


def load_gold(path):
    gold = GoldSet.model_validate_json(Path(path).read_text())
    if gold.version != GOLD_VERSION:
        raise GoldIntegrityError(f"unsupported gold version {gold.version}")
    if gold.content_sha256 != content_hash(gold):
        raise GoldIntegrityError("gold file changed after it was frozen; rebuild it with build-gold")
    return gold


def gold_paper(candidate, gold):
    """A pipeline-shaped Paper for a candidate, so cache keys match the real screening node."""
    return Paper(
        id=candidate.id,
        title=candidate.title,
        abstract=candidate.abstract,
        year=candidate.year,
        doi=candidate.doi,
        provenance=[
            Source(
                connector="gold",
                record_id=candidate.id,
                url=f"gold:{gold.name}/{candidate.id}",
                query=gold.query,
                retrieved_at=gold.built_at,
                raw_sha256=gold.content_sha256,
            )
        ],
    )
```

- [ ] **Step 4: Run to verify pass**

Run: `pytest tests/test_eval_gold.py -v`
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
ruff format src tests && ruff check . && git add -A
git commit -m "Add gold-set schema, SR spec and integrity hash" -m "Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 6: Resolve SR studies and build the gold set

**Files:**
- Create: `src/research_agent/eval/resolve.py`
- Test: `tests/test_eval_resolve.py`

- [ ] **Step 1: Write the failing tests**

```python
import pytest
from eval_helpers import europepmc, row

from research_agent.connectors import EuropePMC
from research_agent.eval.gold import SRSpec, StudyRef
from research_agent.eval.resolve import GoldBuildError, build_gold
from research_agent.storage import Store


def spec(*included):
    return SRSpec(
        name="toy", citation="T", topic="deep learning CT-FFR", query="ctffr", included=list(included)
    )


def build(tmp_path, rows_by_query, *included):
    connector = EuropePMC(Store(tmp_path), europepmc(rows_by_query))
    return build_gold(spec(*included), connector, max_candidates=50, built_at="2026-09-25T00:00:00+00:00")


def by_id(gold):
    return {c.id: c for c in gold.candidates}


def test_matches_by_doi_and_by_title_year(tmp_path):
    pool = [row(1), row(2, title="Exact Title Here", doi=""), row(3)]
    gold = build(
        tmp_path,
        {"ctffr": pool},
        StudyRef(doi="https://doi.org/10.1000/P1"),
        StudyRef(title="exact title here!", year="2024"),
    )
    c = by_id(gold)
    assert (c["MED:1"].label, c["MED:1"].via) == ("include", "query")
    assert (c["MED:2"].label, c["MED:2"].via) == ("include", "query")
    assert c["MED:3"].label == "not_included"
    assert gold.unresolved == [] and gold.ambiguous == []
    assert [x.id for x in gold.candidates] == ["MED:1", "MED:2", "MED:3"]


def test_lookup_when_study_is_not_in_query_results(tmp_path):
    def rows(query):
        return [row(9)] if query.startswith("DOI:") else [row(1)]

    gold = build(tmp_path, rows, StudyRef(doi="10.1000/p9"))
    c = by_id(gold)
    assert (c["MED:9"].label, c["MED:9"].via) == ("include", "lookup")
    assert c["MED:1"].label == "not_included"


def test_unresolved_is_recorded_not_fatal(tmp_path):
    def rows(query):
        return [] if query.startswith("DOI:") else [row(1)]

    gold = build(tmp_path, rows, StudyRef(doi="10.1000/p1"), StudyRef(doi="10.1000/missing"))
    assert [u.reference.doi for u in gold.unresolved] == ["10.1000/missing"]
    assert by_id(gold)["MED:1"].label == "include"


def test_ambiguous_title_is_recorded_never_guessed(tmp_path):
    pool = [row(1, title="Same Title", doi="10.1000/a"), row(2, title="Same Title", doi="10.1000/b")]
    gold = build(tmp_path, {"ctffr": pool, "*": []}, StudyRef(title="Same Title"), StudyRef(doi="10.1000/a"))
    assert len(gold.ambiguous) == 1 and gold.ambiguous[0].matches == ["MED:1", "MED:2"]
    assert by_id(gold)["MED:2"].label == "not_included"


def test_no_resolved_positive_is_an_error(tmp_path):
    with pytest.raises(GoldBuildError):
        build(tmp_path, {"ctffr": [row(1)], "*": []}, StudyRef(doi="10.1000/nope"))


def test_no_abstract_positive_is_flagged(tmp_path):
    gold = build(tmp_path, {"ctffr": [row(1, abstract=""), row(2)]}, StudyRef(doi="10.1000/p1"))
    assert by_id(gold)["MED:1"].flags == ["no_abstract"]
    assert by_id(gold)["MED:2"].flags == []
```

(Note: in `test_ambiguous_title_is_recorded_never_guessed` the mock returns `{"ctffr": pool, "*": []}`: the `"*"` entry serves the DOI lookup queries, so the second reference resolves from the pool by DOI without a lookup.)

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/test_eval_resolve.py -v`
Expected: FAIL, `ModuleNotFoundError: No module named 'research_agent.eval.resolve'`

- [ ] **Step 3: Implement `src/research_agent/eval/resolve.py`**

```python
"""Match SR-included studies to Europe PMC records and build a frozen gold set."""

import re
from datetime import UTC, datetime

from ..connectors import deduplicate, normalize_doi
from .gold import GoldCandidate, GoldSet, UnmatchedStudy


class GoldBuildError(RuntimeError):
    """Nothing measurable: no included study could be resolved."""


def norm_title(title):
    return re.sub(r"\W+", " ", title.casefold()).strip()


def matches(ref, paper):
    """DOI equality when both sides have a DOI (conflicting DOIs never match); else title (+ year)."""
    if ref.doi and paper.doi:
        return normalize_doi(ref.doi) == normalize_doi(paper.doi)
    if ref.title and norm_title(ref.title) == norm_title(paper.title):
        return not ref.year or ref.year == paper.year
    return False


def lookup_query(ref):
    if ref.doi:
        return f'DOI:"{normalize_doi(ref.doi)}"'
    return f'TITLE:"{ref.title.replace(chr(34), " ")}"'


def resolve_study(ref, pool, connector):
    """Return (paper, via, status, match_ids); status is resolved | not_found | ambiguous."""
    found, via = [p for p in pool if matches(ref, p)], "query"
    if not found:
        via = "lookup"
        found = [p for p in connector.search(lookup_query(ref), 5) if matches(ref, p)]
    unique = deduplicate(found)
    if not unique:
        return None, via, "not_found", []
    if len(unique) > 1:
        return None, via, "ambiguous", [p.id for p in unique]
    return unique[0], via, "resolved", []


def _candidate(paper, label, via):
    return GoldCandidate(
        id=paper.id,
        doi=paper.doi,
        title=paper.title,
        abstract=paper.abstract,
        year=paper.year,
        label=label,
        via=via,
        flags=[] if paper.abstract else ["no_abstract"],
    )


def build_gold(spec, connector, max_candidates=200, built_at=None):
    pool = deduplicate(connector.search(spec.query, max_candidates))
    positives, unresolved, ambiguous = {}, [], []
    for ref in spec.included:
        paper, via, status, ids = resolve_study(ref, pool, connector)
        if status == "resolved":
            positives.setdefault(paper.id, (paper, via))
        elif status == "ambiguous":
            ambiguous.append(UnmatchedStudy(reference=ref, matches=ids))
        else:
            unresolved.append(UnmatchedStudy(reference=ref))
    if not positives:
        raise GoldBuildError("no included study could be resolved; nothing to measure")
    candidates = {p.id: _candidate(p, "include" if p.id in positives else "not_included", "query") for p in pool}
    for paper_id, (paper, via) in positives.items():
        candidates[paper_id] = _candidate(paper, "include", via)
    return GoldSet(
        name=spec.name,
        citation=spec.citation,
        topic=spec.topic,
        query=spec.query,
        built_at=built_at or datetime.now(UTC).isoformat(),
        candidates=[candidates[i] for i in sorted(candidates)],
        unresolved=unresolved,
        ambiguous=ambiguous,
    )
```

- [ ] **Step 4: Run to verify pass**

Run: `pytest tests/test_eval_resolve.py -v`
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
ruff format src tests && ruff check . && git add -A
git commit -m "Add SR study resolution and gold-set builder" -m "Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 7: Screen a gold set and write the run manifest

**Files:**
- Create: `src/research_agent/eval/screen.py`
- Test: `tests/test_eval_screen.py`

- [ ] **Step 1: Write the failing tests**

```python
import pytest
from eval_helpers import StubEvaluator, jev_client, make_gold

from research_agent.eval.gold import write_gold
from research_agent.eval.screen import read_manifest, run_screen, write_manifest
from research_agent.agents import PROMPT_VERSION
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
        models={},
        jev_model="jev-latest",
        screened={"screened": 3, "jev_model_versions": ["jev-1.13.0"]},
    )
    m = read_manifest(tmp_path / "run")
    assert m["gold_sha256"] == gold.content_sha256 and m["mode"] == "demo"
    assert m["jev_model_versions"] == ["jev-1.13.0"] and m["prompt_version"] == PROMPT_VERSION
    with pytest.raises(ValueError, match="no eval run"):
        read_manifest(tmp_path / "missing")
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/test_eval_screen.py -v`
Expected: FAIL, `ModuleNotFoundError: No module named 'research_agent.eval.screen'`

- [ ] **Step 3: Implement `src/research_agent/eval/screen.py`**

```python
"""Run Jev and the LLM screen over every gold candidate. Results live in the calls cache."""

import json
from pathlib import Path

from ..agents import PROMPT_VERSION
from ..jev import JEV_SCREEN_VERSION
from ..schemas import Screen
from .gold import gold_paper

MANIFEST = "manifest.json"


def run_screen(gold, store, evaluator, jev, progress=None):
    """Both tiers on every candidate with an abstract (not only the escalated ones), so `report` can
    replay the cascade at any threshold pair offline. Errors propagate; the cache makes re-runs resume."""
    versions, done = set(), 0
    for candidate in gold.candidates:
        if not candidate.abstract:
            continue
        paper = gold_paper(candidate, gold).model_dump()
        verdict = jev.screen(gold.topic, paper)
        versions.add(verdict["model_version"])
        evaluator.ask("screen", Screen, {"topic": gold.topic, "paper": paper})
        done += 1
        if progress:
            progress(done)
    return {"screened": done, "jev_model_versions": sorted(versions)}


def write_manifest(run_dir, *, gold_path, gold, mode, models, jev_model, screened):
    run_dir = Path(run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    data = {
        "gold_path": str(Path(gold_path).resolve()),
        "gold_sha256": gold.content_sha256,
        "mode": mode,
        "models": models,
        "prompt_version": PROMPT_VERSION,
        "jev_screen_version": JEV_SCREEN_VERSION,
        "jev_model": jev_model,
        **screened,
    }
    temporary = run_dir / (MANIFEST + ".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2))
    temporary.replace(run_dir / MANIFEST)
    return data


def read_manifest(run_dir):
    path = Path(run_dir) / MANIFEST
    if not path.exists():
        raise ValueError(f"no eval run in {run_dir}; run `research-eval screen` first")
    return json.loads(path.read_text())
```

- [ ] **Step 4: Run to verify pass**

Run: `pytest tests/test_eval_screen.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
ruff format src tests && ruff check . && git add -A
git commit -m "Add gold screening run with resumable cache and manifest" -m "Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 8: Reviewer agreement run

**Files:**
- Create: `src/research_agent/eval/agreement.py`
- Test: `tests/test_eval_agreement.py`

- [ ] **Step 1: Write the failing tests**

```python
import json

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
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/test_eval_agreement.py -v`
Expected: FAIL, `ModuleNotFoundError: No module named 'research_agent.eval.agreement'`

- [ ] **Step 3: Implement `src/research_agent/eval/agreement.py`**

```python
"""Run reviewers A and B (and the adjudicator on disagreement) over a gold sample."""

import json
import random
from pathlib import Path

from ..graph import disagreement
from ..schemas import Decision, Evidence, Review
from .gold import gold_paper


def sample_papers(gold, limit, seed=0):
    """All positives with an abstract plus `limit` seeded-random negatives with an abstract."""
    positives = [c for c in gold.candidates if c.label == "include" and c.abstract]
    negatives = sorted((c for c in gold.candidates if c.label != "include" and c.abstract), key=lambda c: c.id)
    picked = random.Random(seed).sample(negatives, min(limit, len(negatives)))
    return positives + sorted(picked, key=lambda c: c.id)


def run_agreement(gold, run_dir, evaluator, limit=40, seed=0):
    """Same payloads as the pipeline graph, so cached calls are shared. Errors propagate (fail closed)."""
    papers = {}
    for candidate in sample_papers(gold, limit, seed):
        paper = gold_paper(candidate, gold).model_dump()
        evidence = evaluator.ask("extract", Evidence, {"paper": paper}).model_dump()
        payload = {"topic": gold.topic, "paper": paper, "evidence": evidence}
        a = evaluator.ask("review_a", Review, payload).model_dump()
        b = evaluator.ask("review_b", Review, payload).model_dump()
        adjudicated = disagreement(a, b)
        if adjudicated:
            evaluator.ask("adjudicate", Decision, {**payload, "reviews": [a, b]})
        papers[candidate.id] = {
            "label": candidate.label,
            "review_a": a,
            "review_b": b,
            "adjudicated": adjudicated,
        }
    path = Path(run_dir) / "agreement.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"seed": seed, "limit": limit, "papers": papers}, ensure_ascii=False, indent=2))
    return path
```

- [ ] **Step 4: Run to verify pass**

Run: `pytest tests/test_eval_agreement.py -v`
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
ruff format src tests && ruff check . && git add -A
git commit -m "Add reviewer agreement run over a seeded gold sample" -m "Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 9: Offline report (metrics, missed positives, sweep, holdout, agreement)

**Files:**
- Create: `src/research_agent/eval/report.py`
- Test: `tests/test_eval_report.py`

- [ ] **Step 1: Write the failing tests**

```python
import json

import pytest
from eval_helpers import StubEvaluator, jev_client, make_gold

from research_agent.eval.agreement import run_agreement
from research_agent.eval.gold import StudyRef, UnmatchedStudy, load_gold, write_gold
from research_agent.eval.report import ReportError, build_report, render_markdown, write_report
from research_agent.eval.screen import run_screen, write_manifest
from research_agent.jev import JevScreener
from research_agent.agents import Evaluator
from research_agent.storage import Store

JEV_P = {1: 0.97, 2: 0.5, 3: 0.03, 4: 0.9, 5: 0.01, 6: 0.02, 7: 0.5, 8: 0.5, 9: 0.95, 10: 0.5, 11: 0.5, 12: 0.04}
LLM_EXCLUDE = {"MED:7", "MED:8"}


def screened_run(base, name="toy", mutate=lambda g: g):
    gold = write_gold(mutate(make_gold(n=12, positive_ids=(1, 2, 3, 4), name=name)), base / "gold.json")
    run = base / "run"
    store = Store(run)
    jev = JevScreener(store, "k", client=jev_client(JEV_P))
    result = run_screen(gold, store, StubEvaluator(store, exclude=LLM_EXCLUDE), jev)
    write_manifest(
        run, gold_path=base / "gold.json", gold=gold, mode="demo", models={}, jev_model="jev-latest", screened=result
    )
    return run


@pytest.fixture
def run_dir(tmp_path):
    return screened_run(tmp_path)


def test_strategies_at_default_thresholds(run_dir):
    report = build_report(run_dir)
    s = report["strategies"]
    assert s["llm_only"]["recall"]["k"] == 4 and s["llm_only"]["calls_saved"] == 0
    assert [m["id"] for m in s["cascade"]["missed"]] == ["MED:3"]  # p=0.03 auto-excluded at exclude>=0.9
    assert [m["id"] for m in s["jev_only"]["missed"]] == ["MED:3"]
    assert report["counts"]["screened"] == 12 and report["jev_model_versions"] == ["jev-1.13.0"]


def test_recommended_pair_needs_the_stricter_exclude_bar(run_dir):
    report = build_report(run_dir, target_recall=0.98)
    best = report["recommended"]
    assert best["recall"]["value"] == 1.0 and best["exclude_min_confidence"] >= 0.95
    assert any("untested on held-out data" in w for w in report["warnings"])


def test_no_recommendation_when_target_unreachable(tmp_path):
    run = screened_run(tmp_path, mutate=lambda g: g)
    # Positives MED:1..4 are all kept by the LLM, so an impossible target (>1) must yield None.
    report = build_report(run, target_recall=1.01)
    assert report["recommended"] is None
    assert any("No threshold pair reaches" in w for w in report["warnings"])


def test_retrieval_recall_counts_lookup_unresolved_and_ambiguous_as_misses(tmp_path):
    def mutate(g):
        g.candidates[3].via = "lookup"
        g.unresolved.append(UnmatchedStudy(reference=StudyRef(doi="10.1/zzz")))
        return g

    report = build_report(screened_run(tmp_path, mutate=mutate))
    r = report["retrieval_recall"]
    assert (r["k"], r["n"]) == (3, 5)


def test_positives_without_abstract_are_reported_separately(tmp_path):
    def mutate(g):
        g.candidates[0].abstract = ""
        g.candidates[0].flags = ["no_abstract"]
        return g

    report = build_report(screened_run(tmp_path, mutate=mutate))
    assert report["counts"]["positives_no_abstract"] == 1 and report["counts"]["positives_screened"] == 3


def test_missing_cached_calls_fail_with_a_count(run_dir):
    with Store(run_dir).connect() as db:
        db.execute("DELETE FROM calls WHERE role='jev_screen'")
    with pytest.raises(ReportError, match=r"12 cached call\(s\) missing"):
        build_report(run_dir)


def test_mixed_jev_versions_are_refused_unless_allowed(run_dir):
    with Store(run_dir).connect() as db:
        db.execute(
            "UPDATE calls SET output = replace(output, 'jev-1.13.0', 'jev-1.14.0') "
            "WHERE rowid = (SELECT min(rowid) FROM calls WHERE role='jev_screen')"
        )
    with pytest.raises(ReportError, match="model versions"):
        build_report(run_dir)
    report = build_report(run_dir, allow_mixed=True)
    assert any("model versions" in w for w in report["warnings"])


def test_edited_gold_file_is_rejected(run_dir, tmp_path):
    path = tmp_path / "gold.json"
    data = json.loads(path.read_text())
    data["candidates"][0]["label"] = "not_included"
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError):
        build_report(run_dir)


def test_holdout_applies_the_recommended_pair_to_a_second_run(tmp_path):
    main = screened_run(tmp_path / "a")
    other = screened_run(tmp_path / "b", name="other")
    report = build_report(main, holdout_dir=other)
    assert report["holdout"]["gold"] == "other" and report["holdout"]["recall"]["n"] == 4
    assert not any("untested on held-out data" in w for w in report["warnings"])


def test_agreement_and_screen_vs_gold_sections(run_dir, tmp_path):
    gold = load_gold(tmp_path / "gold.json")  # the gold file `screened_run` froze
    run_agreement(gold, run_dir, Evaluator(Store(run_dir)), limit=2)
    report = build_report(run_dir)
    ag = report["agreement"]
    assert ag["n"] == 6 and ag["adjudication_rate"]["value"] == 1.0
    assert ag["verdict"]["kappa"] is None  # both demo reviewers say 'include' everywhere: single class
    assert ag["same_family"] is None  # demo manifest has no provider prefixes
    assert report["screen_vs_gold"]["n"] == 12


def test_markdown_and_json_outputs(run_dir):
    report = build_report(run_dir)
    write_report(run_dir, report)
    text = (run_dir / "metrics.md").read_text()
    for needle in ("## Retrieval recall", "## Screening recall", "## Missed positives", "## Threshold sweep", "MED:3"):
        assert needle in text
    assert json.loads((run_dir / "metrics.json").read_text())["gold"]["name"] == "toy"
    assert render_markdown(report) == text
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/test_eval_report.py -v`
Expected: FAIL, `ModuleNotFoundError: No module named 'research_agent.eval.report'`

- [ ] **Step 3: Implement `src/research_agent/eval/report.py`**

```python
"""Offline metrics from cached calls. No network, no API keys, no new model calls."""

import json
from pathlib import Path

from ..agents import Evaluator
from ..jev import JevScreener, JevThresholds
from ..schemas import Screen
from ..storage import MissingCall, Store
from .gold import gold_paper, load_gold
from .metrics import STRATEGIES, cohen_kappa, evaluate, rate, recommend, sweep, weighted_kappa
from .screen import read_manifest


class ReportError(RuntimeError):
    """The report cannot be computed faithfully (missing calls, mixed model versions, stale gold)."""


def load_records(gold, store, evaluator, jev, allow_mixed=False):
    """Cached Jev probabilities + LLM screen decision for every candidate with an abstract."""
    records, versions, missing = [], set(), 0
    for candidate in gold.candidates:
        if not candidate.abstract:
            continue
        paper = gold_paper(candidate, gold).model_dump()
        try:
            probabilities, version = jev.cached_probabilities(gold.topic, paper)
            llm = evaluator.ask("screen", Screen, {"topic": gold.topic, "paper": paper}).decision
        except MissingCall:
            missing += 1
            continue
        versions.add(version)
        records.append(
            {
                "id": candidate.id,
                "title": candidate.title,
                "label": candidate.label,
                "probabilities": probabilities,
                "llm": llm,
            }
        )
    if missing:
        raise ReportError(
            f"{missing} cached call(s) missing; run `research-eval screen` for this gold set first "
            "(a prompt-version change also invalidates the cache)"
        )
    if len(versions) > 1 and not allow_mixed:
        raise ReportError(
            f"Jev model versions differ across cached calls ({sorted(versions)}); "
            "re-screen, or pass --allow-mixed-jev-versions"
        )
    return records, sorted(versions)


def _load_run(run_dir, allow_mixed):
    manifest = read_manifest(run_dir)
    gold = load_gold(manifest["gold_path"])
    if gold.content_sha256 != manifest["gold_sha256"]:
        raise ReportError("gold file changed since this run was screened; re-run `research-eval screen`")
    store = Store(run_dir)
    evaluator = Evaluator(store, manifest["mode"], manifest["models"], offline=True)
    jev = JevScreener(store, "offline", model=manifest["jev_model"])
    records, versions = load_records(gold, store, evaluator, jev, allow_mixed)
    return manifest, gold, records, versions


def _provider(models, role):
    model = models.get(role)
    return model.split(":")[0] if model and ":" in model else None


def _agreement(run_dir, manifest):
    path = Path(run_dir) / "agreement.json"
    if not path.exists():
        return None
    papers = json.loads(path.read_text())["papers"]
    ids = sorted(papers)
    a = [papers[i]["review_a"] for i in ids]
    b = [papers[i]["review_b"] for i in ids]
    provider_a, provider_b = _provider(manifest["models"], "review_a"), _provider(manifest["models"], "review_b")
    return {
        "n": len(ids),
        "verdict": cohen_kappa([r["verdict"] for r in a], [r["verdict"] for r in b]),
        "scores": {
            key: weighted_kappa([r[key] for r in a], [r[key] for r in b])
            for key in ("relevance", "methods", "support")
        },
        "adjudication_rate": rate(sum(papers[i]["adjudicated"] for i in ids), len(ids)),
        "same_family": None if None in (provider_a, provider_b) else provider_a == provider_b,
    }


def build_report(run_dir, target_recall=0.98, holdout_dir=None, allow_mixed=False):
    run_dir = Path(run_dir)
    manifest, gold, records, versions = _load_run(run_dir, allow_mixed)
    default = JevThresholds()
    strategies = {name: evaluate(records, name, default) for name in STRATEGIES}
    rows = sweep(records)
    best = recommend(rows, target_recall)
    positives = [c for c in gold.candidates if c.label == "include"]
    total = len(positives) + len(gold.unresolved) + len(gold.ambiguous)
    warnings = []
    if len(versions) > 1:
        warnings.append(f"Mixed Jev model versions in this run: {versions}.")
    if best is None:
        warnings.append(f"No threshold pair reaches recall >= {target_recall}.")
    holdout = None
    if holdout_dir and best:
        _m, other, other_records, _v = _load_run(holdout_dir, allow_mixed)
        thresholds = JevThresholds(best["min_confidence"], best["exclude_min_confidence"])
        out = evaluate(other_records, "cascade", thresholds)
        holdout = {
            "gold": other.name,
            "n": len(other_records),
            "thresholds": {
                "min_confidence": best["min_confidence"],
                "exclude_min_confidence": best["exclude_min_confidence"],
            },
            "recall": out["recall"],
            "missed": out["missed"],
            "calls_saved": out["calls_saved"],
        }
    else:
        if holdout_dir:
            warnings.append("--holdout ignored: there is no recommended pair to apply.")
        warnings.append("Recommended thresholds are untested on held-out data (no usable --holdout run).")
    return {
        "gold": {"name": gold.name, "citation": gold.citation, "topic": gold.topic, "query": gold.query,
                 "sha256": gold.content_sha256},
        "jev_model_versions": versions,
        "counts": {
            "candidates": len(gold.candidates),
            "screened": len(records),
            "positives_total": total,
            "positives_resolved": len(positives),
            "positives_screened": sum(r["label"] == "include" for r in records),
            "positives_no_abstract": sum(1 for c in positives if not c.abstract),
            "unresolved": len(gold.unresolved),
            "ambiguous": len(gold.ambiguous),
        },
        "retrieval_recall": rate(sum(c.via == "query" for c in positives), total),
        "default_thresholds": {
            "min_confidence": default.min_confidence,
            "exclude_min_confidence": default.exclude_min_confidence,
        },
        "strategies": strategies,
        "sweep": rows,
        "target_recall": target_recall,
        "recommended": best,
        "holdout": holdout,
        "screen_vs_gold": cohen_kappa(
            ["excluded" if r["llm"] == "exclude" else "kept" for r in records],
            ["kept" if r["label"] == "include" else "excluded" for r in records],
        ),
        "agreement": _agreement(run_dir, manifest),
        "warnings": warnings,
    }


def fmt_rate(r):
    if r["value"] is None:
        return f"n/a ({r['reason']})"
    low, high = r["ci"]
    return f"{r['value']:.3f} ({r['k']}/{r['n']}; 95% CI {low:.3f}-{high:.3f})"


def _fmt_kappa(k):
    if k["kappa"] is None:
        return f"n/a ({k['reason']}); agreement {k['agreement']:.2f}" if "agreement" in k else f"n/a ({k['reason']})"
    text = f"{k['kappa']:.3f}"
    return text + (f"; agreement {k['agreement']:.2f}" if "agreement" in k else "")


def render_markdown(report):
    g, c = report["gold"], report["counts"]
    out = [f"# Eval report: {g['name']}", "", f"{g['citation']} · topic: {g['topic']} · gold `{g['sha256'][:12]}`", ""]
    out += [
        "## Retrieval recall",
        "",
        f"{fmt_rate(report['retrieval_recall'])} of SR-included studies were found by the search query "
        f"(unresolved: {c['unresolved']}, ambiguous: {c['ambiguous']} count as misses).",
        "",
        "## Screening recall",
        "",
        f"Kept = not excluded. Denominator: {c['positives_screened']} SR-included papers with an abstract "
        f"({c['positives_no_abstract']} without abstract are not screened). "
        f"Jev thresholds: include >= {report['default_thresholds']['min_confidence']}, "
        f"exclude >= {report['default_thresholds']['exclude_min_confidence']}.",
        "",
        "| strategy | recall | missed | LLM screen calls saved |",
        "|---|---|---|---|",
    ]
    for name, s in report["strategies"].items():
        out.append(f"| {name} | {fmt_rate(s['recall'])} | {len(s['missed'])} | {s['calls_saved']} of {c['screened']} |")
    out += ["", "## Missed positives", ""]
    any_missed = False
    for name, s in report["strategies"].items():
        for m in s["missed"]:
            any_missed = True
            out.append(f"- **{name}**: {m['id']} · {m['title']} · Jev p={m['probabilities']} · decided by {m['tier']}")
    if not any_missed:
        out.append("None at the default thresholds.")
    out += ["", "## Threshold sweep", "", "| include >= | exclude >= | recall | missed | calls saved |", "|---|---|---|---|---|"]
    for r in report["sweep"]:
        out.append(
            f"| {r['min_confidence']} | {r['exclude_min_confidence']} | {fmt_rate(r['recall'])} | "
            f"{r['missed']} | {r['calls_saved']} |"
        )
    best = report["recommended"]
    out += ["", f"**Recommended (recall >= {report['target_recall']}):** "]
    if best:
        out[-1] += (
            f"include >= {best['min_confidence']}, exclude >= {best['exclude_min_confidence']} "
            f"(recall {fmt_rate(best['recall'])}, {best['calls_saved']} calls saved)."
        )
    else:
        out[-1] += "none: no pair reaches the target."
    if report["holdout"]:
        h = report["holdout"]
        out += ["", "## Holdout", "", f"`{h['gold']}` (n={h['n']}): recall {fmt_rate(h['recall'])}, {h['calls_saved']} calls saved."]
    sg = report["screen_vs_gold"]
    out += [
        "",
        "## LLM screen vs SR label",
        "",
        f"Cohen's kappa {_fmt_kappa(sg)} (n={sg['n']}). Caution: SR-not-included papers may be on topic, "
        "so a low kappa is expected; recall is the headline metric.",
    ]
    if report["agreement"]:
        a = report["agreement"]
        out += [
            "",
            "## Reviewer agreement",
            "",
            f"n={a['n']} · same model family: {a['same_family']} · adjudication rate {fmt_rate(a['adjudication_rate'])}",
            f"- verdict kappa: {_fmt_kappa(a['verdict'])}",
        ]
        out += [f"- {key} weighted kappa: {_fmt_kappa(k)}" for key, k in a["scores"].items()]
    if report["warnings"]:
        out += ["", "## Warnings", ""] + [f"- {w}" for w in report["warnings"]]
    return "\n".join(out) + "\n"


def write_report(run_dir, report):
    run_dir = Path(run_dir)
    (run_dir / "metrics.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
    (run_dir / "metrics.md").write_text(render_markdown(report))
```

Two behaviours to keep in mind while running the tests: `ReportError` is raised for missing calls **before** the mixed-version check; `test_missing_cached_calls_fail_with_a_count` deletes every `jev_screen` row, so all 12 candidates are missing.

- [ ] **Step 4: Run to verify pass**

Run: `pytest tests/test_eval_report.py -v`
Expected: 11 passed. If `test_agreement_and_screen_vs_gold_sections` reports a different `n`, the sample is 4 positives + `limit=2` negatives = 6; the assertion already encodes that.

- [ ] **Step 5: Commit**

```bash
ruff format src tests && ruff check . && git add -A
git commit -m "Add offline eval report with sweep, holdout and agreement" -m "Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 10: Consistency test (harness measures the shipped cascade)

**Files:**
- Test: `tests/test_eval_consistency.py`

No production code: this test guards against the harness and the pipeline drifting apart.

- [ ] **Step 1: Write the test**

```python
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

JEV_P = {1: 0.97, 2: 0.5, 3: 0.03, 4: 0.9, 5: 0.01, 6: 0.02, 7: 0.5, 8: 0.5, 9: 0.95, 10: 0.5, 11: 0.5, 12: 0.04}


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
```

- [ ] **Step 2: Run**

Run: `pytest tests/test_eval_consistency.py -v`
Expected: PASS. If it fails on `harness.screen_calls`, the payload or paper shape differs between `run_screen` and the graph's screen node: fix `gold_paper`/`run_screen` (never the test), because that is exactly the drift this test exists to catch.

- [ ] **Step 3: Commit**

```bash
ruff format tests && ruff check . && git add -A
git commit -m "Add consistency test: offline replay equals the real screening node" -m "Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 11: CLI, error log, smoke test, optional live test

**Files:**
- Create: `src/research_agent/eval/cli.py`
- Test: `tests/test_eval_cli.py`, `tests/test_eval_live.py`

- [ ] **Step 1: Write the failing tests**

`tests/test_eval_cli.py`:

```python
import json

from eval_helpers import europepmc, jev_client, row

from research_agent.connectors import EuropePMC
from research_agent.eval import cli
from research_agent.jev import JevScreener

SR = """name: toy
citation: Test et al. 2026
topic: deep learning CT-FFR
query: ctffr
included:
  - doi: 10.1000/p1
  - doi: 10.1000/p2
"""


def test_cli_end_to_end_in_demo_mode(tmp_path, monkeypatch, capsys):
    rows = [row(i) for i in range(1, 9)]
    monkeypatch.setattr(cli, "make_connector", lambda store: EuropePMC(store, europepmc({"*": rows})))
    monkeypatch.setattr(
        cli, "make_jev", lambda store: JevScreener(store, "k", client=jev_client({1: 0.97, 2: 0.9, 3: 0.02}))
    )
    sr, gold, run = tmp_path / "sr.yaml", tmp_path / "gold" / "toy.json", tmp_path / "run"
    sr.write_text(SR)

    assert cli.main(["build-gold", str(sr), "-o", str(gold)], dotenv=False) == 0
    assert cli.main(["screen", str(gold), "--run-dir", str(run), "--mode", "demo"], dotenv=False) == 0
    assert cli.main(["agreement", str(gold), "--run-dir", str(run), "--limit", "2"], dotenv=False) == 0
    assert cli.main(["report", str(run), "--target-recall", "0.9"], dotenv=False) == 0

    report = json.loads((run / "metrics.json").read_text())
    assert report["counts"]["positives_screened"] == 2 and report["agreement"]["n"] == 4
    assert "## Screening recall" in (run / "metrics.md").read_text()
    assert "Gold:" in capsys.readouterr().out


def test_cli_failure_writes_errors_log_and_returns_1(tmp_path, capsys):
    run = tmp_path / "nope"
    assert cli.main(["report", str(run)], dotenv=False) == 1
    log = (run / "errors.log").read_text()
    assert "ValueError" in log and "no eval run" in log
    assert "errors.log" in capsys.readouterr().err
```

`tests/test_eval_live.py`:

```python
import os

import pytest

from research_agent.jev import JevScreener
from research_agent.storage import Store


@pytest.mark.live
@pytest.mark.skipif(not os.getenv("TYPESAFE_API_KEY"), reason="TYPESAFE_API_KEY not set")
def test_live_jev_screen_returns_a_valid_verdict(tmp_path):
    paper = {
        "title": "Deep learning for CT-derived fractional flow reserve",
        "abstract": "We trained a convolutional network on coronary CT angiography to predict invasive FFR.",
    }
    verdict = JevScreener.from_env(Store(tmp_path)).screen("deep learning CT-derived fractional flow reserve", paper)
    assert verdict["decision"] in {"include", "exclude", "escalate"}
    assert all(0 <= p <= 1 for p in verdict["probabilities"].values())
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/test_eval_cli.py -v`
Expected: FAIL, `ImportError: cannot import name 'cli' from 'research_agent.eval'`

- [ ] **Step 3: Implement `src/research_agent/eval/cli.py`**

```python
"""research-eval: build gold sets, screen them, run reviewer agreement, and report offline."""

import argparse
import sys
from pathlib import Path

from dotenv import load_dotenv

from ..agents import Evaluator, live_models
from ..connectors import EuropePMC
from ..jev import JevScreener
from ..storage import Store
from .agreement import run_agreement
from .gold import load_gold, load_sr_spec, write_gold
from .report import build_report, write_report
from .resolve import build_gold
from .screen import read_manifest, run_screen, write_manifest


# Seams for tests: the real network clients are created only here.
def make_connector(store):
    return EuropePMC(store)


def make_jev(store):
    return JevScreener.from_env(store)


def make_evaluator(store, mode):
    return Evaluator(store, "demo") if mode == "demo" else Evaluator(store, "live", live_models())


def cmd_build_gold(args):
    spec, out = load_sr_spec(args.spec), Path(args.out)
    store = Store(out.parent / f".{spec.name}.build")  # raw Europe PMC payloads for provenance
    gold = write_gold(build_gold(spec, make_connector(store), args.max_candidates), out)
    positives = sum(c.label == "include" for c in gold.candidates)
    print(
        f"Gold: {out} · {len(gold.candidates)} candidates, {positives} positives, "
        f"{len(gold.unresolved)} unresolved, {len(gold.ambiguous)} ambiguous"
    )
    return 0


def cmd_screen(args):
    gold = load_gold(args.gold)
    store = Store(args.run_dir)
    evaluator, jev = make_evaluator(store, args.mode), make_jev(store)

    def progress(n):
        if n % 25 == 0:
            print(f"screened {n}", flush=True)

    result = run_screen(gold, store, evaluator, jev, progress)
    write_manifest(
        args.run_dir,
        gold_path=args.gold,
        gold=gold,
        mode=args.mode,
        models=evaluator.models,
        jev_model=jev.model,
        screened=result,
    )
    print(f"Screened {result['screened']} candidates · Jev {result['jev_model_versions']} · run: {args.run_dir}")
    return 0


def cmd_agreement(args):
    manifest = read_manifest(args.run_dir)
    gold = load_gold(args.gold)
    if gold.content_sha256 != manifest["gold_sha256"]:
        raise ValueError("gold file differs from the one this run screened")
    evaluator = make_evaluator(Store(args.run_dir), manifest["mode"])
    print(f"Agreement: {run_agreement(gold, args.run_dir, evaluator, args.limit)}")
    return 0


def cmd_report(args):
    report = build_report(args.run_dir, args.target_recall, args.holdout, args.allow_mixed_jev_versions)
    write_report(args.run_dir, report)
    best = report["recommended"]
    print(
        f"Report: {Path(args.run_dir) / 'metrics.md'} · recommended: "
        + (f"include>={best['min_confidence']} exclude>={best['exclude_min_confidence']}" if best else "none")
    )
    return 0


def build_parser():
    parser = argparse.ArgumentParser(prog="research-eval", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("build-gold", help="resolve an SR's included studies and freeze a gold set")
    p.add_argument("spec")
    p.add_argument("-o", "--out", required=True)
    p.add_argument("--max-candidates", type=int, default=200)
    p.set_defaults(func=cmd_build_gold)

    p = sub.add_parser("screen", help="run Jev and the LLM screen on every candidate")
    p.add_argument("gold")
    p.add_argument("--run-dir", required=True)
    p.add_argument("--mode", choices=["live", "demo"], default="live")
    p.set_defaults(func=cmd_screen)

    p = sub.add_parser("agreement", help="reviewers A/B on all positives plus sampled negatives")
    p.add_argument("gold")
    p.add_argument("--run-dir", required=True)
    p.add_argument("--limit", type=int, default=40, help="number of negatives sampled")
    p.set_defaults(func=cmd_agreement)

    p = sub.add_parser("report", help="offline metrics from cached calls")
    p.add_argument("run_dir")
    p.add_argument("--target-recall", type=float, default=0.98)
    p.add_argument("--holdout", help="run dir of a second, already-screened SR")
    p.add_argument("--allow-mixed-jev-versions", action="store_true")
    p.set_defaults(func=cmd_report)
    return parser


def log_dir(args):
    return Path(args.out).parent if args.command == "build-gold" else Path(args.run_dir)


def main(argv=None, dotenv=True):
    args = build_parser().parse_args(argv)
    if dotenv:  # tests pass dotenv=False so real keys from .env never leak into the test process
        load_dotenv(".env")
    try:
        return args.func(args)
    except Exception as exc:  # noqa: BLE001 -- CLI boundary: log type + message, never keys
        directory = log_dir(args)
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "errors.log").write_text(f"{type(exc).__name__}: {str(exc)[:2000]}\n")
        print(f"research-eval stopped ({type(exc).__name__}); details in {directory / 'errors.log'}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
```

Note: the pipeline's own `research-agent` CLI is unchanged; only the eval CLI writes `errors.log`. Making the main CLI do the same is a separate, optional follow-up.

- [ ] **Step 4: Run to verify pass**

Run: `pip install -e '.[dev,live,ui]' -q && pytest tests/test_eval_cli.py tests/test_eval_live.py -v`
Expected: 2 passed, 1 skipped (the live test, no key exported in the test process). Then `research-eval --help` prints the four subcommands.

- [ ] **Step 5: Commit**

```bash
ruff format src tests && ruff check . && pytest -q && git add -A
git commit -m "Add research-eval CLI with errors.log, smoke test and optional live test" -m "Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 12: Documentation

**Files:**
- Modify: `README.md`, `CLAUDE.md`

- [ ] **Step 1: Add an evaluation section to `README.md` (Romanian, matching the file)**

Append a section `## Evaluare (research-eval)` covering: the four commands with one example each (`research-eval build-gold sr_specs/x.yaml -o gold/x.json`, `screen`, `agreement`, `report`), the `sr.yaml` format (name, citation, topic, query, included with doi/title/year), what is measured (recall cu interval Wilson, lista pozitivelor ratate, sweep de praguri, kappa), and the honest limits: precizia nu e raportată ca metrică principală (SR-included = criterii full-text), pragurile recomandate sunt netestate fără `--holdout`, revieweri din aceeași familie umflă kappa.

- [ ] **Step 2: Update `CLAUDE.md`**

Under "Comenzi" add `research-eval --help` and the four subcommands. In the roadmap, replace item 4 with: `4. Eval harness: implementat (research-eval); urmează un run real pe 1–2 SR-uri open-access și calibrarea pragurilor Jev.` Add under "Principii": `Etapele de măsurare rulează offline din cache (Raw Layer); report nu apelează niciodată API-uri.`

- [ ] **Step 3: Verify and commit**

Run: `ruff check . && pytest -q`
Expected: all green.

```bash
git add README.md CLAUDE.md
git commit -m "Document research-eval" -m "Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 13: First real gold set and run (needs the user's go-ahead: spends API calls)

**Files:**
- Create: `sr_specs/<name>.yaml` (one or two), committed.

This task is not code. It produces the success-criteria evidence from the spec. Do not start it without the user confirming the chosen SRs and the spend (about N Jev calls + N LLM screen calls per SR, N up to `--max-candidates`, plus 2 reviewer calls and one extraction per sampled paper for `agreement`).

- [ ] **Step 1: Find candidate SRs and propose them to the user**

Search Europe PMC / the web for open-access systematic reviews on AI or ML for CT-derived FFR or closely related cardiac-CT AI, each with a public included-studies table listing DOIs or titles. For each candidate, report: citation, licence, number of included studies, whether DOIs are given. Ask the user to pick one or two. A second SR is needed for `--holdout`.

- [ ] **Step 2: Write `sr_specs/<name>.yaml` from the SR's included-studies table**

Use the format from Task 5's `test_sr_spec_yaml`. Copy DOIs or titles exactly as the SR lists them; do not invent or "fix" entries.

- [ ] **Step 3: Build, screen, report**

```bash
research-eval build-gold sr_specs/<name>.yaml -o gold/<name>.json
research-eval screen gold/<name>.json --run-dir evals/<name>
research-eval report evals/<name>
```

Read `evals/<name>/errors.log` if any command exits 1. Check the printed counts: if fewer than about 20 positives resolved, say so, because the recall interval will be wide.

- [ ] **Step 4: Second SR as holdout, then agreement**

```bash
research-eval build-gold sr_specs/<other>.yaml -o gold/<other>.json
research-eval screen gold/<other>.json --run-dir evals/<other>
research-eval report evals/<name> --holdout evals/<other>
research-eval agreement gold/<name>.json --run-dir evals/<name> --limit 40
research-eval report evals/<name> --holdout evals/<other>
```

- [ ] **Step 5: Show the user `evals/<name>/metrics.md`**

Report exactly what it says: recall with interval, every missed positive, the recommended threshold pair (or that none exists), holdout result, and the reviewer-agreement caveat (`same_family: true` while both reviewers are Anthropic). Do not change the pipeline's default thresholds in this task; that is a separate decision for the user.

- [ ] **Step 6: Commit the SR specs only**

```bash
git add sr_specs
git commit -m "Add SR specs for the first eval gold sets" -m "Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

## Self-review (against the spec)

**Coverage**
- Goals 1–4 → Tasks 6 (gold), 4+9 (recall, sweep), 9 (calibration output), 8+9 (κ).
- Gold format incl. `label_source`, `flags`, `unresolved`, `ambiguous`, hash → Task 5; `via` added by the Task 0 amendment.
- Commands `build-gold`, `screen`, `agreement`, `report` → Tasks 6/7/8/9 logic, Task 11 CLI.
- Metrics 1–7 → retrieval recall (T9), screening recall + Wilson (T1, T4, T9), missed positives (T4, T9), workload (T4), sweep + recommended pair (T4), holdout guard (T9), agreement + κ + same_family (T2, T8, T9).
- Error handling: unresolved/ambiguous/zero-positives/no_abstract (T6), hash integrity (T5, T9), resumable screen (T7), missing calls / mixed versions / zero denominators / single-class κ (T1, T2, T9), `errors.log` (T11).
- Testing list: metrics (T1, T2, T4), gold (T5, T6), screen (T7), consistency (T10), CLI smoke (T11), optional live smoke (T11).
- Non-goals respected: no expert-label tooling, no precision headline, no new sources.

**Placeholder scan:** no TBD/TODO; every code step has full code; Task 13 is intentionally a non-code task with concrete commands and a stated approval gate.

**Type/name consistency:** `MissingCall` (storage) is used by `agents.py`, `jev.py`, `report.py`. `decide_from_probabilities(probabilities, thresholds)` used by `metrics.py` and `JevScreener.decide`. Record keys `id/title/label/probabilities/llm` are identical in `metrics.py`, `report.load_records` and the tests. `UnmatchedStudy` (gold) is used by `resolve.py` and the report test. `run_screen(gold, store, evaluator, jev, progress=None)` returns `{"screened", "jev_model_versions"}` consumed by `write_manifest(screened=...)`. `build_report(run_dir, target_recall, holdout_dir, allow_mixed)` matches the CLI call. `Evaluator(store, mode, models, offline)` matches all call sites.

**Known judgement calls to revisit if wrong:** `agreement` reads mode/models from the manifest (spec amended); `sr_specs/` committed and `gold/`/`evals/` ignored; the report keeps the default `JevThresholds()` (0.6/0.9) as the "as shipped" baseline row.
