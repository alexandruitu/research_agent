import re

import pytest

from research_agent.panel import DEFAULT_EDITOR, DEFAULT_PANEL, default_panel, default_review
from research_agent.schemas import ReviewSpec


def test_default_panel_has_three_roles_with_tagged_items():
    assert [r["key"] for r in DEFAULT_PANEL] == ["methodologist", "clinician", "statistician"]
    for reviewer in DEFAULT_PANEL:
        assert 8 <= len(reviewer["items"]) <= 12
        for item in reviewer["items"]:
            assert re.fullmatch(r"(CLAIM 2020 #\d+|TRIPOD\+AI \d+[a-z]?)", item["source"])
            assert 1 <= item["weight"] <= 3


def test_red_flags_cover_leakage_split_and_external_validation():
    flagged = " ".join(i["text"].lower() for r in DEFAULT_PANEL for i in r["items"] if i.get("red_flag_if"))
    assert "patient level" in flagged and "external" in flagged and "test set" in flagged


def test_default_review_validates_and_is_a_fresh_copy():
    spec = ReviewSpec.model_validate(default_review(contact="a@b.org"))
    assert spec.fulltext.sources == ["pmc_oa", "unpaywall", "upload"]
    assert ReviewSpec.model_validate(default_review()).fulltext.sources == ["pmc_oa", "upload"]
    default_panel()[0]["items"].clear()
    assert DEFAULT_PANEL[0]["items"] and DEFAULT_EDITOR["model"] is None


def test_every_default_item_has_a_problem_phrasing():
    for reviewer in DEFAULT_PANEL:
        for item in reviewer["items"]:
            assert 3 <= len(item["flag_text"]) <= 200 and item["flag_text"] != item["text"]


def test_review_spec_accepts_flag_text_and_old_files():
    from research_agent.schemas import ChecklistItem

    assert ChecklistItem.model_validate({"key": "a", "text": "abc"}).flag_text is None
    assert ChecklistItem.model_validate({"key": "a", "text": "abc", "flag_text": "Bad"}).flag_text == "Bad"
    with pytest.raises(ValueError):
        ChecklistItem.model_validate({"key": "a", "text": "abc", "flag_text": "x" * 201})
