import json

import pytest
from pydantic import ValidationError

from research_agent.schemas import Contract, ReviewError, ReviewSpec, read_review

REVIEW = {
    "schema": 1,
    "panel": [
        {
            "key": "methodologist",
            "name": "Methodologist",
            "version": 2,
            "perspective": "Study design, data splits and leakage.",
            "model": "anthropic:claude-sonnet-5",
            "items": [
                {"key": "m1", "text": "Data were split at patient level.", "weight": 2, "red_flag_if": "no"}
            ],
        }
    ],
    "editor": {"model": "anthropic:claude-opus-5-5", "instructions": "Be fair."},
    "models": {"plan": "openai:gpt-6"},
    "screening": {
        "keep_min": 0.8,
        "include_fail_max": 0.05,
        "exclude_hit_min": 0.95,
        "exclude_clear_max": 0.2,
    },
    "fulltext": {"sources": ["pmc_oa", "unpaywall", "upload"], "contact": "a@b.org", "max_chars": 60000},
}


def reviewer(key, items=None):
    return {**REVIEW["panel"][0], "key": key, "items": items or REVIEW["panel"][0]["items"]}


def test_the_spec_example_validates_and_dumps_with_aliases():
    spec = ReviewSpec.model_validate(REVIEW)
    assert spec.panel[0].items[0].pass_if == "yes" and spec.panel[0].items[0].weight == 2
    assert spec.model_dump()["schema"] == 1


def test_defaults_minimal_file():
    spec = ReviewSpec.model_validate({"schema": 1, "panel": [reviewer("clinician")]})
    assert spec.editor.model is None and spec.screening is None
    assert spec.fulltext.sources == ["pmc_oa", "upload"] and spec.fulltext.max_chars == 60000


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"extra": 1}, "Extra inputs are not permitted"),
        ({"panel": []}, "at least 1 item"),
        ({"panel": [reviewer(f"r{i}x") for i in range(6)]}, "at most 5 items"),
        ({"panel": [reviewer("same"), reviewer("same")]}, "reviewer keys must be unique"),
        ({"panel": [reviewer("Bad Key")]}, "String should match pattern"),
        (
            {"panel": [reviewer("dup", [{"key": "a1", "text": "One."}, {"key": "a1", "text": "Two."}])]},
            "item keys must be unique",
        ),
        ({"panel": [reviewer("w", [{"key": "a1", "text": "One.", "weight": 4}])]}, "less than or equal to 3"),
        ({"fulltext": {"sources": ["unpaywall"]}}, "fulltext.contact is required when unpaywall is a source"),
        ({"fulltext": {"sources": ["upload", "upload"]}}, "each full-text source may be listed once"),
        ({"models": {"review_a": "x"}}, "Extra inputs are not permitted"),
    ],
)
def test_invalid_specs_are_refused(change, message):
    with pytest.raises(ValidationError, match=message):
        ReviewSpec.model_validate({**REVIEW, **change})


def test_read_review_reports_every_problem(tmp_path):
    path = tmp_path / "review.json"
    path.write_text(json.dumps({**REVIEW, "panel": [], "fulltext": {"max_chars": 10}}))
    with pytest.raises(ReviewError) as exc:
        read_review(path)
    assert str(exc.value).startswith("review.json is invalid: panel: ")
    assert "fulltext.max_chars" in str(exc.value)
    path.write_text("{")
    with pytest.raises(ReviewError, match="is not valid JSON"):
        read_review(path)
    with pytest.raises(ReviewError, match="cannot read"):
        read_review(tmp_path / "missing.json")


def test_contract_carries_the_review():
    contract = Contract(topic="deep learning CT-FFR", review=ReviewSpec.model_validate(REVIEW))
    assert contract.model_dump()["review"]["panel"][0]["key"] == "methodologist"
    assert Contract(topic="deep learning CT-FFR").review is None
