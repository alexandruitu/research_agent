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
    verdict = JevScreener.from_env(Store(tmp_path)).screen(
        "deep learning CT-derived fractional flow reserve", paper
    )
    assert verdict["decision"] in {"include", "exclude", "escalate"}
    assert all(0 <= p <= 1 for p in verdict["probabilities"].values())
