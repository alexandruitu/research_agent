# Slice 2 · Plan 1: Pipeline (fields and sources) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the research pipeline run a *field* (`domain.json`: topic + inclusion/exclusion criteria + sources + years + thresholds) against Europe PMC, OpenAlex and arXiv, screening per criterion (Jev, then LLM with verified quotes), while legacy positional-topic runs keep today's decisions.

**Architecture:** `DomainSpec` (Pydantic, `schemas.py`) is the frozen contract; it rides inside `Contract.domain`, so it is checkpointed, resumed and written to `report.json` with the rest of the state. Connectors share one retry/fail-closed GET helper and raise `SourceUnavailable(<source>)`; a `MultiSource` wrapper sends every planned query to every configured source. Screening decisions are pure functions in a new `criteria.py` (models answer, code decides); `graph.py` branches on `contract.domain`: absent → today's `topic_match` path, present → per-criterion path.

**Tech Stack:** Python 3.12, Pydantic 2.13, httpx (MockTransport in tests), LangGraph, SQLite (`research.sqlite` raw layer), `xml.etree.ElementTree` for arXiv Atom, pytest, ruff.

**Spec:** `docs/superpowers/specs/2026-09-28-fields-and-sources-design.md` (sections "domain.json", "Pipeline changes", "Testing → Pipeline", "Plans → 1").

---

## Decisions this plan takes (the spec left them open)

