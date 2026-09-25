import pytest
from eval_helpers import europepmc, row

from research_agent.connectors import EuropePMC
from research_agent.eval.gold import SRSpec, StudyRef
from research_agent.eval.resolve import GoldBuildError, build_gold, lookup_query, matches
from research_agent.schemas import Paper, Source
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


def alpha_rows(query):
    """Pool holds a DOI-less record; the DOI lookup returns the same paper under another id."""
    if query.startswith("DOI:"):
        return [row(9, title="Alpha Study", doi="10.1000/z")]
    return [row(1, title="Alpha Study", doi="")]


def test_lookup_hit_that_duplicates_a_pool_record_yields_one_candidate(tmp_path):
    gold = build(tmp_path, alpha_rows, StudyRef(doi="10.1000/z"))
    assert len(gold.candidates) == 1
    only = gold.candidates[0]
    assert (only.label, only.via) == ("include", "query")


def test_two_sr_entries_for_one_paper_yield_one_positive(tmp_path):
    gold = build(tmp_path, alpha_rows, StudyRef(doi="10.1000/z"), StudyRef(title="Alpha Study"))
    assert [c.label for c in gold.candidates] == ["include"]


def paper(title="T", doi="", year="2024"):
    source = Source(connector="t", record_id="MED:1", url="u", query="q", retrieved_at="now", raw_sha256="x")
    return Paper(id="MED:1", title=title, abstract="", doi=doi, year=year, provenance=[source])


def test_conflicting_dois_never_match_even_with_same_title():
    assert not matches(StudyRef(doi="10.1/a", title="Same"), paper(title="Same", doi="10.1/b"))


def test_doi_only_ref_does_not_match_paper_without_doi():
    assert not matches(StudyRef(doi="10.1/a"), paper(title="Same"))


def test_title_match_respects_year():
    assert not matches(StudyRef(title="T", year="2023"), paper(year="2024"))
    assert matches(StudyRef(title="T"), paper(year="2024"))


def test_title_normalization_is_unicode_aware():
    composed, decomposed = "caf\u00e9 study", "cafe\u0301 study"
    assert matches(StudyRef(title=composed), paper(title=decomposed))


def test_punctuation_only_titles_never_match():
    assert not matches(StudyRef(title="!!!"), paper(title="???"))


def test_lookup_query_strips_quotes_and_backslashes_from_titles():
    assert lookup_query(StudyRef(title='A "B" C\\')) == 'TITLE:"A  B  C "'
