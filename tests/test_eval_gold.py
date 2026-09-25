import json

import pytest
from pydantic import ValidationError

from research_agent.eval.gold import (
    GoldCandidate,
    GoldIntegrityError,
    GoldSet,
    SRSpec,
    StudyRef,
    UnmatchedStudy,
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
    with pytest.raises(ValidationError):
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


@pytest.mark.parametrize("name", [".", "..", ".hidden", "-x", ""])
def test_sr_name_must_be_a_safe_file_stem(name):
    with pytest.raises(ValidationError):
        SRSpec(name=name, citation="T", topic="topic", query="query", included=[StudyRef(doi="10.1/a")])


def test_study_ref_strips_whitespace():
    assert StudyRef(doi="  10.1/a  ").doi == "10.1/a"
    with pytest.raises(ValueError):
        StudyRef(doi="  ", title=" ")


def test_future_version_is_an_integrity_error_not_a_validation_error(tmp_path):
    path = tmp_path / "toy.json"
    write_gold(gold(), path)
    data = json.loads(path.read_text())
    data["version"] = 2
    data["candidates"][0]["new_in_v2"] = 1
    path.write_text(json.dumps(data))
    with pytest.raises(GoldIntegrityError, match="unsupported gold version"):
        load_gold(path)


@pytest.mark.parametrize("field", ["unresolved", "ambiguous"])
def test_hash_covers_unresolved_and_ambiguous(tmp_path, field):
    g = gold().model_copy(update={field: [UnmatchedStudy(reference=StudyRef(doi="10.1/x"))]})
    path = tmp_path / "toy.json"
    write_gold(g, path)
    data = json.loads(path.read_text())
    data[field][0]["reference"]["doi"] = "10.1/y"
    path.write_text(json.dumps(data))
    with pytest.raises(GoldIntegrityError):
        load_gold(path)