1. **`sources` (list) instead of a singular `source` on `Paper`.** Every connector sets `sources=[<name>]`; dedup unions them (sorted). Legacy demo papers get `["demo"]`, Europe PMC `["europepmc"]`. Old `report.json` papers without the key still validate (`default_factory=list`).
2. **LLM payloads never contain `paper.sources`.** `Evaluator.ask` strips it before hashing, so (a) the list of sources cannot bias a model and (b) cache keys of existing eval runs (gold papers) stay identical.
3. **`PROMPT_VERSION` → `m1.2`.** Old caches stay readable because `Evaluator` takes a `prompt_version` and the eval report passes the one recorded in the run's manifest. The legacy `screen` instruction and schema are unchanged; the per-criterion screen is a new role, `screen_criteria`.
4. **Per-criterion LLM role is `screen_criteria`** with schema `CriteriaScreen{answers:[{key, answer, quote}], reason}` (a list, not a dict, so structured output has a fixed schema; `quote` is required and empty when not needed). If a model config has no `screen_criteria` entry it falls back to the `screen` model.
5. **Every non-empty quote is verified** (not only the required ones) with the same `snap`/exact-substring rule as claims; a missing required quote, a wrong key set or a mangled quote → retry (3 attempts) → fail closed.
6. **Jev question wording:** one Noul question per criterion, key = criterion key. `instructions = "Research topic: <topic>. Is this true of the paper? <text> Judge only from the title and abstract in the state."`; `true`/`false` describe "shown true" vs "shown false or no sign". Same form for exclusion criteria (p = probability the exclusion applies).
7. **Decision rule order:** inclusion criteria first (listed order), then exclusion; the first hit is `decided_by`. Jev decisions are `include | exclude | escalate`; LLM decisions `include | exclude | uncertain` (spec's keep/drop = include/exclude, as everywhere else in the pipeline).
8. **Legacy screens also gain `criteria` and `decided_by`:** `criteria = {"topic_match": {"jev_p", "llm": null, "quote": null}}` when Jev ran, else `{}`; `decided_by = "topic_match"` when the decision is `exclude`, else `null`. `decision`, `reason`, `tier`, `jev` are unchanged (characterization test).
9. **No-abstract papers in field runs:** `tier: "rule"`, `decision: "uncertain"`, `decided_by: null`, `criteria` has every key with all three values `null`.
10. **Europe PMC year filter:** `(<query>) AND (PUB_YEAR:[<from|1900> TO <to|9999>])`, only when a bound is set; the query actually sent is what provenance records. OpenAlex: `filter=from_publication_date:YYYY-01-01,to_publication_date:YYYY-12-31`. arXiv: `submittedDate:[YYYY01010000 TO YYYY12312359]` with open ends 1900/3000 (checked live once).
11. **arXiv query building:** words of the planned query (boolean operators and punctuation dropped, at most 8) joined as `all:w1 AND all:w2 …`, AND the category filter `(cat:cs.CV OR cat:eess.IV OR cat:physics.med-ph)`, AND the date clause. Abstract and title whitespace collapsed. Consecutive searches on one connector wait 3 s (arXiv API terms). Raw payload cached as `{"atom": <text>}`. An Atom error entry (`/api/errors`) → `SourceUnavailable`.
12. **Dedup keeps today's rule** (DOI, else normalized title **and same year**, conflicting DOIs never merged). A preprint and its journal version from different years stay separate; noted as a limitation.
13. **`MultiSource.search(query, limit)` ignores `limit`** and uses each source's `max_results`; `Contract.max_papers` still bounds how many unique candidates are screened (normalize step).
14. **Demo mode with a domain:** one `DemoConnector(source=<name>)` per listed source (synthetic records, same ids), so demo runs exercise multi-source dedup and show every source in `sources`.
15. **`domain.json` in the run folder** is a byte copy of the file given to `--domain`; the manifest gets `domain: {"file": "domain.json", "sha256": <of the copy>, "field": <field ref or null>}`. The validated spec itself is `manifest.contract.domain` (aliases `schema`, `from`, `to` preserved).
16. **CLI:** `--domain FILE` and the positional topic are mutually exclusive; `--domain` refuses `--resume`, and refuses `--jev-min-confidence`/`--jev-exclude-min-confidence` (thresholds come from the file). Invalid files exit 2 with `domain.json is invalid: <loc>: <msg>; …`.
17. **`field` in `domain.json` is optional** (hand-written files for the CLI); the web always sends it. At least one criterion (inclusion or exclusion) is required; 1–3 unique sources; `max_results` 1–200; `contact` must look like an email.
18. **Run failure on a source:** progress gets `error_type: "SourceUnavailable"`, `message: "<source>"`, so the web's existing `failure_message` renders `failed at stage 'discover': SourceUnavailable: openalex`.
19. **`research-eval screen --field`:** the run manifest records `field` (the domain dict) and `field_sha256`; a run dir refuses a different field. `report` replays per-criterion runs through the existing two-threshold sweep by converting exclusion probabilities to "criterion satisfied" (`1 - p`); the LLM decision is `decide_llm` over the cached answers. Calibrating the four field thresholds is left for later.

---

## File structure

| File | Responsibility |
|---|---|
| `src/research_agent/schemas.py` | + `Criterion`, `Criteria`, `SourceSpec`, `Years`, `Thresholds`, `FieldRef`, `DomainSpec`, `DomainError`, `read_domain`, `CriterionAnswer`, `CriteriaScreen`; `Paper.sources`; `Contract.domain` |
| `src/research_agent/connectors.py` | `SourceUnavailable`, `fetch` (retries), `EuropePMC(years)`, `OpenAlex`, `ArXiv`, `DemoConnector(source)`, `MultiSource`, `domain_connector`, dedup unions `sources` |
| `src/research_agent/criteria.py` (new) | `criterion_keys`, `decide_jev`, `decide_llm`, `screen_payload`, `satisfied` |
| `src/research_agent/jev.py` | `criteria_questions`, `JevScreener.screen_criteria`, `cached_criteria_probabilities` |
| `src/research_agent/agents.py` | `PROMPT_VERSION = "m1.2"`, `screen_criteria` role, `snap_quote`, `snap_screen`, `CriteriaAnswerError`, `prompt_version` param, sources stripped from payloads |
| `src/research_agent/graph.py` | plan payload, per-criterion screen node, legacy `criteria`/`decided_by` |
| `src/research_agent/report.py` | field line and "found by" in `report.md` |
| `src/research_agent/runner.py` | `make_connector`, `domain.json` copy + manifest, English messages, `SourceUnavailable` progress |
| `src/research_agent/cli.py` | `--domain FILE` |
| `src/research_agent/jobs.py`, `ui.py` | English failure messages |
| `src/research_agent/eval/{screen,report,cli}.py` | `--field`, per-criterion records, manifest prompt version |
| `tests/fixtures/{openalex_works.json,arxiv_query.xml,legacy_screens.json}` | recorded API responses; legacy baseline |
| `tests/test_legacy_screens.py`, `test_domain.py`, `test_connectors.py`, `test_criteria.py`, `test_jev_criteria.py`, `test_screen_criteria.py`, `test_domain_run.py`, `test_eval_field.py` | new tests |

Before every commit: `. .venv/bin/activate && ruff format src tests && ruff check . && pytest -q` (all green, web tests included). Stage exact files only. Commit trailer: `-m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"`.

---

### Task 1: Freeze today's legacy decisions (characterization test)

**Files:**
- Create: `tests/test_legacy_screens.py`
- Create: `tests/fixtures/legacy_screens.json` (generated at HEAD `5909658`, before any change)

- [ ] **Step 1: Write the test** (it also regenerates the baseline with `--write`)

```python
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
```

- [ ] **Step 2: Generate the baseline at HEAD and run**

Run: `cd tests && python test_legacy_screens.py --write && cd .. && pytest -q tests/test_legacy_screens.py`
Expected: `2 passed`. The `jev` baseline has MED:1/4 include (jev), MED:2/5 exclude (jev), MED:3 exclude (llm, "off topic"), MED:6–8 include (llm), MED:9 uncertain (rule).

- [ ] **Step 3: Commit** (the recorded API fixtures of Tasks 4–5 are committed with those tasks)

```bash
git add tests/test_legacy_screens.py tests/fixtures/legacy_screens.json
git commit -m "Freeze today's legacy screening decisions as a characterization test" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: `DomainSpec`, `read_domain`, `Paper.sources`, `Contract.domain`

**Files:**
- Modify: `src/research_agent/schemas.py`
- Create: `tests/test_domain.py`

- [ ] **Step 1: Write the failing tests** — `tests/test_domain.py`

```python
import json

import pytest
from pydantic import ValidationError

from research_agent.schemas import Contract, DomainError, DomainSpec, Paper, read_domain


def domain(**overrides):
    data = {
        "schema": 1,
        "field": {"id": "f-1", "name": "ML CT-FFR", "version": 3},
        "topic": "machine learning or deep learning estimation of CT-derived fractional flow reserve",
        "criteria": {
            "include": [{"key": "i1", "text": "The study uses machine learning or deep learning."}],
            "exclude": [
                {"key": "e1", "text": "The paper is a review, editorial or commentary without original results."}
            ],
        },
        "sources": [
            {"name": "europepmc", "max_results": 100},
            {"name": "openalex", "max_results": 100, "contact": "research-team@example.org"},
        ],
        "years": {"from": 2018, "to": None},
        "thresholds": {"keep_min": 0.8, "include_fail_max": 0.05, "exclude_hit_min": 0.95, "exclude_clear_max": 0.2},
    }
    data.update(overrides)
    return data


def test_the_spec_example_validates_and_dumps_with_its_own_key_names():
    spec = DomainSpec.model_validate(domain())
    assert spec.years.start == 2018 and spec.years.end is None
    assert spec.field.version == 3 and spec.sources[1].contact == "research-team@example.org"
    dumped = spec.model_dump()
    assert dumped["schema"] == 1 and dumped["years"] == {"from": 2018, "to": None}
    assert DomainSpec.model_validate(dumped) == spec


def test_minimal_domain_uses_default_years_and_thresholds():
    data = domain()
    for key in ("field", "years", "thresholds"):
        del data[key]
    spec = DomainSpec.model_validate(data)
    assert spec.field is None and spec.years.start is None and spec.years.end is None
    assert spec.thresholds.model_dump() == {
        "keep_min": 0.8,
        "include_fail_max": 0.05,
        "exclude_hit_min": 0.95,
        "exclude_clear_max": 0.2,
    }


def many(prefix, n):
    return [{"key": f"{prefix}{i}", "text": f"Criterion number {i}."} for i in range(1, n + 1)]


@pytest.mark.parametrize(
    "overrides",
    [
        {"extra": 1},
        {"schema": 2},
        {"topic": "x"},
        {"sources": []},
        {"sources": [{"name": "semanticscholar"}]},
        {"sources": [{"name": "arxiv"}, {"name": "arxiv"}]},
        {"sources": [{"name": "arxiv", "max_results": 0}]},
        {"sources": [{"name": "arxiv", "max_results": 201}]},
        {"sources": [{"name": "openalex", "contact": "not-an-email"}]},
        {"sources": [{"name": "arxiv", "api_key": "x"}]},
        {"criteria": {"include": [], "exclude": []}},
        {"criteria": {"include": [{"key": "i1", "text": "x" * 501}]}},
        {"criteria": {"include": many("i", 11)}},
        {"criteria": {"exclude": many("e", 11)}},
        {"criteria": {"include": [{"key": "e1", "text": "Wrong prefix here."}]}},
        {"criteria": {"include": [{"key": "i1", "text": "One."}, {"key": "i1", "text": "Two."}]}},
        {"criteria": {"include": [{"key": "i1", "text": "Fine text.", "weight": 2}]}},
        {"years": {"from": 2020, "to": 2019}},
        {"years": {"since": 2020}},
        {"thresholds": {"keep_min": 0.05, "include_fail_max": 0.05}},
        {"thresholds": {"exclude_hit_min": 0.2, "exclude_clear_max": 0.2}},
        {"thresholds": {"keep_min": 1.5}},
    ],
)
def test_invalid_domains_are_refused(overrides):
    with pytest.raises(ValidationError):
        DomainSpec.model_validate(domain(**overrides))


def test_read_domain_reports_every_problem_in_one_readable_message(tmp_path):
    path = tmp_path / "domain.json"
    path.write_text(json.dumps(domain(topic="x", sources=[])))
    with pytest.raises(DomainError) as info:
        read_domain(path)
    message = str(info.value)
    assert message.startswith("domain.json is invalid: ")
    assert "topic: String should have at least 3 characters" in message
    assert "sources: List should have at least 1 item" in message


def test_read_domain_refuses_unreadable_and_non_json_files(tmp_path):
    with pytest.raises(DomainError, match="cannot read"):
        read_domain(tmp_path / "missing.json")
    bad = tmp_path / "bad.json"
    bad.write_text("{not json")
    with pytest.raises(DomainError, match="not valid JSON"):
        read_domain(bad)
    good = tmp_path / "good.json"
    good.write_text(json.dumps(domain()))
    assert read_domain(good).topic.startswith("machine learning")


def test_contract_carries_the_domain_and_round_trips_through_a_dump():
    spec = DomainSpec.model_validate(domain())
    contract = Contract(topic=spec.topic, domain=spec)
    dumped = contract.model_dump()
    assert dumped["domain"]["years"] == {"from": 2018, "to": None} and dumped["domain"]["schema"] == 1
    assert Contract.model_validate(dumped) == contract
    with pytest.raises(ValidationError, match="topic must equal"):
        Contract(topic="something else entirely", domain=spec)
    assert Contract(topic="legacy topic").model_dump()["domain"] is None


def test_paper_sources_default_to_empty_for_old_reports():
    paper = {
        "id": "x:1",
        "title": "t",
        "abstract": "a",
        "provenance": [
            {"connector": "c", "record_id": "x:1", "url": "u", "query": "q", "retrieved_at": "r", "raw_sha256": "h"}
        ],
    }
    assert Paper.model_validate(paper).sources == []
    assert Paper.model_validate({**paper, "sources": ["openalex"]}).sources == ["openalex"]
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest -q tests/test_domain.py`
Expected: FAIL — `ImportError: cannot import name 'DomainError'`.

- [ ] **Step 3: Implement** — in `src/research_agent/schemas.py`, change the imports and add the models (keep every existing class as is, except `Contract` and `Paper` shown here).

```python
import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


# Keys may have aliases that are Python keywords or BaseModel attributes ("schema", "from"): the file uses the
# alias, the code the name, and every dump writes the alias back so report.json matches domain.json.
ALIASED = ConfigDict(extra="forbid", validate_by_name=True, validate_by_alias=True, serialize_by_alias=True)


class Criterion(Model):
    key: str = Field(pattern=r"^[ie][1-9][0-9]?$")
    text: str = Field(min_length=3, max_length=500)


class Criteria(Model):
    include: list[Criterion] = Field(default_factory=list, max_length=10)
    exclude: list[Criterion] = Field(default_factory=list, max_length=10)

    @model_validator(mode="after")
    def _keys(self):
        if not (self.include or self.exclude):
            raise ValueError("at least one inclusion or exclusion criterion is required")
        for criteria, prefix in ((self.include, "i"), (self.exclude, "e")):
            for criterion in criteria:
                if not criterion.key.startswith(prefix):
                    raise ValueError(f"criterion key {criterion.key!r} must start with {prefix!r}")
        keys = [c.key for c in self.include + self.exclude]
        if len(set(keys)) != len(keys):
            raise ValueError("criterion keys must be unique")
        return self


class SourceSpec(Model):
    name: Literal["europepmc", "openalex", "arxiv"]
    max_results: int = Field(default=100, ge=1, le=200)
    contact: str | None = Field(default=None, max_length=200, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class Years(Model):
    model_config = ALIASED
    start: int | None = Field(default=None, alias="from", ge=1900, le=2100)
    end: int | None = Field(default=None, alias="to", ge=1900, le=2100)

    @model_validator(mode="after")
    def _order(self):
        if self.start is not None and self.end is not None and self.start > self.end:
            raise ValueError("years.from must not be after years.to")
        return self


class Thresholds(Model):
    keep_min: float = Field(default=0.8, ge=0, le=1)
    include_fail_max: float = Field(default=0.05, ge=0, le=1)
    exclude_hit_min: float = Field(default=0.95, ge=0, le=1)
    exclude_clear_max: float = Field(default=0.2, ge=0, le=1)

    @model_validator(mode="after")
    def _bands(self):
        if self.include_fail_max >= self.keep_min:
            raise ValueError("include_fail_max must be below keep_min")
        if self.exclude_clear_max >= self.exclude_hit_min:
            raise ValueError("exclude_clear_max must be below exclude_hit_min")
        return self


class FieldRef(Model):
    id: str = Field(min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=200)
    version: int = Field(ge=1)


class DomainSpec(Model):
    """domain.json: the frozen contract between the web app and one pipeline run."""

    model_config = ALIASED
    schema_version: Literal[1] = Field(alias="schema")
    field: FieldRef | None = None
    topic: str = Field(min_length=3, max_length=500)
    criteria: Criteria
    sources: list[SourceSpec] = Field(min_length=1, max_length=3)
    years: Years = Field(default_factory=Years)
    thresholds: Thresholds = Field(default_factory=Thresholds)

    @model_validator(mode="after")
    def _unique_sources(self):
        names = [s.name for s in self.sources]
        if len(set(names)) != len(names):
            raise ValueError("each source may be listed once")
        return self


class DomainError(ValueError):
    """domain.json cannot be read or is invalid; the message lists every problem."""


def read_domain(path):
    path = Path(path)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise DomainError(f"cannot read {path}: {exc.strerror}") from None
    except ValueError as exc:
        raise DomainError(f"{path.name} is not valid JSON ({exc})") from None
    try:
        return DomainSpec.model_validate(data)
    except ValidationError as exc:
        problems = "; ".join(
            f"{'.'.join(str(part) for part in error['loc']) or '(root)'}: {error['msg']}" for error in exc.errors()
        )
        raise DomainError(f"domain.json is invalid: {problems}") from None
```

Change `Contract` (add the field and extend the validator):

```python
class Contract(Model):
    topic: str = Field(min_length=3, max_length=500)
    max_papers: int = Field(default=12, ge=1, le=30)
    mode: Literal["demo", "live"] = "demo"
    scope: Literal["abstract_only"] = "abstract_only"
    # Jev screening tier (cascade ahead of the LLM screen). Asymmetric: recall over precision.
    jev: bool = False
    jev_min_confidence: float = Field(default=0.6, ge=0, le=1)
    jev_exclude_min_confidence: float = Field(default=0.9, ge=0, le=1)
    # A field run (domain.json); None is a legacy topic run with one topic_match question.
    domain: DomainSpec | None = None

    @model_validator(mode="after")
    def _jev_needs_live(self):
        if self.jev and self.mode != "live":
            raise ValueError("Jev screening requires live mode")
        if self.jev_exclude_min_confidence < self.jev_min_confidence:
            raise ValueError("jev_exclude_min_confidence must be >= jev_min_confidence")
        if self.domain is not None and self.topic != self.domain.topic:
            raise ValueError("topic must equal domain.topic")
        return self
```

`Contract` must be defined after `DomainSpec`: move the `Contract` class below `read_domain`. Add to `Paper`, after `doi`:

```python
    sources: list[str] = Field(default_factory=list)  # connectors that found it (after dedup: all of them)
```

- [ ] **Step 4: Run** `pytest -q tests/test_domain.py` → `28 passed` (22 parametrized + 6). Then full `pytest -q` → all green.

- [ ] **Step 5: Commit**

```bash
git add src/research_agent/schemas.py tests/test_domain.py
git commit -m "Add DomainSpec (domain.json), read_domain, Paper.sources and Contract.domain" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: Shared fetch with fail-closed `SourceUnavailable`; Europe PMC year filter and `sources`

**Files:**
- Modify: `src/research_agent/connectors.py`
- Modify: `tests/test_pipeline.py` (`test_source_failure_is_not_reported_as_empty` expects `SourceUnavailable`)
- Create: `tests/test_connectors.py`

- [ ] **Step 1: Write the failing tests** — `tests/test_connectors.py`

```python
import json

import httpx
import pytest
from eval_helpers import row

from research_agent import connectors
from research_agent.connectors import DemoConnector, EuropePMC, SourceUnavailable
from research_agent.schemas import Years
from research_agent.storage import Store


@pytest.fixture(autouse=True)
def no_backoff(monkeypatch):
    monkeypatch.setattr(connectors.time, "sleep", lambda _s: None)


def recording(payload, status=200):
    requests = []

    def handler(request):
        requests.append(request)
        body = payload(request) if callable(payload) else payload
        return httpx.Response(status, **({"json": body} if isinstance(body, dict) else {"text": body}))

    client = httpx.Client(transport=httpx.MockTransport(handler))
    client.requests = requests
    return client


def epmc(rows):
    return {"resultList": {"result": rows}}


def test_europepmc_year_filter_is_sent_and_recorded(tmp_path):
    client = recording(epmc([row(1)]))
    papers = EuropePMC(Store(tmp_path), client, years=Years(start=2018)).search("ffr", 5)
    sent = client.requests[0].url.params["query"]
    assert sent == "(ffr) AND (PUB_YEAR:[2018 TO 9999])"
    assert papers[0].provenance[0].query == sent
    assert papers[0].sources == ["europepmc"]
    bounded = recording(epmc([]))
    EuropePMC(Store(tmp_path), bounded, years=Years(start=2018, end=2020)).search("ffr", 5)
    assert bounded.requests[0].url.params["query"] == "(ffr) AND (PUB_YEAR:[2018 TO 2020])"


def test_europepmc_without_years_sends_the_query_unchanged(tmp_path):
    client = recording(epmc([row(1)]))
    EuropePMC(Store(tmp_path), client).search("ffr", 5)
    EuropePMC(Store(tmp_path), client, years=Years()).search("ffr", 5)
    assert [r.url.params["query"] for r in client.requests] == ["ffr", "ffr"]


@pytest.mark.parametrize("status,attempts", [(400, 1), (503, 3), (429, 3)])
def test_http_failures_raise_source_unavailable_after_the_same_retries(tmp_path, status, attempts):
    client = recording(epmc([]), status=status)
    with pytest.raises(SourceUnavailable) as info:
        EuropePMC(Store(tmp_path), client).search("q", 2)
    assert info.value.source == "europepmc" and str(info.value) == "europepmc"
    assert len(client.requests) == attempts


def test_transport_errors_are_retried_then_fail_closed(tmp_path):
    calls = []

    def handler(request):
        calls.append(request)
        raise httpx.ConnectError("down")

    with pytest.raises(SourceUnavailable):
        EuropePMC(Store(tmp_path), httpx.Client(transport=httpx.MockTransport(handler))).search("q", 2)
    assert len(calls) == 3


@pytest.mark.parametrize("body", [{"unexpected": 1}, {"resultList": {"result": [{"title": "no id"}]}}, "not json"])
def test_malformed_responses_fail_closed(tmp_path, body):
    with pytest.raises(SourceUnavailable):
        EuropePMC(Store(tmp_path), recording(body)).search("q", 2)


def test_demo_connector_names_its_source(tmp_path):
    store = Store(tmp_path)
    assert DemoConnector(store).search("q", 1)[0].sources == ["demo"]
    assert DemoConnector(store, source="openalex").search("q", 1)[0].sources == ["openalex"]


def test_raw_payload_is_cached_before_parsing(tmp_path):
    store = Store(tmp_path)
    paper = EuropePMC(store, recording(epmc([row(7)]))).search("q", 1)[0]
    with store.connect() as db:
        raw = db.execute("SELECT payload FROM raw WHERE hash=?", (paper.provenance[0].raw_sha256,)).fetchone()
    assert json.loads(raw[0])["resultList"]["result"][0]["id"] == "7"
```

In `tests/test_pipeline.py` replace the body of `test_source_failure_is_not_reported_as_empty`:

```python
def test_source_failure_is_not_reported_as_empty(tmp_path):
    from research_agent.connectors import SourceUnavailable

    with (
        httpx.Client(transport=httpx.MockTransport(lambda req: httpx.Response(400))) as client,
        pytest.raises(SourceUnavailable, match="europepmc"),
    ):
        EuropePMC(Store(tmp_path), client).search("bad", 2)
```

- [ ] **Step 2: Run** `pytest -q tests/test_connectors.py` → FAIL (`ImportError: cannot import name 'SourceUnavailable'`).

- [ ] **Step 3: Implement** — in `connectors.py` add after `normalize_doi`:

```python
RETRYABLE = (429, 500, 502, 503, 504)


class SourceUnavailable(RuntimeError):
    """A source failed after retries or answered with something unreadable. Fail closed: the run stops
    (checkpoint kept). The message is only the source name, so it is safe to show and to log."""

    def __init__(self, source):
        super().__init__(source)
        self.source = source


def fetch(client, url, params, source, decode):
    """One GET with the Europe PMC policy of M1: 3 attempts, backoff 1 s then 2 s on transport errors and
    429/5xx, 30 s timeout. Any failure, including an undecodable body, raises SourceUnavailable."""

    def attempts(http):
        for attempt in range(3):
            try:
                response = http.get(url, params=params)
                response.raise_for_status()
                return decode(response)
            except (httpx.TransportError, httpx.HTTPStatusError) as exc:
                retryable = not isinstance(exc, httpx.HTTPStatusError) or exc.response.status_code in RETRYABLE
                if not retryable or attempt == 2:
                    raise SourceUnavailable(source) from exc
                time.sleep(2**attempt)
            except ValueError as exc:
                raise SourceUnavailable(source) from exc

    if client is not None:
        return attempts(client)
    with httpx.Client(timeout=30, follow_redirects=True) as http:
        return attempts(http)
```

Replace `EuropePMC`:

```python
class EuropePMC:
    name = "europepmc"
    endpoint = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"

    def __init__(self, store, client=None, years=None):
        self.store = store
        self.client = client
        self.years = years

    def full_query(self, query):
        if self.years is None or (self.years.start is None and self.years.end is None):
            return query
        return f"({query}) AND (PUB_YEAR:[{self.years.start or 1900} TO {self.years.end or 9999}])"

    def search(self, query, limit):
        query = self.full_query(query)
        params = {"query": query, "format": "json", "resultType": "core", "pageSize": limit}
        # A single bounded page per query; raw payload retained before parsing.
        payload = fetch(self.client, self.endpoint, params, self.name, lambda response: response.json())
        raw_hash = self.store.raw(payload)
        retrieved = datetime.now(UTC).isoformat()
        try:
            return [self._paper(row, query, retrieved, raw_hash) for row in payload["resultList"]["result"]]
        except (KeyError, TypeError, ValueError) as exc:
            raise SourceUnavailable(self.name) from exc

    def _paper(self, row, query, retrieved, raw_hash):
        source, rid = row["source"], row["id"]
        return Paper(
            id=f"{source}:{rid}",
            title=plain(row.get("title")),
            abstract=plain(row.get("abstractText")),
            year=str(row.get("pubYear", "")),
            doi=normalize_doi(row.get("doi", "")),
            sources=[self.name],
            provenance=[
                Source(
                    connector="europe_pmc",
                    record_id=f"{source}:{rid}",
                    url=f"https://europepmc.org/article/{source}/{rid}",
                    query=query,
                    retrieved_at=retrieved,
                    raw_sha256=raw_hash,
                )
            ],
        )
```

`DemoConnector`: `def __init__(self, store, source="demo")` storing `self.source = source`, and `sources=[self.source],` in the `Paper(...)` call.

- [ ] **Step 4: Run** `pytest -q tests/test_connectors.py tests/test_pipeline.py tests/test_legacy_screens.py` → all pass; then full `pytest -q`.

- [ ] **Step 5: Commit**

```bash
git add src/research_agent/connectors.py tests/test_connectors.py tests/test_pipeline.py
git commit -m "Connectors: shared fail-closed fetch (SourceUnavailable), Europe PMC year filter, sources on papers" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: OpenAlex connector

**Files:**
- Modify: `src/research_agent/connectors.py`
- Create: `tests/fixtures/openalex_works.json` (recorded once, trimmed to 2 works; the second work's `abstract_inverted_index` set to `null`, as OpenAlex returns for works without an abstract)
- Modify: `tests/test_connectors.py`

Fixture query (recorded 2026-09-28): `GET https://api.openalex.org/works?search=CT%20fractional%20flow%20reserve%20deep%20learning&filter=from_publication_date:2018-01-01&per-page=3&select=id,doi,title,publication_year,abstract_inverted_index` — results 1 and 3 kept.

- [ ] **Step 1: Write the failing tests** — append to `tests/test_connectors.py`

```python
from pathlib import Path

from research_agent.connectors import OpenAlex, rebuild_abstract

FIXTURES = Path(__file__).parent / "fixtures"
# Recorded 2026-09-28: GET https://api.openalex.org/works?search=CT%20fractional%20flow%20reserve%20deep%20learning
# &filter=from_publication_date:2018-01-01&per-page=3&select=id,doi,title,publication_year,abstract_inverted_index
OPENALEX = json.loads((FIXTURES / "openalex_works.json").read_text())


def test_rebuild_abstract_orders_words_by_position():
    assert rebuild_abstract({"b": [1], "a": [0, 2]}) == "a b a"
    assert rebuild_abstract(None) == "" and rebuild_abstract({}) == ""


def test_openalex_parses_recorded_works(tmp_path):
    store = Store(tmp_path)
    first, second = OpenAlex(store, recording(OPENALEX)).search("ct ffr", 2)
    assert first.id == "openalex:W2807965844" and first.year == "2018"
    assert first.doi == "10.1161/circimaging.117.007217"
    assert first.title.startswith("Diagnostic Accuracy of a Machine-Learning Approach")
    assert first.abstract.startswith("Background: Coronary computed tomographic angiography (CTA) is a reliable")
    assert first.abstract.endswith("performs equally well as CFD-based CT-FFR.")
    assert first.sources == ["openalex"]
    assert first.provenance[0].url == "https://openalex.org/W2807965844"
    assert first.provenance[0].connector == "openalex"
    assert second.id == "openalex:W4281259955" and second.abstract == ""
    with store.connect() as db:
        raw = db.execute("SELECT payload FROM raw WHERE hash=?", (first.provenance[0].raw_sha256,)).fetchone()
    assert json.loads(raw[0])["results"][0]["id"] == "https://openalex.org/W2807965844"


def test_openalex_request_parameters(tmp_path):
    client = recording(OPENALEX)
    OpenAlex(Store(tmp_path), client, years=Years(start=2018, end=2024), contact="team@example.org").search("ct ffr", 500)
    OpenAlex(Store(tmp_path), client).search("ct ffr", 20)
    with_all, plain_request = (r.url.params for r in client.requests)
    assert with_all["search"] == "ct ffr" and with_all["per-page"] == "200"
    assert with_all["filter"] == "from_publication_date:2018-01-01,to_publication_date:2024-12-31"
    assert with_all["mailto"] == "team@example.org"
    assert with_all["select"] == "id,doi,title,publication_year,abstract_inverted_index"
    assert "filter" not in plain_request and "mailto" not in plain_request and plain_request["per-page"] == "20"


@pytest.mark.parametrize("status,body", [(500, OPENALEX), (200, {"meta": {}}), (200, {"results": [{"title": "x"}]})])
def test_openalex_failures_fail_closed(tmp_path, status, body):
    with pytest.raises(SourceUnavailable, match="openalex"):
        OpenAlex(Store(tmp_path), recording(body, status=status)).search("q", 2)
```

- [ ] **Step 2: Run** `pytest -q tests/test_connectors.py` → FAIL (`ImportError: cannot import name 'OpenAlex'`).

- [ ] **Step 3: Implement** — append to `connectors.py` (after `EuropePMC`):

```python
def rebuild_abstract(index):
    """OpenAlex ships abstracts as {word: [positions]}; put every word back at its position."""
    if not index:
        return ""
    return " ".join(word for _position, word in sorted((p, w) for w, positions in index.items() for p in positions))


class OpenAlex:
    name = "openalex"
    endpoint = "https://api.openalex.org/works"
    select = "id,doi,title,publication_year,abstract_inverted_index"

    def __init__(self, store, client=None, years=None, contact=None):
        self.store = store
        self.client = client
        self.years = years
        self.contact = contact  # polite pool; never recorded in provenance

    def search(self, query, limit):
        params = {"search": query, "per-page": min(limit, 200), "select": self.select}
        filters = []
        if self.years is not None and self.years.start is not None:
            filters.append(f"from_publication_date:{self.years.start}-01-01")
        if self.years is not None and self.years.end is not None:
            filters.append(f"to_publication_date:{self.years.end}-12-31")
        if filters:
            params["filter"] = ",".join(filters)
        if self.contact:
            params["mailto"] = self.contact
        payload = fetch(self.client, self.endpoint, params, self.name, lambda response: response.json())
        raw_hash = self.store.raw(payload)
        retrieved = datetime.now(UTC).isoformat()
        try:
            return [self._paper(row, query, retrieved, raw_hash) for row in payload["results"]]
        except (KeyError, TypeError, ValueError, AttributeError) as exc:
            raise SourceUnavailable(self.name) from exc

    def _paper(self, row, query, retrieved, raw_hash):
        work = row["id"].rsplit("/", 1)[-1]
        return Paper(
            id=f"openalex:{work}",
            title=plain(row.get("title")),
            abstract=rebuild_abstract(row.get("abstract_inverted_index")),
            year=str(row.get("publication_year") or ""),
            doi=normalize_doi(row.get("doi") or ""),
            sources=[self.name],
            provenance=[
                Source(
                    connector="openalex",
                    record_id=f"openalex:{work}",
                    url=row["id"],
                    query=query,
                    retrieved_at=retrieved,
                    raw_sha256=raw_hash,
                )
            ],
        )
```

- [ ] **Step 4: Run** `pytest -q tests/test_connectors.py` → pass; full `pytest -q`.

- [ ] **Step 5: Commit**

```bash
git add src/research_agent/connectors.py tests/test_connectors.py tests/fixtures/openalex_works.json
git commit -m "Add the OpenAlex connector (abstract rebuilt from the inverted index, polite-pool contact)" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: arXiv connector

**Files:**
- Modify: `src/research_agent/connectors.py`
- Create: `tests/fixtures/arxiv_query.xml` (recorded once; author lists trimmed to the first author; the query is in an XML comment on line 2)
- Modify: `tests/test_connectors.py`

Fixture query (recorded 2026-09-28): `GET https://export.arxiv.org/api/query?search_query=all:%22fractional%20flow%20reserve%22%20AND%20(cat:cs.CV%20OR%20cat:eess.IV%20OR%20cat:physics.med-ph)&start=0&max_results=2`.

- [ ] **Step 1: Write the failing tests** — append to `tests/test_connectors.py`

```python
from research_agent.connectors import ArXiv

ARXIV = (FIXTURES / "arxiv_query.xml").read_text()
ARXIV_ERROR = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom"><entry><id>http://arxiv.org/api/errors#incorrect_id_format</id>
<title>Error</title><summary>incorrect id format</summary></entry></feed>"""


def test_arxiv_query_uses_words_categories_and_dates(tmp_path):
    arxiv = ArXiv(Store(tmp_path), years=Years(start=2018))
    assert arxiv.search_query('"deep learning" AND (FFR OR CT-FFR)') == (
        "all:deep AND all:learning AND all:FFR AND all:CT-FFR"
        " AND (cat:cs.CV OR cat:eess.IV OR cat:physics.med-ph)"
        " AND submittedDate:[201801010000 TO 300012312359]"
    )
    assert ArXiv(Store(tmp_path)).search_query("a b c d e f g h i j") == (
        "all:a AND all:b AND all:c AND all:d AND all:e AND all:f AND all:g AND all:h"
        " AND (cat:cs.CV OR cat:eess.IV OR cat:physics.med-ph)"
    )


def test_arxiv_parses_recorded_entries_and_caches_the_atom_text(tmp_path):
    store = Store(tmp_path)
    client = recording(ARXIV)
    first, second = ArXiv(store, client).search("fractional flow reserve", 500)
    assert client.requests[0].url.params["max_results"] == "200"
    assert client.requests[0].url.params["start"] == "0"
    assert first.id == "arxiv:1805.11472" and first.year == "2018" and first.doi == ""
    assert first.title == "Comparison of 1D and 3D Models for the Estimation of Fractional Flow Reserve"
    assert first.abstract.startswith("In this work we propose to validate the predictive capabilities")
    assert "  " not in first.abstract and "\n" not in first.abstract
    assert first.sources == ["arxiv"] and first.provenance[0].url == "https://arxiv.org/abs/1805.11472"
    assert second.id == "arxiv:2308.04923" and second.year == "2023"
    with store.connect() as db:
        raw = db.execute("SELECT payload FROM raw WHERE hash=?", (first.provenance[0].raw_sha256,)).fetchone()
    assert json.loads(raw[0]) == {"atom": ARXIV}


def test_arxiv_waits_three_seconds_between_requests(tmp_path):
    waits = []
    arxiv = ArXiv(Store(tmp_path), recording(ARXIV), sleep=waits.append)
    arxiv.search("a", 1)
    arxiv.search("b", 1)
    assert waits == [3]


@pytest.mark.parametrize("status,body", [(503, ARXIV), (200, ARXIV_ERROR), (200, "<feed><entry>")])
def test_arxiv_failures_fail_closed(tmp_path, status, body):
    with pytest.raises(SourceUnavailable, match="arxiv"):
        ArXiv(Store(tmp_path), recording(body, status=status)).search("q", 2)
```

- [ ] **Step 2: Run** `pytest -q tests/test_connectors.py` → FAIL (`cannot import name 'ArXiv'`).

- [ ] **Step 3: Implement** — `import xml.etree.ElementTree as ET` at the top of `connectors.py`, then:

```python
ARXIV_CATEGORIES = ("cs.CV", "eess.IV", "physics.med-ph")
ATOM = {"a": "http://www.w3.org/2005/Atom", "arxiv": "http://arxiv.org/schemas/atom"}
OPERATORS = {"AND", "OR", "NOT", "ANDNOT"}


class ArXiv:
    """arXiv Atom API. Python's expat refuses entity-expansion attacks; arXiv is the only producer here."""

    name = "arxiv"
    endpoint = "https://export.arxiv.org/api/query"

    def __init__(self, store, client=None, years=None, sleep=time.sleep):
        self.store = store
        self.client = client
        self.years = years
        self.sleep = sleep
        self.requested = False

    def search_query(self, query):
        words = [w for w in re.findall(r"\w[\w.\-]*", query) if w.upper() not in OPERATORS][:8]
        parts = [" AND ".join(f"all:{w}" for w in words)] if words else []
        parts.append("(" + " OR ".join(f"cat:{c}" for c in ARXIV_CATEGORIES) + ")")
        if self.years is not None and (self.years.start is not None or self.years.end is not None):
            parts.append(f"submittedDate:[{self.years.start or 1900}01010000 TO {self.years.end or 3000}12312359]")
        return " AND ".join(parts)

    def search(self, query, limit):
        if self.requested:
            self.sleep(3)  # arXiv API terms: no more than one request every three seconds
        self.requested = True
        search_query = self.search_query(query)
        params = {"search_query": search_query, "start": 0, "max_results": min(limit, 200)}
        text = fetch(self.client, self.endpoint, params, self.name, lambda response: response.text)
        raw_hash = self.store.raw({"atom": text})
        retrieved = datetime.now(UTC).isoformat()
        try:
            entries = ET.fromstring(text).findall("a:entry", ATOM)
            return [self._paper(entry, search_query, retrieved, raw_hash) for entry in entries]
        except (ET.ParseError, AttributeError, ValueError) as exc:
            raise SourceUnavailable(self.name) from exc

    def _paper(self, entry, query, retrieved, raw_hash):
        link = entry.findtext("a:id", namespaces=ATOM).strip()
        if "/api/errors" in link:
            raise ValueError("arXiv returned an error entry")
        arxiv_id = re.sub(r"v\d+$", "", link.rsplit("/abs/", 1)[-1])
        return Paper(
            id=f"arxiv:{arxiv_id}",
            title=" ".join(entry.findtext("a:title", default="", namespaces=ATOM).split()),
            abstract=" ".join(entry.findtext("a:summary", default="", namespaces=ATOM).split()),
            year=entry.findtext("a:published", default="", namespaces=ATOM)[:4],
            doi=normalize_doi(entry.findtext("arxiv:doi", default="", namespaces=ATOM)),
            sources=[self.name],
            provenance=[
                Source(
                    connector="arxiv",
                    record_id=f"arxiv:{arxiv_id}",
                    url=f"https://arxiv.org/abs/{arxiv_id}",
                    query=query,
                    retrieved_at=retrieved,
                    raw_sha256=raw_hash,
                )
            ],
        )
```

- [ ] **Step 4: Run** `pytest -q tests/test_connectors.py` → pass; full `pytest -q`.

- [ ] **Step 5: Commit**

```bash
git add src/research_agent/connectors.py tests/test_connectors.py tests/fixtures/arxiv_query.xml
git commit -m "Add the arXiv connector (Atom API, imaging categories, date filter, 3 s pacing)" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 6: Multi-source dedup, `MultiSource`, `domain_connector`

**Files:**
- Modify: `src/research_agent/connectors.py`
- Modify: `tests/test_connectors.py`

- [ ] **Step 1: Write the failing tests** — append to `tests/test_connectors.py`

```python
from research_agent.connectors import MultiSource, deduplicate, domain_connector
from research_agent.schemas import DomainSpec, Paper, Source


def paper(pid, source, doi="", title="Same title", year="2024", abstract="text"):
    return Paper(
        id=pid,
        title=title,
        abstract=abstract,
        year=year,
        doi=doi,
        sources=[source],
        provenance=[Source(connector=source, record_id=pid, url=pid, query="q", retrieved_at="r", raw_sha256="h")],
    )


def test_dedup_merges_across_sources_and_keeps_every_source():
    merged = deduplicate(
        [
            paper("MED:1", "europepmc", doi="10.1/x", abstract="short"),
            paper("openalex:W1", "openalex", doi="https://doi.org/10.1/X", abstract="the longer abstract"),
            paper("arxiv:1", "arxiv", title="Other"),
            paper("arxiv:2", "arxiv", title="Title only", year="2023"),
            paper("MED:2", "europepmc", title="Title only!", year="2023"),
        ]
    )
    by_id = {p.id: p for p in merged}
    assert set(by_id) == {"openalex:W1", "arxiv:1", "MED:2"}
    assert by_id["openalex:W1"].sources == ["europepmc", "openalex"]
    assert len(by_id["openalex:W1"].provenance) == 2
    assert by_id["MED:2"].sources == ["arxiv", "europepmc"]  # same normalized title and year
    assert by_id["arxiv:1"].sources == ["arxiv"]


def test_a_preprint_and_a_journal_version_from_different_years_stay_separate():
    merged = deduplicate([paper("arxiv:1", "arxiv", year="2022"), paper("MED:1", "europepmc", year="2023")])
    assert len(merged) == 2


def test_multisource_sends_each_query_to_every_source_with_its_own_limit(tmp_path):
    calls = []

    class Fake:
        def __init__(self, name):
            self.name = name

        def search(self, query, limit):
            calls.append((self.name, query, limit))
            return [paper(f"{self.name}:1", self.name)]

    papers = MultiSource([(Fake("a"), 5), (Fake("b"), 7)]).search("q", 12)
    assert calls == [("a", "q", 5), ("b", "q", 7)] and [p.id for p in papers] == ["a:1", "b:1"]


def spec(sources, years=None):
    return DomainSpec.model_validate(
        {
            "schema": 1,
            "topic": "deep learning CT-FFR",
            "criteria": {"include": [{"key": "i1", "text": "Uses deep learning."}]},
            "sources": sources,
            **({"years": years} if years else {}),
        }
    )


def test_domain_connector_builds_live_sources_with_years_and_contact(tmp_path):
    domain = spec(
        [{"name": "europepmc", "max_results": 10}, {"name": "openalex", "contact": "a@b.org"}, {"name": "arxiv"}],
        years={"from": 2019, "to": None},
    )
    multi = domain_connector(domain, Store(tmp_path), "live")
    (epmc, n1), (openalex, n2), (arxiv, n3) = multi.sources
    assert (type(epmc), type(openalex), type(arxiv)) == (EuropePMC, OpenAlex, ArXiv)
    assert (n1, n2, n3) == (10, 100, 100)
    assert epmc.years.start == openalex.years.start == arxiv.years.start == 2019
    assert openalex.contact == "a@b.org"


def test_domain_connector_in_demo_mode_uses_synthetic_records_per_source(tmp_path):
    multi = domain_connector(spec([{"name": "europepmc"}, {"name": "arxiv"}]), Store(tmp_path), "demo")
    merged = deduplicate(multi.search("q", 3))
    assert len(merged) == 12 and all(p.sources == ["arxiv", "europepmc"] for p in merged)
```

- [ ] **Step 2: Run** → FAIL (`cannot import name 'MultiSource'`).

- [ ] **Step 3: Implement** — in `connectors.py`:

```python
class MultiSource:
    """A field's sources: every planned query goes to every source, each with its own max_results.
    The graph's per-query `limit` bounds legacy single-source runs only and is ignored here."""

    def __init__(self, sources):
        self.sources = list(sources)  # [(connector, max_results)]

    def search(self, query, limit):
        papers = []
        for connector, max_results in self.sources:
            papers.extend(connector.search(query, max_results))
        return papers


def domain_connector(domain, store, mode):
    sources = []
    for source in domain.sources:
        if mode == "demo":
            connector = DemoConnector(store, source=source.name)
        elif source.name == "europepmc":
            connector = EuropePMC(store, years=domain.years)
        elif source.name == "openalex":
            connector = OpenAlex(store, years=domain.years, contact=source.contact)
        else:
            connector = ArXiv(store, years=domain.years)
        sources.append((connector, source.max_results))
    return MultiSource(sources)
```

`DemoConnector.search` keeps `min(limit, 12)`. In `deduplicate`, after `primary.doi = …` add:

```python
        primary.sources = sorted({s for p in group for s in p.sources})
```

- [ ] **Step 4: Run** `pytest -q tests/test_connectors.py tests/test_pipeline.py tests/test_legacy_screens.py`; full `pytest -q`.

- [ ] **Step 5: Commit**

```bash
git add src/research_agent/connectors.py tests/test_connectors.py
git commit -m "Merge papers across sources keeping every source; MultiSource and domain_connector" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 7: Per-criterion decision rules (`criteria.py`)

**Files:**
- Create: `src/research_agent/criteria.py`
- Create: `tests/test_criteria.py`

- [ ] **Step 1: Write the failing tests**

```python
import pytest

from research_agent.criteria import criterion_keys, decide_jev, decide_llm, satisfied, screen_payload

CRITERIA = {
    "include": [{"key": "i1", "text": "Uses ML."}, {"key": "i2", "text": "Uses CT."}],
    "exclude": [{"key": "e1", "text": "Is a review."}],
}
T = {"keep_min": 0.8, "include_fail_max": 0.05, "exclude_hit_min": 0.95, "exclude_clear_max": 0.2}


@pytest.mark.parametrize(
    "p,expected",
    [
        ({"i1": 0.9, "i2": 0.85, "e1": 0.1}, ("include", None)),
        ({"i1": 0.8, "i2": 0.8, "e1": 0.2}, ("include", None)),  # bounds are inclusive
        ({"i1": 0.05, "i2": 0.9, "e1": 0.1}, ("exclude", "i1")),
        ({"i1": 0.9, "i2": 0.01, "e1": 0.99}, ("exclude", "i2")),  # inclusion checked first
        ({"i1": 0.9, "i2": 0.9, "e1": 0.95}, ("exclude", "e1")),
        ({"i1": 0.79, "i2": 0.9, "e1": 0.1}, ("escalate", None)),
        ({"i1": 0.9, "i2": 0.9, "e1": 0.21}, ("escalate", None)),
        ({"i1": 0.06, "i2": 0.9, "e1": 0.94}, ("escalate", None)),
    ],
)
def test_jev_decision_table(p, expected):
    assert decide_jev(p, CRITERIA, T) == expected


@pytest.mark.parametrize(
    "answers,expected",
    [
        ({"i1": "yes", "i2": "yes", "e1": "no"}, ("include", None)),
        ({"i1": "no", "i2": "yes", "e1": "yes"}, ("exclude", "i1")),
        ({"i1": "yes", "i2": "yes", "e1": "yes"}, ("exclude", "e1")),
        ({"i1": "unclear", "i2": "yes", "e1": "no"}, ("uncertain", None)),
        ({"i1": "yes", "i2": "yes", "e1": "unclear"}, ("uncertain", None)),
    ],
)
def test_llm_decision_table(answers, expected):
    assert decide_llm(answers, CRITERIA) == expected


def test_exclusion_only_and_inclusion_only_fields():
    only_exclude = {"include": [], "exclude": [{"key": "e1", "text": "Is a review."}]}
    assert decide_jev({"e1": 0.1}, only_exclude, T) == ("include", None)
    assert decide_llm({"e1": "no"}, only_exclude) == ("include", None)
    only_include = {"include": [{"key": "i1", "text": "Uses ML."}], "exclude": []}
    assert decide_jev({"i1": 0.5}, only_include, T) == ("escalate", None)


def test_keys_payload_and_satisfied():
    assert criterion_keys(CRITERIA) == ["i1", "i2", "e1"]
    domain = {"topic": "t", "criteria": CRITERIA, "sources": [], "thresholds": T}
    paper = {"id": "p", "title": "x", "abstract": "y"}
    assert screen_payload(domain, paper) == {"topic": "t", "criteria": CRITERIA, "paper": paper}
    assert satisfied({"i1": 0.9, "i2": 0.2, "e1": 0.3}, CRITERIA) == {"i1": 0.9, "i2": 0.2, "e1": 0.7}
```

- [ ] **Step 2: Run** `pytest -q tests/test_criteria.py` → FAIL (`No module named 'research_agent.criteria'`).

- [ ] **Step 3: Implement** — `src/research_agent/criteria.py`

```python
"""Per-criterion screening decisions. Models answer each criterion; this code decides (no LLM here).

Inclusion criteria must all hold; any exclusion criterion drops the paper. Inclusion is checked first,
in the field's order, so `decided_by` is the first criterion that failed.
"""


def criterion_keys(criteria):
    return [c["key"] for c in criteria["include"]] + [c["key"] for c in criteria["exclude"]]


def _include(criteria):
    return [c["key"] for c in criteria["include"]]


def _exclude(criteria):
    return [c["key"] for c in criteria["exclude"]]


def decide_jev(probabilities, criteria, thresholds):
    """Jev probabilities -> (include | exclude | escalate, decided_by)."""
    for key in _include(criteria):
        if probabilities[key] <= thresholds["include_fail_max"]:
            return "exclude", key
    for key in _exclude(criteria):
        if probabilities[key] >= thresholds["exclude_hit_min"]:
            return "exclude", key
    if all(probabilities[k] >= thresholds["keep_min"] for k in _include(criteria)) and all(
        probabilities[k] <= thresholds["exclude_clear_max"] for k in _exclude(criteria)
    ):
        return "include", None
    return "escalate", None


def decide_llm(answers, criteria):
    """LLM answers {key: yes | no | unclear} -> (include | exclude | uncertain, decided_by)."""
    for key in _include(criteria):
        if answers[key] == "no":
            return "exclude", key
    for key in _exclude(criteria):
        if answers[key] == "yes":
            return "exclude", key
    if all(answers[k] == "yes" for k in _include(criteria)) and all(answers[k] == "no" for k in _exclude(criteria)):
        return "include", None
    return "uncertain", None


def screen_payload(domain, paper):
    """The LLM screen payload; shared by the pipeline and research-eval so cache keys match."""
    return {"topic": domain["topic"], "criteria": domain["criteria"], "paper": paper}


def satisfied(probabilities, criteria):
    """Probability that each criterion is *satisfied* (exclusion criteria inverted), for the eval sweep."""
    excluded = set(_exclude(criteria))
    return {k: round(1 - p, 12) if k in excluded else p for k, p in probabilities.items()}
```

Note: `1 - 0.3` is `0.7000000000000001`; `round(..., 12)` keeps the test exact.

- [ ] **Step 4: Run** `pytest -q tests/test_criteria.py` → `17 passed`; full `pytest -q`.

- [ ] **Step 5: Commit**

```bash
git add src/research_agent/criteria.py tests/test_criteria.py
git commit -m "Add per-criterion decision rules for Jev and the LLM screen" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 8: Jev asks one question per criterion

**Files:**
- Modify: `src/research_agent/jev.py`
- Modify: `tests/eval_helpers.py` (add `jev_criteria_client`)
- Create: `tests/test_jev_criteria.py`

- [ ] **Step 1: Add the mock and write the failing tests**

Append to `tests/eval_helpers.py`:

```python
def jev_criteria_client(probability):
    """Mock TypeSafe client answering every question in the request.
    `probability(index, key)` -> p, with index the N in the title 'Paper N title' (None if absent)."""
    calls = []

    def handler(request):
        body = json.loads(request.content)
        match = re.search(r"Paper (\d+) title", body["state"]["title"])
        index = int(match.group(1)) if match else None
        calls.append((index, sorted(body["questions"])))
        answers = {key: {"type": "noul", "noul": probability(index, key)} for key in body["questions"]}
        return httpx.Response(200, json={"model": "jev-1.13.0", "answers": answers})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    client.calls = calls
    return client
```

`tests/test_jev_criteria.py`:

```python
import json

import httpx
import pytest
from eval_helpers import jev_criteria_client

from research_agent.jev import JevError, JevScreener, criteria_questions
from research_agent.storage import MissingCall, Store

DOMAIN = {
    "topic": "deep learning CT-FFR",
    "criteria": {
        "include": [{"key": "i1", "text": "The study uses deep learning."}],
        "exclude": [{"key": "e1", "text": "The paper is a review."}],
    },
    "thresholds": {"keep_min": 0.8, "include_fail_max": 0.05, "exclude_hit_min": 0.95, "exclude_clear_max": 0.2},
}
PAPER = {"id": "MED:1", "title": "Paper 1 title", "abstract": "We trained a network.", "sources": ["europepmc"]}


def test_one_noul_question_per_criterion():
    questions = criteria_questions(DOMAIN)
    assert list(questions) == ["i1", "e1"]
    assert questions["e1"]["type"] == "noul"
    assert "Is this true of the paper? The paper is a review." in questions["e1"]["instructions"]
    assert "deep learning CT-FFR" in questions["i1"]["instructions"]
    assert set(questions["i1"]["criteria"]) == {"true", "false"}


def test_screen_criteria_decides_names_the_criterion_and_caches(tmp_path):
    store = Store(tmp_path)
    client = jev_criteria_client(lambda _i, key: {"i1": 0.9, "e1": 0.97}[key])
    jev = JevScreener(store, "k", client=client)
    verdict = jev.screen_criteria(PAPER, DOMAIN)
    assert verdict["decision"] == "exclude" and verdict["decided_by"] == "e1"
    assert verdict["probabilities"] == {"i1": 0.9, "e1": 0.97}
    assert verdict["model_version"] == "jev-1.13.0" and verdict["thresholds"] == DOMAIN["thresholds"]
    assert verdict["cached"] is False and client.calls == [(1, ["e1", "i1"])]
    again = jev.screen_criteria(PAPER, DOMAIN)
    assert again["cached"] is True and len(client.calls) == 1
    assert jev.cached_criteria_probabilities(PAPER, DOMAIN) == ({"i1": 0.9, "e1": 0.97}, "jev-1.13.0")


def test_state_is_evidence_only(tmp_path):
    bodies = []

    def handler(request):
        bodies.append(json.loads(request.content))
        answers = {k: {"type": "noul", "noul": 0.5} for k in bodies[-1]["questions"]}
        return httpx.Response(200, json={"model": "m", "answers": answers})

    JevScreener(Store(tmp_path), "k", client=httpx.Client(transport=httpx.MockTransport(handler))).screen_criteria(
        PAPER, DOMAIN
    )
    assert bodies[0]["state"] == {"title": PAPER["title"], "abstract": PAPER["abstract"]}


def test_missing_answer_for_a_criterion_fails_closed(tmp_path):
    def handler(request):
        return httpx.Response(200, json={"model": "m", "answers": {"i1": {"type": "noul", "noul": 0.9}}})

    jev = JevScreener(Store(tmp_path), "k", client=httpx.Client(transport=httpx.MockTransport(handler)))
    with pytest.raises(JevError):
        jev.screen_criteria(PAPER, DOMAIN)


def test_offline_lookup_raises_on_a_miss(tmp_path):
    with pytest.raises(MissingCall):
        JevScreener(Store(tmp_path), "offline").cached_criteria_probabilities(PAPER, DOMAIN)
```

- [ ] **Step 2: Run** `pytest -q tests/test_jev_criteria.py` → FAIL (`cannot import name 'criteria_questions'`).

- [ ] **Step 3: Implement** — in `jev.py` add `from .criteria import decide_jev` and:

```python
def criteria_questions(domain):
    """One Noul question per field criterion, keyed by the criterion key. Exclusion criteria use the same
    form: p is the probability that the exclusion applies."""
    questions = {}
    for kind in ("include", "exclude"):
        for criterion in domain["criteria"][kind]:
            questions[criterion["key"]] = {
                "type": "noul",
                "instructions": (
                    f"Research topic: {domain['topic']}. Is this true of the paper? {criterion['text']} "
                    "Judge only from the title and abstract in the state."
                ),
                "criteria": {
                    "true": "The title or abstract shows that the statement is true of the paper.",
                    "false": "The title and abstract show that it is false, or give no sign that it is true.",
                },
            }
    return questions
```

Refactor `JevScreener` (replace `_request`, `cached_probabilities`, `screen`; add the two new methods):

```python
    def _request(self, topic, paper, questions=None):
        # Evidence only: never a prior verdict or conclusion.
        state = {"title": paper["title"], "abstract": paper["abstract"]}
        questions = questions or self.criteria or default_criteria(topic)
        inputs = {"model": self.model, "state": state, "questions": questions}
        key = digest({"role": "jev_screen", "version": JEV_SCREEN_VERSION, "inputs": inputs})
        return key, inputs, questions

    def _cached(self, key, questions):
        raw = self.store.cached(key)
        if raw is None:
            raise MissingCall(f"jev_screen call not in cache ({key[:12]})")
        response = self._parse(raw, questions)
        return {q: response.answers[q].noul for q in questions}, response.model

    def _answers(self, key, inputs, questions):
        raw = self.store.cached(key)
        cached = raw is not None
        if not cached:
            raw = self._post(inputs)
        response = self._parse(raw, questions)
        if not cached:
            self.store.record(key, "jev_screen", self.model, JEV_SCREEN_VERSION, inputs, raw)
        return {q: response.answers[q].noul for q in questions}, response.model, cached

    def cached_probabilities(self, topic, paper):
        """Raw probabilities and API model version from the cache only; never calls the API."""
        key, _inputs, questions = self._request(topic, paper)
        return self._cached(key, questions)

    def cached_criteria_probabilities(self, paper, domain):
        key, _inputs, questions = self._request(domain["topic"], paper, criteria_questions(domain))
        return self._cached(key, questions)

    def screen(self, topic, paper):
        key, inputs, questions = self._request(topic, paper)
        probabilities, version, cached = self._answers(key, inputs, questions)
        return {
            "decision": self.decide(probabilities),
            "probabilities": probabilities,
            "model_version": version,
            "min_confidence": self.thresholds.min_confidence,
            "exclude_min_confidence": self.thresholds.exclude_min_confidence,
            "cached": cached,
        }

    def screen_criteria(self, paper, domain):
        """Per-criterion Jev screen of a field; thresholds come from the field (domain.json)."""
        key, inputs, questions = self._request(domain["topic"], paper, criteria_questions(domain))
        probabilities, version, cached = self._answers(key, inputs, questions)
        decision, decided_by = decide_jev(probabilities, domain["criteria"], domain["thresholds"])
        return {
            "decision": decision,
            "decided_by": decided_by,
            "probabilities": probabilities,
            "model_version": version,
            "thresholds": dict(domain["thresholds"]),
            "cached": cached,
        }
```

- [ ] **Step 4: Run** `pytest -q tests/test_jev_criteria.py tests/test_jev.py tests/test_legacy_screens.py`; full `pytest -q`.

- [ ] **Step 5: Commit**

```bash
git add src/research_agent/jev.py tests/eval_helpers.py tests/test_jev_criteria.py
git commit -m "Jev: one Noul question per field criterion, decided in code" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 9: LLM per-criterion screen with verified quotes; `PROMPT_VERSION` m1.2

**Files:**
- Modify: `src/research_agent/schemas.py` (`CriterionAnswer`, `CriteriaScreen`)
- Modify: `src/research_agent/agents.py`
- Create: `tests/test_screen_criteria.py`

- [ ] **Step 1: Write the failing tests** — `tests/test_screen_criteria.py`

```python
import pytest

from research_agent.agents import (
    PROMPT_VERSION,
    CriteriaAnswerError,
    EvidenceQuoteError,
    Evaluator,
    snap_screen,
)
from research_agent.criteria import screen_payload
from research_agent.schemas import CriteriaScreen, CriterionAnswer, Screen
from research_agent.storage import Store

ABSTRACT = "We review prior work on CT-FFR. No new patients were enrolled."
CRITERIA = {
    "include": [{"key": "i1", "text": "Reports original results."}],
    "exclude": [{"key": "e1", "text": "The paper is a review."}],
}
DOMAIN = {"topic": "CT-FFR", "criteria": CRITERIA}
PAPER = {"id": "MED:1", "title": "t", "abstract": ABSTRACT, "sources": ["europepmc"]}


def screen(*answers, reason="r"):
    return CriteriaScreen(answers=[CriterionAnswer(key=k, answer=a, quote=q) for k, a, q in answers], reason=reason)


def test_prompt_version_is_bumped():
    assert PROMPT_VERSION == "m1.2"


def test_quotes_snap_to_the_abstract_and_answers_follow_the_field_order():
    result = snap_screen(
        screen(("e1", "yes", "We review prior work on CT-FFR."), ("i1", "no", "No new patients were enrolled.")),
        CRITERIA,
        ABSTRACT,
    )
    assert [a.key for a in result.answers] == ["i1", "e1"]
    assert result.answers[1].quote == "We review prior work on CT-FFR."  # the abstract's own text
    assert all(a.quote in ABSTRACT for a in result.answers)


@pytest.mark.parametrize(
    "answers,error",
    [
        ((("i1", "yes", ""),), CriteriaAnswerError),  # e1 missing
        ((("i1", "yes", ""), ("e1", "no", ""), ("e2", "no", "")), CriteriaAnswerError),  # unknown key
        ((("i1", "yes", ""), ("i1", "yes", ""), ("e1", "no", "")), CriteriaAnswerError),  # duplicate
        ((("i1", "no", ""), ("e1", "no", "")), CriteriaAnswerError),  # 'no' on inclusion needs a quote
        ((("i1", "yes", ""), ("e1", "yes", " ")), CriteriaAnswerError),  # 'yes' on exclusion needs a quote
        ((("i1", "yes", ""), ("e1", "yes", "We summarise prior work.")), EvidenceQuoteError),  # mangled
        ((("i1", "yes", "Invented."), ("e1", "no", "")), EvidenceQuoteError),  # optional quotes are checked too
    ],
)
def test_bad_answers_are_refused(answers, error):
    with pytest.raises(error):
        snap_screen(screen(*answers), CRITERIA, ABSTRACT)


def test_demo_screen_answers_every_criterion_and_is_cached_under_the_new_role(tmp_path):
    store = Store(tmp_path)
    result = Evaluator(store).ask("screen_criteria", CriteriaScreen, screen_payload(DOMAIN, PAPER))
    assert [(a.key, a.answer, a.quote) for a in result.answers] == [("i1", "yes", ""), ("e1", "no", "")]
    with store.connect() as db:
        role, version, raw = db.execute("SELECT role, prompt_version, input FROM calls").fetchone()
    assert (role, version) == ("screen_criteria", "m1.2") and "sources" not in raw


def test_paper_sources_never_reach_a_model_or_a_cache_key(tmp_path):
    store = Store(tmp_path)
    first = Evaluator(store).ask("screen", Screen, {"topic": "t", "paper": PAPER})
    without = {k: v for k, v in PAPER.items() if k != "sources"}
    offline = Evaluator(store, offline=True)
    assert offline.ask("screen", Screen, {"topic": "t", "paper": without}) == first


def test_prompt_version_can_be_pinned_to_read_an_old_cache(tmp_path):
    store = Store(tmp_path)
    Evaluator(store, prompt_version="m1.1").ask("screen", Screen, {"topic": "t", "paper": PAPER})
    with store.connect() as db:
        assert db.execute("SELECT prompt_version FROM calls").fetchone()[0] == "m1.1"
    Evaluator(store, prompt_version="m1.1", offline=True).ask("screen", Screen, {"topic": "t", "paper": PAPER})


def test_screen_criteria_falls_back_to_the_screen_model():
    assert Evaluator(None, "live", {"screen": "anthropic:x"}).model_for("screen_criteria") == "anthropic:x"
    both = {"screen": "anthropic:x", "screen_criteria": "openai:y"}
    assert Evaluator(None, "live", both).model_for("screen_criteria") == "openai:y"


def test_live_screen_retries_a_mangled_quote_then_fails_closed(tmp_path, monkeypatch):
    import langchain.chat_models

    bad = screen(("i1", "yes", ""), ("e1", "yes", "We summarise prior work."))
    good = screen(("i1", "yes", ""), ("e1", "yes", "We review prior work on CT-FFR."))

    class Flaky:
        def __init__(self, outputs):
            self.outputs, self.calls = outputs, 0

        def with_structured_output(self, schema, method=None):
            return self

        def invoke(self, messages):
            self.calls += 1
            return self.outputs[min(self.calls, len(self.outputs)) - 1]

    def evaluator(directory, model):
        monkeypatch.setattr(langchain.chat_models, "init_chat_model", lambda *a, **k: model)
        return Evaluator(Store(directory), "live", {"screen": "test:model"})

    model = Flaky([bad, good])
    result = evaluator(tmp_path, model).ask("screen_criteria", CriteriaScreen, screen_payload(DOMAIN, PAPER))
    assert model.calls == 2 and result.answers[1].quote in ABSTRACT
    always_bad = Flaky([bad])
    with pytest.raises(EvidenceQuoteError):
        evaluator(tmp_path / "x", always_bad).ask("screen_criteria", CriteriaScreen, screen_payload(DOMAIN, PAPER))
    assert always_bad.calls == 3
```

- [ ] **Step 2: Run** `pytest -q tests/test_screen_criteria.py` → FAIL (`cannot import name 'CriteriaAnswerError'`).

- [ ] **Step 3: Implement**

In `schemas.py`, after `Screen`:

```python
class CriterionAnswer(Model):
    key: str
    answer: Literal["yes", "no", "unclear"]
    quote: str  # exact abstract text; required for 'no' on inclusion and 'yes' on exclusion, else ""


class CriteriaScreen(Model):
    answers: list[CriterionAnswer] = Field(min_length=1, max_length=20)
    reason: str
```

In `agents.py`:

```python
from .schemas import Claim, CriteriaScreen, CriterionAnswer, Decision, Evidence, Plan, Review, Screen

PROMPT_VERSION = "m1.2"  # m1.2: per-criterion screen (screen_criteria); older roles unchanged


class CriteriaAnswerError(ValueError):
    """The per-criterion screen does not answer each criterion exactly once, or omits a required quote."""
```

Add to `INSTRUCTIONS`:

```python
    "screen_criteria": (
        "Screen title and abstract against each criterion of the field. For every criterion key answer yes, "
        "no or unclear from the title and abstract only; missing or ambiguous evidence -> unclear. For every "
        "'no' on an inclusion criterion and every 'yes' on an exclusion criterion, quote the exact contiguous "
        "abstract text that shows it; otherwise give an empty quote. One answer per criterion key, then a short reason."
    ),
```

`Evaluator` changes:

```python
class Evaluator:
    def __init__(self, store, mode="demo", models=None, offline=False, prompt_version=PROMPT_VERSION):
        self.store = store
        self.mode = mode
        self.models = models or {}
        self.offline = offline
        self.prompt_version = prompt_version  # an old run's version reads that run's cache

    def model_for(self, role):
        if self.mode == "demo":
            return "synthetic-demo-v1"
        if role == "screen_criteria" and role not in self.models:
            role = "screen"
        return self.models[role]

    def ask(self, role, schema, payload):
        payload = without_sources(payload)
        model = self.model_for(role)
        inputs = {
            "system": SYSTEM,
            "instruction": INSTRUCTIONS[role],
            "payload": payload,
            "schema": schema.model_json_schema(),
        }
        key = digest({"model": model, "role": role, "version": self.prompt_version, "inputs": inputs})
        cached = self.store.cached(key)
        if cached is not None:
            return schema.model_validate(cached)
        if self.offline:
            raise MissingCall(f"{role} call not in cache ({key[:12]})")
        if self.mode == "demo":
            result = self._demo(role, payload)
        else:
            from langchain.chat_models import init_chat_model

            from .connectors import canonical_json

            llm = init_chat_model(model, timeout=60, max_retries=2, max_tokens=2500)
            # Native constrained decoding: schema-valid by construction (forced tool calling drifted on
            # nested fields, and is unsupported on some newer Claude models).
            structured = llm.with_structured_output(schema, method="json_schema")
            messages = [("system", SYSTEM + "\n" + INSTRUCTIONS[role]), ("human", canonical_json(payload))]
            for attempt in range(SCHEMA_ATTEMPTS):
                try:
                    # A quote the model mangled (e.g. "(49)" for "(31%)") is a bad generation, not a
                    # matching bug: regenerate. Only quotes validated against the abstract are accepted.
                    result = checked(role, schema.model_validate(_dump(structured.invoke(messages))), payload)
                    break
                except (ValidationError, OutputParserException, EvidenceQuoteError, CriteriaAnswerError):
                    # langchain-anthropic raises OutputParserException for a schema mismatch or truncated JSON;
                    # tool-calling models occasionally emit a nested field as a JSON string.
                    # Retry the identical request; still fail closed once attempts run out.
                    if attempt == SCHEMA_ATTEMPTS - 1:
                        raise
        result = checked(role, schema.model_validate(_dump(result)), payload)
        if role == "extract":
            validate_evidence(result, payload["paper"]["abstract"])
        self.store.record(key, role, model, self.prompt_version, inputs, result.model_dump())
        return result
```

`_demo` gains (before the `extract` branch):

```python
        if role == "screen_criteria":
            answers = [
                CriterionAnswer(key=c["key"], answer="yes" if kind == "include" else "no", quote="")
                for kind in ("include", "exclude")
                for c in payload["criteria"][kind]
            ]
            return CriteriaScreen(answers=answers, reason="Synthetic demo routing only.")
```

New module-level helpers (replace `snap_evidence`):

```python
def without_sources(payload):
    """Which connectors found a paper is provenance, not evidence: it never reaches a model or a cache key."""
    paper = payload.get("paper") if isinstance(payload, dict) else None
    if isinstance(paper, dict) and "sources" in paper:
        return {**payload, "paper": {k: v for k, v in paper.items() if k != "sources"}}
    return payload


def checked(role, result, payload):
    if role == "extract":
        return snap_evidence(result, payload["paper"]["abstract"])
    if role == "screen_criteria":
        return snap_screen(result, payload["criteria"], payload["paper"]["abstract"])
    return result


def snap_quote(quote, abstract):
    """Models often normalise typography (thin space, NBSP). Match modulo whitespace/Unicode form, then
    return the abstract's own text so every quote stays an exact substring of the source."""
    folded, starts, ends = _fold(abstract)
    needle = _fold(quote.strip())[0]
    start = folded.find(needle) if needle else -1
    if start < 0:
        raise EvidenceQuoteError("Evidence quote is not an exact span in the retrieved abstract")
    return abstract[starts[start] : ends[start + len(needle) - 1]]


def snap_evidence(evidence, abstract):
    claims = [claim.model_copy(update={"quote": snap_quote(claim.quote, abstract)}) for claim in evidence.claims]
    return evidence.model_copy(update={"claims": claims})


def snap_screen(screen, criteria, abstract):
    """Each criterion answered exactly once (in the field's order); every non-empty quote snapped to the
    abstract; a quote is required for 'no' on an inclusion criterion and 'yes' on an exclusion criterion."""
    kinds = {c["key"]: kind for kind in ("include", "exclude") for c in criteria[kind]}
    answers = {a.key: a for a in screen.answers}
    if len(answers) != len(screen.answers) or set(answers) != set(kinds):
        raise CriteriaAnswerError("the screen must answer each criterion key exactly once")
    ordered = []
    for key, kind in kinds.items():
        answer = answers[key]
        required = (kind == "include" and answer.answer == "no") or (kind == "exclude" and answer.answer == "yes")
        if required and not answer.quote.strip():
            raise CriteriaAnswerError(f"criterion {key}: this answer needs a quote from the abstract")
        quote = snap_quote(answer.quote, abstract) if answer.quote.strip() else ""
        ordered.append(answer.model_copy(update={"quote": quote}))
    return screen.model_copy(update={"answers": ordered})
```

- [ ] **Step 4: Run** `pytest -q tests/test_screen_criteria.py tests/test_pipeline.py tests/test_eval_*.py tests/test_legacy_screens.py`; full `pytest -q`.

- [ ] **Step 5: Commit**

```bash
git add src/research_agent/schemas.py src/research_agent/agents.py tests/test_screen_criteria.py
git commit -m "LLM per-criterion screen with verified quotes; prompt version m1.2, pinnable for old caches" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 10: Graph screens per criterion; `criteria` and `decided_by` in report.json

**Files:**
- Modify: `src/research_agent/graph.py`
- Modify: `src/research_agent/report.py`
- Modify: `tests/test_screen_criteria.py`

- [ ] **Step 1: Write the failing tests** — append to `tests/test_screen_criteria.py`

```python
import json

from eval_helpers import europepmc, jev_criteria_client, row

from research_agent.connectors import DemoConnector, EuropePMC
from research_agent.graph import build_graph
from research_agent.jev import JevScreener
from research_agent.report import write_report
from research_agent.schemas import Contract, DomainSpec

FIELD = DomainSpec.model_validate(
    {
        "schema": 1,
        "field": {"id": "f1", "name": "ML CT-FFR", "version": 2},
        "topic": "deep learning CT-FFR",
        "criteria": {
            "include": [{"key": "i1", "text": "Uses deep learning."}],
            "exclude": [{"key": "e1", "text": "Is a review."}],
        },
        "sources": [{"name": "europepmc"}],
    }
)


class QuotingEvaluator(Evaluator):
    """Demo evaluator whose criteria screen drops MED:6 by e1 and is unsure about MED:7."""

    def _demo(self, role, payload):
        if role == "screen_criteria" and payload["paper"]["id"] == "MED:6":
            return screen(("i1", "yes", ""), ("e1", "yes", "Abstract 6 on the topic."), reason="a review")
        if role == "screen_criteria" and payload["paper"]["id"] == "MED:7":
            return screen(("i1", "unclear", ""), ("e1", "no", ""), reason="unclear")
        return super()._demo(role, payload)


def field_run(tmp_path):
    store = Store(tmp_path)
    rows = [row(i) for i in range(1, 8)] + [row(8, abstract="")]
    probabilities = {1: (0.9, 0.1), 2: (0.01, 0.1), 3: (0.9, 0.99), 4: (0.5, 0.5), 6: (0.5, 0.5), 7: (0.5, 0.5)}
    jev = JevScreener(
        store,
        "k",
        client=jev_criteria_client(lambda i, key: probabilities.get(i, (0.5, 0.5))[0 if key == "i1" else 1]),
    )
    contract = Contract(topic=FIELD.topic, domain=FIELD).model_dump()
    graph = build_graph(EuropePMC(store, europepmc({"*": rows})), QuotingEvaluator(store), jev=jev)
    return graph.invoke({"contract": contract})


def test_field_run_screens_per_criterion_and_names_the_decider(tmp_path):
    screens = field_run(tmp_path)["screens"]
    assert screens["MED:1"]["decision"] == "include" and screens["MED:1"]["tier"] == "jev"
    assert screens["MED:1"]["decided_by"] is None
    assert screens["MED:1"]["criteria"] == {
        "i1": {"jev_p": 0.9, "llm": None, "quote": None},
        "e1": {"jev_p": 0.1, "llm": None, "quote": None},
    }
    assert (screens["MED:2"]["decision"], screens["MED:2"]["decided_by"]) == ("exclude", "i1")
    assert screens["MED:2"]["reason"] == "Jev: i1 p=0.01, e1 p=0.10 (jev-1.13.0); dropped by i1"
    assert (screens["MED:3"]["decision"], screens["MED:3"]["decided_by"]) == ("exclude", "e1")
    assert screens["MED:4"]["tier"] == "llm" and screens["MED:4"]["decision"] == "include"
    assert screens["MED:4"]["jev"]["decision"] == "escalate"
    assert screens["MED:4"]["criteria"]["i1"] == {"jev_p": 0.5, "llm": "yes", "quote": None}
    assert screens["MED:6"]["decision"] == "exclude" and screens["MED:6"]["decided_by"] == "e1"
    assert screens["MED:6"]["criteria"]["e1"] == {"jev_p": 0.5, "llm": "yes", "quote": "Abstract 6 on the topic."}
    assert screens["MED:6"]["reason"] == "a review"
    assert screens["MED:7"]["decision"] == "uncertain" and screens["MED:7"]["decided_by"] is None
    assert screens["MED:8"] == {
        "decision": "uncertain",
        "reason": "No abstract available; retained in audit, unranked.",
        "tier": "rule",
        "decided_by": None,
        "criteria": {k: {"jev_p": None, "llm": None, "quote": None} for k in ("i1", "e1")},
    }


def test_field_run_report_json_is_a_superset_of_todays_shape(tmp_path):
    result = field_run(tmp_path)
    write_report(result, tmp_path, {"models": {"all": "synthetic-demo-v1"}})
    state = json.loads((tmp_path / "report.json").read_text())["state"]
    assert state["contract"]["domain"]["field"] == {"id": "f1", "name": "ML CT-FFR", "version": 2}
    assert state["papers"][0]["sources"] == ["europepmc"]
    for screen_entry in state["screens"].values():
        assert {"decision", "reason", "tier", "decided_by", "criteria"} <= set(screen_entry)
    markdown = (tmp_path / "report.md").read_text()
    assert "Field: ML CT-FFR · version 2" in markdown and "Found by: europepmc" in markdown


def test_legacy_screens_gain_topic_match_cells(tmp_path):
    store = Store(tmp_path)
    contract = Contract(topic="retrieval augmented generation", max_papers=2).model_dump()
    screens = build_graph(DemoConnector(store), Evaluator(store)).invoke({"contract": contract})["screens"]
    assert screens["demo:1"]["criteria"] == {} and screens["demo:1"]["decided_by"] is None


def test_plan_payload_is_unchanged_for_legacy_runs_and_gets_the_criteria_for_fields(tmp_path):
    seen = []

    class Recording(Evaluator):
        def ask(self, role, schema, payload):
            if role == "plan":
                seen.append(payload)
            return super().ask(role, schema, payload)

    store = Store(tmp_path)
    legacy = Contract(topic="retrieval augmented generation", max_papers=1).model_dump()
    build_graph(DemoConnector(store), Recording(store), interrupt_after=["plan"]).invoke({"contract": legacy})
    field = Contract(topic=FIELD.topic, domain=FIELD, max_papers=1).model_dump()
    build_graph(DemoConnector(store), Recording(store), interrupt_after=["plan"]).invoke({"contract": field})
    assert "domain" not in seen[0] and seen[0]["topic"] == "retrieval augmented generation"
    assert seen[1]["criteria"] == FIELD.model_dump()["criteria"] and seen[1]["years"] == {"from": None, "to": None}
    assert "domain" not in seen[1]
```

Also add to `tests/test_legacy_screens.py` (Jev legacy cells):

```python
def test_legacy_jev_screens_record_topic_match_and_the_decider(tmp_path):
    screens = jev_run(tmp_path)["screens"]
    assert screens["MED:2"]["criteria"] == {"topic_match": {"jev_p": 0.01, "llm": None, "quote": None}}
    assert screens["MED:2"]["decided_by"] == "topic_match"
    assert screens["MED:3"]["decided_by"] == "topic_match"  # the LLM excluded it
    assert screens["MED:1"]["decided_by"] is None and screens["MED:9"]["criteria"] == {}
```

- [ ] **Step 2: Run** → FAIL (`KeyError: 'decided_by'` / `'criteria'`).

- [ ] **Step 3: Implement** — `graph.py`:

```python
from .agents import validate_evidence
from .connectors import deduplicate
from .criteria import criterion_keys, decide_llm, screen_payload
from .schemas import CriteriaScreen, Decision, Evidence, Paper, Plan, Review, Screen

NO_ABSTRACT = "No abstract available; retained in audit, unranked."


def plan_payload(contract):
    """Legacy runs send exactly today's payload; a field adds its criteria and year range."""
    payload = {k: v for k, v in contract.items() if k != "domain"}
    if contract.get("domain"):
        payload["criteria"] = contract["domain"]["criteria"]
        payload["years"] = contract["domain"]["years"]
    return payload
```

Inside `build_graph`, `plan` becomes `return {"plan": evaluator.ask("plan", Plan, plan_payload(s["contract"])).model_dump()}` and `screen` is replaced by:

```python
    def screen_topic(topic, paper):
        # Tier 1 (optional): Jev decides only when confident; otherwise the LLM sees the same
        # payload as without Jev (evidence, never Jev's conclusion).
        verdict = jev.screen(topic, paper) if jev else None
        if verdict and verdict["decision"] != "escalate":
            entry = {
                "decision": verdict["decision"],
                "reason": "Jev: "
                + ", ".join(f"{q} p={p:.2f}" for q, p in verdict["probabilities"].items())
                + f" ({verdict['model_version']})",
                "tier": "jev",
            }
        else:
            entry = {
                **evaluator.ask("screen", Screen, {"topic": topic, "paper": paper}).model_dump(),
                "tier": "llm",
            }
        if verdict:
            entry["jev"] = verdict
        entry["decided_by"] = "topic_match" if entry["decision"] == "exclude" else None
        entry["criteria"] = {
            q: {"jev_p": p, "llm": None, "quote": None} for q, p in (verdict or {}).get("probabilities", {}).items()
        }
        return entry

    def screen_criteria(domain, paper):
        cells = {k: {"jev_p": None, "llm": None, "quote": None} for k in criterion_keys(domain["criteria"])}
        verdict = jev.screen_criteria(paper, domain) if jev else None
        for key, p in (verdict or {}).get("probabilities", {}).items():
            cells[key]["jev_p"] = p
        if verdict and verdict["decision"] != "escalate":
            dropped = f"; dropped by {verdict['decided_by']}" if verdict["decided_by"] else ""
            entry = {
                "decision": verdict["decision"],
                "reason": "Jev: "
                + ", ".join(f"{k} p={p:.2f}" for k, p in verdict["probabilities"].items())
                + f" ({verdict['model_version']}){dropped}",
                "tier": "jev",
                "decided_by": verdict["decided_by"],
            }
        else:
            answer = evaluator.ask("screen_criteria", CriteriaScreen, screen_payload(domain, paper))
            for a in answer.answers:
                cells[a.key]["llm"], cells[a.key]["quote"] = a.answer, a.quote or None
            decision, decided_by = decide_llm({a.key: a.answer for a in answer.answers}, domain["criteria"])
            entry = {"decision": decision, "reason": answer.reason, "tier": "llm", "decided_by": decided_by}
        entry["criteria"] = cells
        if verdict:
            entry["jev"] = verdict
        return entry

    def screen(s):
        topic, domain, results = s["contract"]["topic"], s["contract"].get("domain"), {}
        for paper in s["papers"]:
            if not paper["abstract"]:
                keys = criterion_keys(domain["criteria"]) if domain else []
                results[paper["id"]] = {
                    **Screen(decision="uncertain", reason=NO_ABSTRACT).model_dump(),
                    "tier": "rule",
                    "decided_by": None,
                    "criteria": {k: {"jev_p": None, "llm": None, "quote": None} for k in keys},
                }
            elif domain:
                results[paper["id"]] = screen_criteria(domain, paper)
            else:
                results[paper["id"]] = screen_topic(topic, paper)
        return {"screens": results}
```

(The `jev` key follows `criteria` in field entries; key order in `MED:8` equality does not matter for dicts.)

`report.py`: after the `f"Topic: …"` line pair insert

```python
        *(
            [f"Field: {field['name']} · version {field['version']}", ""]
            if (field := (state["contract"].get("domain") or {}).get("field"))
            else []
        ),
```

and in the per-paper block, before `"**Evidence and provenance**"` lines, add `f"Found by: {', '.join(p.get('sources') or []) or 'not recorded'}",` followed by `""`.

- [ ] **Step 4: Run** `pytest -q tests/test_screen_criteria.py tests/test_legacy_screens.py tests/test_pipeline.py tests/test_jev.py`; full `pytest -q` (web importer tests read report.json; only keys were added).

- [ ] **Step 5: Commit**

```bash
git add src/research_agent/graph.py src/research_agent/report.py tests/test_screen_criteria.py tests/test_legacy_screens.py
git commit -m "Screen per criterion in field runs; report.json screens gain criteria and decided_by" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 11: Runner and CLI take `--domain FILE`; English failure messages

**Files:**
- Modify: `src/research_agent/runner.py`
- Modify: `src/research_agent/cli.py`
- Create: `tests/test_domain_run.py`

- [ ] **Step 1: Write the failing tests** — `tests/test_domain_run.py`

```python
import hashlib
import json
import sys

import pytest

from research_agent import cli, runner
from research_agent.connectors import SourceUnavailable
from research_agent.runner import run_research
from research_agent.schemas import Contract, read_domain

DOMAIN = {
    "schema": 1,
    "field": {"id": "f1", "name": "ML CT-FFR", "version": 3},
    "topic": "deep learning CT-FFR",
    "criteria": {
        "include": [{"key": "i1", "text": "Uses deep learning."}],
        "exclude": [{"key": "e1", "text": "Is a review."}],
    },
    "sources": [{"name": "europepmc", "max_results": 5}, {"name": "arxiv", "max_results": 5}],
    "years": {"from": 2018, "to": None},
}


def write_domain(tmp_path, data=DOMAIN):
    path = tmp_path / "field.json"
    path.write_text(json.dumps(data, indent=1))
    return path


def test_demo_field_run_copies_domain_json_and_records_it(tmp_path):
    source = write_domain(tmp_path)
    spec = read_domain(source)
    run = tmp_path / "run"
    run_research(run, Contract(topic=spec.topic, domain=spec, max_papers=3), domain_file=source)
    assert (run / "domain.json").read_bytes() == source.read_bytes()
    manifest = json.loads((run / "manifest.json").read_text())
    assert manifest["domain"] == {
        "file": "domain.json",
        "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "field": {"id": "f1", "name": "ML CT-FFR", "version": 3},
    }
    assert manifest["prompt_version"] == "m1.2"
    report = json.loads((run / "report.json").read_text())
    assert report["manifest"]["contract"]["domain"]["years"] == {"from": 2018, "to": None}
    papers = report["state"]["papers"]
    assert len(papers) == 3 and all(p["sources"] == ["arxiv", "europepmc"] for p in papers)
    assert all(s["decided_by"] is None and set(s["criteria"]) == {"i1", "e1"} for s in report["state"]["screens"].values())


def test_a_field_run_resumes_from_its_saved_contract(tmp_path):
    spec = read_domain(write_domain(tmp_path))
    run = tmp_path / "run"
    assert run_research(run, Contract(topic=spec.topic, domain=spec, max_papers=2), stop_after="discover") is None
    result = run_research(run, resume=True)
    assert result["contract"]["domain"]["field"]["version"] == 3 and len(result["ranking"]) == 2


def test_legacy_manifest_has_no_domain(tmp_path):
    run_research(tmp_path / "run", Contract(topic="retrieval augmented generation", max_papers=1))
    assert json.loads((tmp_path / "run" / "manifest.json").read_text())["domain"] is None


def test_source_failure_is_recorded_with_the_source_name(tmp_path, monkeypatch):
    class Down:
        def search(self, query, limit):
            raise SourceUnavailable("openalex")

    monkeypatch.setattr(runner, "make_connector", lambda contract, store: Down())
    spec = read_domain(write_domain(tmp_path))
    with pytest.raises(SourceUnavailable):
        run_research(tmp_path / "run", Contract(topic=spec.topic, domain=spec))
    progress = json.loads((tmp_path / "run" / "progress.json").read_text())
    assert progress["status"] == "failed" and progress["stages"]["discover"] == "failed"
    assert (progress["error_type"], progress["message"]) == ("SourceUnavailable", "openalex")


def test_other_failures_get_the_generic_english_message(tmp_path, monkeypatch):
    class Broken:
        def search(self, query, limit):
            raise RuntimeError("provider said sk-secret")

    monkeypatch.setattr(runner, "make_connector", lambda contract, store: Broken())
    with pytest.raises(RuntimeError):
        run_research(tmp_path / "run", Contract(topic="retrieval augmented generation"))
    progress = json.loads((tmp_path / "run" / "progress.json").read_text())
    assert progress["message"].startswith("The stage did not finish.") and "sk-secret" not in progress["message"]


@pytest.mark.parametrize(
    "call,message",
    [
        (lambda run: run_research(run, resume=True), "There is no saved research in this folder."),
        (
            lambda run: (
                run_research(run, Contract(topic="retrieval augmented generation", max_papers=1)),
                run_research(run, Contract(topic="retrieval augmented generation", max_papers=1)),
            ),
            "This research already exists; resume it or choose a new folder.",
        ),
    ],
)
def test_runner_messages_are_english(tmp_path, call, message):
    with pytest.raises(ValueError, match=message):
        call(tmp_path / "run")


def run_cli(monkeypatch, *argv):
    monkeypatch.setattr(sys, "argv", ["research-agent", *argv])
    monkeypatch.setattr(cli, "load_dotenv", lambda: None)
    cli.main()


def test_cli_runs_a_field_in_demo_mode(tmp_path, monkeypatch, capsys):
    source = write_domain(tmp_path)
    run_cli(monkeypatch, "--domain", str(source), "--run-dir", str(tmp_path / "run"), "--max-papers", "2")
    assert "Report:" in capsys.readouterr().out
    assert (tmp_path / "run" / "domain.json").exists()


@pytest.mark.parametrize(
    "extra,message",
    [
        (["a topic"], "either a topic or --domain"),
        (["--resume"], "do not pass --domain"),
        (["--jev-min-confidence", "0.7"], "thresholds come from domain.json"),
    ],
)
def test_cli_refuses_domain_combinations(tmp_path, monkeypatch, capsys, extra, message):
    source = write_domain(tmp_path)
    with pytest.raises(SystemExit) as exited:
        run_cli(monkeypatch, "--domain", str(source), "--run-dir", str(tmp_path / "run"), *extra)
    assert exited.value.code == 2 and message in capsys.readouterr().err


def test_cli_reports_an_invalid_domain_file(tmp_path, monkeypatch, capsys):
    source = write_domain(tmp_path, {**DOMAIN, "sources": []})
    with pytest.raises(SystemExit) as exited:
        run_cli(monkeypatch, "--domain", str(source), "--run-dir", str(tmp_path / "run"))
    assert exited.value.code == 2
    assert "domain.json is invalid: sources: List should have at least 1 item" in capsys.readouterr().err


def test_cli_still_requires_a_topic_or_a_domain(tmp_path, monkeypatch, capsys):
    with pytest.raises(SystemExit):
        run_cli(monkeypatch, "--run-dir", str(tmp_path / "run"))
    assert "Topic or --domain is required" in capsys.readouterr().err
```

- [ ] **Step 2: Run** `pytest -q tests/test_domain_run.py` → FAIL (`unexpected keyword argument 'domain_file'`).

- [ ] **Step 3: Implement**

`runner.py` imports: `import hashlib`, `import shutil`, `from .connectors import DemoConnector, EuropePMC, SourceUnavailable, domain_connector`. Add:

```python
FAILED = (
    "The stage did not finish. Check source access, the key and the configured model, then resume the run. "
    "The checkpoint is kept."
)


def make_connector(contract, store):
    if contract.domain is not None:
        return domain_connector(contract.domain, store, contract.mode)
    return DemoConnector(store) if contract.mode == "demo" else EuropePMC(store)


def copy_domain(path, contract, domain_file):
    """domain.json in the run folder is the exact file the run was started with (or the validated spec)."""
    target = Path(path) / "domain.json"
    if domain_file is not None:
        shutil.copyfile(domain_file, target)
    else:
        target.write_text(json.dumps(contract.domain.model_dump(), ensure_ascii=False, indent=2))
    field = contract.domain.field
    return {
        "file": "domain.json",
        "sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
        "field": field.model_dump() if field else None,
    }
```

Messages: `RunLocked("This research is already running.")`; `"There is no saved research in this folder."`; `"The prompt version changed; start a new research run."`; `"The topic cannot be changed when resuming."`; `"This research already exists; resume it or choose a new folder."`.

`run_research(path, contract=None, models=None, resume=False, stop_after=None, on_event=None, domain_file=None)`. In the new-run branch, after `contract = Contract.model_validate(contract)`, and in the manifest dict add `"domain": copy_domain(path, contract, domain_file) if contract.domain else None,` (evaluate before `atomic_json`). Replace the connector line with `connector = make_connector(contract, store)`. The failure handler:

```python
        except Exception as exc:
            # No raw provider exception: it can contain credentials or request bodies. A source failure
            # names only the source.
            progress.write(
                status="failed",
                error_type=type(exc).__name__,
                message=exc.source if isinstance(exc, SourceUnavailable) else FAILED,
            )
            raise
```

`cli.py`:

```python
import argparse
from pathlib import Path

from dotenv import load_dotenv

from .runner import RunLocked, run_research
from .schemas import Contract, DomainError, read_domain

EXIT_LOCKED = 75  # os.EX_TEMPFAIL: another process is running this folder; try again later


def main():
    parser = argparse.ArgumentParser(description="Abstract-level research pipeline; demo is synthetic.")
    parser.add_argument("topic", nargs="?")
    parser.add_argument("--domain", type=Path, help="field definition (domain.json) instead of a topic")
    parser.add_argument("--mode", choices=["demo", "live"], default="demo")
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--max-papers", type=int, default=12)
    parser.add_argument("--jev", action="store_true", help="Jev classifier as screening tier 1 (live only)")
    parser.add_argument("--jev-min-confidence", type=float, default=None, help="auto-include threshold (0.6)")
    parser.add_argument(
        "--jev-exclude-min-confidence", type=float, default=None, help="auto-exclude threshold (0.9, stricter)"
    )
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--stop-after", choices=["discover", "extract", "adjudicate"])
    args = parser.parse_args()
    load_dotenv()
    if args.domain and args.topic:
        parser.error("Give either a topic or --domain, not both")
    if args.domain and args.resume:
        parser.error("--resume reads the saved run; do not pass --domain")
    if args.domain and (args.jev_min_confidence is not None or args.jev_exclude_min_confidence is not None):
        parser.error("With --domain the Jev thresholds come from domain.json")
    if not args.resume and not (args.topic or args.domain):
        parser.error("Topic or --domain is required for a new run")
    domain = None
    if args.domain:
        try:
            domain = read_domain(args.domain)
        except DomainError as exc:
            parser.error(str(exc))
    contract = (
        Contract(
            topic=domain.topic if domain else args.topic,
            domain=domain,
            mode=args.mode,
            max_papers=args.max_papers,
            jev=args.jev,
            jev_min_confidence=0.6 if args.jev_min_confidence is None else args.jev_min_confidence,
            jev_exclude_min_confidence=0.9
            if args.jev_exclude_min_confidence is None
            else args.jev_exclude_min_confidence,
        )
        if args.topic or domain
        else None
    )
    try:
        result = run_research(
            args.run_dir,
            contract=contract,
            resume=args.resume,
            stop_after=args.stop_after,
            on_event=lambda event: print("Completed:", ", ".join(event), flush=True),
            domain_file=args.domain,
        )
    except RunLocked:
        parser.exit(
            EXIT_LOCKED, "This research is already running in this folder; try again when it finishes.\n"
        )
    except Exception as exc:  # noqa: BLE001 -- CLI boundary deliberately sanitizes provider errors.
        parser.exit(
            1, f"Research stopped ({type(exc).__name__}). Check configuration and resume the saved run.\n"
        )
    print(
        f"Report: {args.run_dir / 'report.md'}" if result is not None else "Checkpoint saved. Use --resume."
    )
```

- [ ] **Step 4: Run** `pytest -q tests/test_domain_run.py tests/test_ui.py tests/test_pipeline.py tests/test_web_runner.py`; full `pytest -q`.

- [ ] **Step 5: Commit**

```bash
git add src/research_agent/runner.py src/research_agent/cli.py tests/test_domain_run.py
git commit -m "Run a field with --domain FILE: domain.json copied and recorded, English runner messages" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 12: English failure messages in `jobs.py` and `ui.py`

**Files:**
- Modify: `src/research_agent/jobs.py`, `src/research_agent/ui.py`
- Modify: `tests/test_ui.py`

- [ ] **Step 1: Write the failing test** — append to `tests/test_ui.py`

```python
def test_failure_messages_are_english(tmp_path, monkeypatch):
    import research_agent.jobs as jobs_module

    run = tmp_path / "run"
    with pytest.raises(ValueError, match="There is no checkpoint to resume."):
        jobs_module.launch(run, resume=True)

    class Done:
        def poll(self):
            return 1

    monkeypatch.setitem(jobs_module.PROCESSES, str((tmp_path / "gone").resolve()), Done())
    assert jobs_module.status(tmp_path / "gone")["message"].startswith("The run could not start.")
    source = (Path(jobs_module.__file__).parent / "ui.py").read_text()
    for romanian in ("Introdu un subiect", "Lipsește cheia", "nu a putut porni", "Nu se poate relua"):
        assert romanian not in source
```

(add `from pathlib import Path` and `import pytest` to the test module imports if missing.)

- [ ] **Step 2: Run** `pytest -q tests/test_ui.py::test_failure_messages_are_english` → FAIL.

- [ ] **Step 3: Implement**

`jobs.py`: `"This research is already running."`, `"There is no checkpoint to resume."`, status failure message `"The run could not start. Check the models and the configuration, then try again."`.

`ui.py` replacements (only failure messages; the rest of the Streamlit UI stays as it is):

| Line (today) | New text |
|---|---|
| `"Introdu un subiect de cel puțin 3 caractere."` | `"Enter a topic of at least 3 characters."` |
| `"Completează modelul principal."` | `"Fill in the main model."` |
| `"Interfața V1 acceptă modelele openai:ID și anthropic:ID."` | `"This interface accepts openai:ID and anthropic:ID models."` |
| `f"Lipsește cheia pentru {provider}."` | `f"The key for {provider} is missing."` |
| `f"Cercetarea nu a putut porni ({type(exc).__name__})."` | `f"The research could not start ({type(exc).__name__})."` |
| `"Tip eroare: "` | `"Error type: "` |
| `"Nu se poate relua acum; verifică dacă cercetarea rulează deja."` | `"Cannot resume now; check whether the research is already running."` |

- [ ] **Step 4: Run** `pytest -q tests/test_ui.py`; full `pytest -q`.

- [ ] **Step 5: Commit**

```bash
git add src/research_agent/jobs.py src/research_agent/ui.py tests/test_ui.py
git commit -m "English failure messages in the local launcher and the Streamlit UI" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 13: `research-eval screen --field domain.json`; reports read per-criterion runs and old caches

**Files:**
- Modify: `src/research_agent/eval/screen.py`, `src/research_agent/eval/report.py`, `src/research_agent/eval/cli.py`
- Create: `tests/test_eval_field.py`

- [ ] **Step 1: Write the failing tests** — `tests/test_eval_field.py`

```python
import json

import pytest
from eval_helpers import StubEvaluator, jev_client, jev_criteria_client, make_gold

from research_agent.agents import Evaluator
from research_agent.eval import cli
from research_agent.eval.gold import write_gold
from research_agent.eval.report import build_report
from research_agent.eval.screen import run_screen, write_manifest
from research_agent.jev import JevScreener
from research_agent.storage import Store

DOMAIN = {
    "schema": 1,
    "field": {"id": "f1", "name": "ML CT-FFR", "version": 1},
    "topic": "deep learning CT-FFR",
    "criteria": {
        "include": [{"key": "i1", "text": "Uses deep learning."}],
        "exclude": [{"key": "e1", "text": "Is a review."}],
    },
    "sources": [{"name": "europepmc"}],
}
# Positives 1-4 satisfy i1 and are not reviews; 5 is a review; 6 fails i1; others are unsure.
P = {1: (0.97, 0.02), 2: (0.95, 0.1), 3: (0.9, 0.05), 4: (0.6, 0.1), 5: (0.9, 0.99), 6: (0.01, 0.1)}


def probability(index, key):
    return P.get(index, (0.5, 0.5))[0 if key == "i1" else 1]


def test_cli_screens_and_reports_a_field(tmp_path, monkeypatch, capsys):
    gold, run, field = tmp_path / "toy.json", tmp_path / "run", tmp_path / "field.json"
    write_gold(make_gold(n=8), gold)
    field.write_text(json.dumps(DOMAIN))
    client = jev_criteria_client(probability)
    monkeypatch.setattr(cli, "make_jev", lambda store: JevScreener(store, "k", client=client))
    args = ["screen", str(gold), "--run-dir", str(run), "--mode", "demo", "--field", str(field)]
    assert cli.main(args, dotenv=False) == 0
    assert len(client.calls) == 8 and all(keys == ["e1", "i1"] for _i, keys in client.calls)
    manifest = json.loads((run / "manifest.json").read_text())
    assert manifest["field"]["field"]["name"] == "ML CT-FFR" and len(manifest["field_sha256"]) == 64
    assert cli.main(["report", str(run)], dotenv=False) == 0
    report = json.loads((run / "metrics.json").read_text())
    assert report["counts"]["screened"] == 8 and report["run"]["field"] == DOMAIN["field"]
    assert "Screened 8 candidates" in capsys.readouterr().out


def test_a_run_dir_refuses_a_different_field(tmp_path, monkeypatch):
    gold, run, field = tmp_path / "toy.json", tmp_path / "run", tmp_path / "field.json"
    write_gold(make_gold(n=2), gold)
    field.write_text(json.dumps(DOMAIN))
    monkeypatch.setattr(
        cli, "make_jev", lambda store: JevScreener(store, "k", client=jev_criteria_client(probability))
    )
    base = ["screen", str(gold), "--run-dir", str(run), "--mode", "demo"]
    assert cli.main([*base, "--field", str(field)], dotenv=False) == 0
    changed = {**DOMAIN, "topic": "another field topic"}
    field.write_text(json.dumps(changed))
    assert cli.main([*base, "--field", str(field)], dotenv=False) == 1
    assert "different field" in (run / "errors.log").read_text()


def test_report_reads_a_run_screened_under_an_older_prompt_version(tmp_path):
    gold_path, run = tmp_path / "toy.json", tmp_path / "run"
    gold = write_gold(make_gold(n=6), gold_path)
    store = Store(run)
    old = StubEvaluator(store, exclude={"MED:5"}, prompt_version="m1.1")
    jev = JevScreener(store, "k", client=jev_client({1: 0.97, 2: 0.9, 3: 0.02}))
    screened = run_screen(gold, store, old, jev)
    write_manifest(run, gold_path=gold_path, gold=gold, mode="demo", models={}, jev_model="jev-latest", screened=screened)
    manifest = json.loads((run / "manifest.json").read_text())
    manifest["prompt_version"] = "m1.1"
    (run / "manifest.json").write_text(json.dumps(manifest))
    report = build_report(run)
    assert report["counts"]["screened"] == 6 and report["run"]["prompt_version"] == "m1.1"
    with pytest.raises(Exception, match="missing cached calls"):
        manifest["prompt_version"] = "m1.2"
        (run / "manifest.json").write_text(json.dumps(manifest))
        build_report(run)


def test_legacy_eval_manifest_has_no_field(tmp_path):
    gold_path, run = tmp_path / "toy.json", tmp_path / "run"
    gold = write_gold(make_gold(n=2), gold_path)
    store = Store(run)
    screened = run_screen(gold, store, Evaluator(store), JevScreener(store, "k", client=jev_client({})))
    data = write_manifest(run, gold_path=gold_path, gold=gold, mode="demo", models={}, jev_model="m", screened=screened)
    assert data["field"] is None and data["field_sha256"] is None
```

- [ ] **Step 2: Run** `pytest -q tests/test_eval_field.py` → FAIL (`unrecognized arguments: --field`).

- [ ] **Step 3: Implement**

`eval/screen.py`:

```python
"""Run Jev and the LLM screen over every gold candidate. Results live in the calls cache."""

import json
from pathlib import Path

from ..agents import PROMPT_VERSION
from ..connectors import digest
from ..criteria import screen_payload
from ..jev import JEV_SCREEN_VERSION
from ..schemas import CriteriaScreen, Screen
from .gold import gold_paper

MANIFEST = "manifest.json"


def run_screen(gold, store, evaluator, jev, progress=None, domain=None):
    """Both tiers on every candidate with an abstract (not only the escalated ones), so `report` can
    replay the cascade at any threshold pair offline. Errors propagate; the cache makes re-runs resume.
    With `domain` (a field, as a dict) both tiers screen per criterion and the field's topic is used."""
    versions, done = set(), 0
    for candidate in gold.candidates:
        if not candidate.abstract:
            continue
        paper = gold_paper(candidate, gold).model_dump()
        if domain:
            verdict = jev.screen_criteria(paper, domain)
            evaluator.ask("screen_criteria", CriteriaScreen, screen_payload(domain, paper))
        else:
            verdict = jev.screen(gold.topic, paper)
            evaluator.ask("screen", Screen, {"topic": gold.topic, "paper": paper})
        versions.add(verdict["model_version"])
        done += 1
        if progress:
            progress(done)
    return {"screened": done, "jev_model_versions": sorted(versions)}


def field_sha256(domain):
    return digest(domain) if domain else None


def check_run_dir(run_dir, gold, domain=None):
    """One run dir holds one gold set and one field: a resume is fine, anything else is refused."""
    path = Path(run_dir) / MANIFEST
    if not path.exists():
        return
    manifest = json.loads(path.read_text())
    if manifest.get("gold_sha256") != gold.content_sha256:
        raise ValueError("run dir already holds a run for a different gold set; use a new --run-dir")
    if manifest.get("field_sha256") != field_sha256(domain):
        raise ValueError("run dir already holds a run for a different field; use a new --run-dir")


def write_manifest(run_dir, *, gold_path, gold, mode, models, jev_model, screened, domain=None):
    check_run_dir(run_dir, gold, domain)
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
        "field": domain,
        "field_sha256": field_sha256(domain),
        **screened,
    }
    temporary = run_dir / (MANIFEST + ".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2))
    temporary.replace(run_dir / MANIFEST)
    return data
```

(`read_manifest` unchanged.)

`eval/cli.py` `cmd_screen`:

```python
def cmd_screen(args):
    gold = load_gold(args.gold)
    domain = read_domain(args.field).model_dump() if args.field else None
    check_run_dir(args.run_dir, gold, domain)  # before any API call
    store = Store(args.run_dir)
    evaluator, jev = make_evaluator(store, args.mode), make_jev(store)

    def progress(n):
        if n % 25 == 0:
            print(f"screened {n}", flush=True)

    result = run_screen(gold, store, evaluator, jev, progress, domain)
    write_manifest(
        args.run_dir,
        gold_path=args.gold,
        gold=gold,
        mode=args.mode,
        models=evaluator.models,
        jev_model=jev.model,
        screened=result,
        domain=domain,
    )
    print(
        f"Screened {result['screened']} candidates · Jev {result['jev_model_versions']} · run: {args.run_dir}"
    )
    return 0
```

with `from ..schemas import read_domain` and, in `build_parser` for `screen`:
`p.add_argument("--field", help="screen with a field's criteria (a domain.json file)")`.

`eval/report.py`: imports `from ..criteria import decide_llm, satisfied, screen_payload` and `from ..schemas import CriteriaScreen, Screen`. `load_records(gold, store, evaluator, jev, allow_mixed=False, domain=None)`; inside the `try`:

```python
        try:
            if domain:
                # Per-criterion run: replay the two-threshold sweep on "criterion satisfied" probabilities
                # (exclusion inverted); the LLM decision is the code's decision over its answers.
                raw, version = jev.cached_criteria_probabilities(paper, domain)
                probabilities = satisfied(raw, domain["criteria"])
                answer = evaluator.ask("screen_criteria", CriteriaScreen, screen_payload(domain, paper))
                llm = decide_llm({a.key: a.answer for a in answer.answers}, domain["criteria"])[0]
            else:
                probabilities, version = jev.cached_probabilities(gold.topic, paper)
                llm = evaluator.ask("screen", Screen, {"topic": gold.topic, "paper": paper}).decision
        except MissingCall:
```

`_load_run`: `evaluator = Evaluator(store, manifest["mode"], manifest["models"], offline=True, prompt_version=manifest["prompt_version"])` and `load_records(gold, store, evaluator, jev, allow_mixed, manifest.get("field"))`. In `build_report`, `"run"` gains `"field": (manifest.get("field") or {}).get("field"),`.

`StubEvaluator.__init__(self, store, exclude=(), **kwargs)` already forwards `prompt_version`.

- [ ] **Step 4: Run** `pytest -q tests/test_eval_field.py tests/test_eval_*.py tests/test_web_import_eval.py`; full `pytest -q`.

- [ ] **Step 5: Commit**

```bash
git add src/research_agent/eval/screen.py src/research_agent/eval/report.py src/research_agent/eval/cli.py tests/test_eval_field.py
git commit -m "research-eval screen --field: per-criterion eval runs; reports read the run's own prompt version" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 14: README usage

**Files:**
- Modify: `README.md` (Romanian, like the rest of the file)

- [ ] **Step 1:** After the "Căutare și evaluare live" section add:

````markdown
## Câmpuri (domain.json)

Un câmp = topic + criterii de includere (toate trebuie să fie adevărate) și excludere (oricare elimină
lucrarea) + surse (Europe PMC, OpenAlex, arXiv) + interval de ani + praguri Jev. Aplicația web scrie
`domain.json`; din linia de comandă:

```bash
research-agent --domain field.json --mode demo --run-dir runs/field-demo
research-eval screen gold/toy.json --run-dir runs/eval-field --field field.json
```

`domain.json` se copiază în directorul run-ului și apare în `manifest.json`. În `report.json`, fiecare
screen are `criteria` (per criteriu: `jev_p`, răspunsul LLM `yes|no|unclear`, citatul verificat) și
`decided_by` (criteriul care a eliminat lucrarea sau `null`); fiecare lucrare are `sources`.
Run-urile cu topic pozițional rămân neschimbate (o singură întrebare `topic_match`).
````

- [ ] **Step 2:** `ruff format src tests && ruff check . && pytest -q` → green.

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "Document field runs (domain.json) in the README" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Resulting data shapes (for the backend plan)

`report.json → state.papers[*]` gains `sources: ["europepmc" | "openalex" | "arxiv" | "demo", …]` (sorted, deduplicated).

`report.json → state.screens[paper_id]` (field run):

```json
{
  "decision": "include | exclude | uncertain",
  "reason": "…",
  "tier": "jev | llm | rule",
  "decided_by": "i1 | e1 | null",
  "criteria": {"i1": {"jev_p": 0.93, "llm": "yes | no | unclear | null", "quote": "exact abstract text | null"}},
  "jev": {"decision": "include | exclude | escalate", "decided_by": "…|null", "probabilities": {"i1": 0.93},
          "model_version": "jev-…", "thresholds": {"keep_min": 0.8, "…": 0}, "cached": false}
}
```

Legacy run: same keys; `criteria` is `{"topic_match": {"jev_p": p, "llm": null, "quote": null}}` or `{}`; `decided_by` is `"topic_match"` on exclude, else `null`; `jev` keeps today's shape (`min_confidence`, `exclude_min_confidence`).

`manifest.json` (research run): `domain: null | {"file": "domain.json", "sha256": "…", "field": {"id","name","version"} | null}`; `contract.domain`: the validated `domain.json` (keys `schema`, `field`, `topic`, `criteria`, `sources`, `years{from,to}`, `thresholds`, and `contact: null` filled in on sources without one).

The LLM call for a per-criterion screen is recorded under role `screen_criteria` (not `screen`).

## Self-review

- Spec coverage: DomainSpec + validation (T2), `--domain` + legacy topic (T11), year filter (T3), OpenAlex (T4), arXiv (T5), cache/retries/fail closed (T3–T5), `sources` + multi-source dedup (T6), per-criterion Jev + thresholds (T7–T8), per-criterion LLM with snap/retry (T9), `criteria`/`decided_by` (T10), PROMPT_VERSION (T9), English messages (T11–T12), `research-eval --field` (T13), legacy identical decisions (T1, re-run in every task). Connection checks, criteria-test jobs and key checks belong to the backend plan.
- Placeholders: none; every code step has the code.
- Names: `screen_criteria` (Jev method and LLM role), `decide_jev`/`decide_llm`, `screen_payload`, `criterion_keys`, `satisfied`, `snap_quote`/`snap_screen`, `SourceUnavailable.source`, `domain_connector`, `MultiSource.sources`, `read_domain`/`DomainError`, `Years.start/end` (aliases `from`/`to`), `DomainSpec.schema_version` (alias `schema`) — used consistently across tasks.
