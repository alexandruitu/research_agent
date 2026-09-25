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
            GoldCandidate(
                id="MED:1", doi="10.1/a", title="A", abstract="Abstract A.", year="2024", label="include"
            ),
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
        'query: \'"fractional flow reserve" AND "deep learning"\'\n'
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
