import pytest
from test_eval_panel import run

from research_agent.eval.panel_eval import load_panel_eval
from research_agent.eval.panel_report import SINGLE_FAMILY_NOTE, build_panel_metrics, families, provider


def metrics(tmp_path, n=6):
    _data, eval_dir, _e = run(tmp_path, n=n)
    return build_panel_metrics(*load_panel_eval(eval_dir))


def test_panel_metrics_agreement_items_coverage(tmp_path):
    m = metrics(tmp_path)
    assert m["n"] == 6 and m["reviewers"] == ["methodologist", "statistician"]
    # The stub's statistician always flips the verdict: raw agreement 0, kappa -1 (both classes present).
    assert m["verdicts"]["fleiss"]["agreement"] == 0
    assert m["verdicts"]["pairwise"]["methodologist|statistician"]["kappa"] == pytest.approx(-1.0)
    shared = next(r for r in m["items"] if len(r["items"]) == 2)
    assert shared["share"]["value"] == 1.0 and shared["kappa"]["kappa"] == pytest.approx(1.0)
    own = next(r for r in m["items"] if r["items"] == [{"reviewer": "statistician", "item": "s1"}])
    assert own["reason"] == "single answerer: agreement undefined"
    assert own["unanswered_share"] == 1.0 and own["reword_candidate"] is True
    assert m["items"][0]["share"]["value"] == 1.0  # defined agreement ranks before undefined
    cov = m["coverage"]["methodologist"]["m1"]
    assert cov["fulltext"]["n"] == 1 and cov["abstract"]["n"] == 5 and cov["abstract"]["value"] == 1.0
    assert m["coverage"]["statistician"]["s1"]["abstract"]["value"] == 0.0
    assert m["text_sources"] == {"abstract": 5, "pmc_oa": 1}


def test_panel_metrics_dispersion_auc_and_single_family(tmp_path):
    m = metrics(tmp_path)
    # Both stub reviewers score 100 (included) or 0 (excluded) on their answered items: no spread.
    assert [r["range"] for r in m["dispersion"]] == [0] * 6 and m["dispersion"][0]["n"] == 2
    assert m["sr_inclusion_auc"]["value"] == 1.0 and m["sr_inclusion_auc"]["method"] == "hanley-mcneil"
    assert m["sr_inclusion_auc"]["n_pos"] == 3 and "not study quality" in m["sr_inclusion_auc"]["note"]
    fam = m["model_families"]
    assert fam["single_family"] is True and fam["families"] == {"single": "demo"}
    assert fam["note"] == SINGLE_FAMILY_NOTE


def test_families_split_when_two_providers():
    papers = {
        f"p{i}": {"reviews": {k: {"verdict": v} for k, v in zip("abc", verdicts, strict=True)}}
        for i, verdicts in enumerate([("include", "include", "exclude"), ("exclude", "exclude", "include")])
    }
    manifest = {
        "panel": [
            {"key": "a", "model": "anthropic:x"},
            {"key": "b", "model": "claude-y"},
            {"key": "c", "model": "openai:z"},
        ]
    }
    out = families(papers, sorted(papers), manifest)
    assert out["single_family"] is False
    assert out["families"]["anthropic"]["pairwise"]["a|b"]["kappa"] == pytest.approx(1.0)
    assert out["families"]["openai"]["fleiss"] is None
    assert out["between"]["anthropic|openai"]["a|c"]["kappa"] == pytest.approx(-1.0)


@pytest.mark.parametrize(
    "model, name",
    [
        ("anthropic:claude-x", "anthropic"),
        ("gpt-5", "openai"),
        ("synthetic-demo-v1", "demo"),
        (None, "unknown"),
    ],
)
def test_provider(model, name):
    assert provider(model) == name
