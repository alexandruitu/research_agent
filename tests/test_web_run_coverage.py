"""Run coverage: what a run searched, skipped, capped and read, in one object on RunOut."""

from sqlalchemy import select

from research_agent import runner
from research_agent.connectors import DemoConnector, MultiSource, SourceUnavailable
from research_agent.runner import run_research
from research_agent.schemas import Contract, DomainSpec
from research_agent.web.api.routers.runs import _run_out, run_coverage
from research_agent.web.api.schemas import RunOut
from research_agent.web.db.models import PaperReview, Run, Screening
from research_agent.web.importer.research import import_research_run

DOMAIN = {
    "schema": 1,
    "topic": "deep learning CT-FFR",
    "criteria": {"include": [{"key": "i1", "text": "Uses deep learning."}], "exclude": []},
    "sources": [{"name": "europepmc", "max_results": 5}, {"name": "semantic_scholar", "max_results": 5}],
}


class Down:
    name = "semantic_scholar"

    def search(self, query, limit, raw=False):
        raise SourceUnavailable("semantic_scholar", reason="rate limited (HTTP 429)")


def _imported(db, tmp_path, monkeypatch):
    spec = DomainSpec.model_validate(DOMAIN)
    monkeypatch.setattr(
        runner,
        "make_connector",
        lambda c, store: MultiSource([(DemoConnector(store, source="europepmc"), 5), (Down(), 5)]),
    )
    folder = tmp_path / "run"
    run_research(folder, Contract(topic=spec.topic, domain=spec, max_papers=3))
    return db.get(Run, import_research_run(db, folder).run_id)


def test_a_run_says_what_it_searched_skipped_and_capped(db, tmp_path, monkeypatch):
    run = _imported(db, tmp_path, monkeypatch)
    coverage = _run_out(db, run, RunOut, names={}).coverage
    assert coverage.searched == ["europepmc"]
    assert [w.source for w in coverage.skipped] == ["semantic_scholar"]
    assert coverage.max_papers == 3
    # no panel review: the text counts are unknown, not zero
    assert coverage.full_text is None and coverage.abstract_only is None


def test_text_counts_come_from_the_panel_reviews(db, tmp_path, monkeypatch):
    run = _imported(db, tmp_path, monkeypatch)
    papers = db.scalars(select(Screening.paper_id).where(Screening.run_id == run.id)).all()
    assert len(papers) >= 2
    for paper_id, source in zip(papers, ["abstract", "pmc_oa"], strict=False):
        db.add(PaperReview(run_id=run.id, paper_id=paper_id, text_source=source))
    db.flush()
    coverage = run_coverage(db, run)
    assert (coverage["full_text"], coverage["abstract_only"]) == (1, 1)


def test_a_legacy_run_records_no_search(db, tmp_path):
    folder = tmp_path / "run"
    run_research(folder, Contract(topic="retrieval augmented generation", max_papers=1))
    run = db.get(Run, import_research_run(db, folder).run_id)
    coverage = run_coverage(db, run)
    assert coverage["skipped"] is None and coverage["max_papers"] == 1
