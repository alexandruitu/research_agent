import pytest

from research_agent.querybuild import (
    QueryError,
    build,
    build_queries,
    check_override,
    clean_term,
    has_terms,
    normalize_keywords,
)

CATS = "(cat:cs.CV OR cat:eess.IV OR cat:physics.med-ph)"

CASES = [
    ("europepmc", {"all": ["CT"]}, "TITLE_ABS:CT"),
    (
        "europepmc",
        {
            "all": ["coronary angiography", "deep learning"],
            "any": ["segment*", "U-Net"],
            "none": ["review"],
        },
        (
            'TITLE_ABS:"coronary angiography" AND TITLE_ABS:"deep learning" AND '
            '(TITLE_ABS:segment* OR TITLE_ABS:"U-Net") NOT TITLE_ABS:review'
        ),
    ),
    ("europepmc", {"any": ["CT", "MRI"]}, "(TITLE_ABS:CT OR TITLE_ABS:MRI)"),
    (
        "openalex",
        {"all": ["deep learning"], "any": ["CT", "MRI"], "none": ["review", "case report"]},
        '"deep learning" AND (CT OR MRI) NOT (review OR "case report")',
    ),
    ("openalex", {"all": ["segment*"]}, "segment"),
    (
        "arxiv",
        {"all": ["deep learning"], "any": ["CT"], "none": ["survey"]},
        f'abs:"deep learning" AND abs:CT AND {CATS} ANDNOT abs:survey',
    ),
    ("arxiv", {"any": ["CT", "MR imaging"]}, f'(abs:CT OR abs:"MR imaging") AND {CATS}'),
]


@pytest.mark.parametrize("source,keywords,expected", CASES)
def test_build_per_source(source, keywords, expected):
    assert build(source, keywords) == expected


@pytest.mark.parametrize(
    "term,wildcard,expected",
    [
        ('x" OR 1:(y)', False, "x OR 1 y"),
        ("  deep   learning ", False, "deep learning"),
        ("segment*", True, "segment*"),
        ("segment*", False, "segment"),
        ("deep learn*", True, "deep learn"),
        ("a*b", True, "a b"),
        ("CT/MR", False, "CT MR"),
        ('"()"', False, ""),
        ("ﬁbrosis", False, "fibrosis"),  # NFKC folds the ligature
    ],
)
def test_clean_term(term, wildcard, expected):
    assert clean_term(term, wildcard) == expected


def test_operator_words_and_punctuated_terms_are_quoted():
    assert (
        build("openalex", {"all": ["AND", "or", "x-ray", "Crohn's"]})
        == '"AND" AND "or" AND "x-ray" AND "Crohn\'s"'
    )


def test_duplicates_and_empty_terms_are_dropped():
    assert build("openalex", {"all": ["CT", "ct", " ", "()"], "any": ["MRI", "mri"]}) == "CT AND MRI"


def test_none_only_or_nothing_is_an_error():
    with pytest.raises(QueryError, match="All of"):
        build("europepmc", {"none": ["review"]})
    with pytest.raises(QueryError):
        build("arxiv", {})


def test_too_long_is_an_error():
    with pytest.raises(QueryError, match="too long"):
        build(
            "europepmc",
            {
                "all": [f"t{i} " + "x" * 70 for i in range(20)],
                "any": [f"a{i} " + "y" * 70 for i in range(20)],
            },
        )


def test_unknown_source():
    with pytest.raises(ValueError):
        build("scholar", {"all": ["x"]})


def test_normalize_keywords():
    assert normalize_keywords(None) is None
    assert normalize_keywords({"all": [" ", ""], "any": [], "none": []}) is None
    assert normalize_keywords({"all": [" deep  learning", "Deep learning"], "none": ["review*"]}) == {
        "all": ["deep learning"],
        "any": [],
        "none": ["review*"],
    }
    assert has_terms({"all": [], "any": ["x"], "none": []})
    assert not has_terms({"all": [], "any": [], "none": ["x"]})
    assert not has_terms(None)


def test_build_queries_with_overrides():
    keywords = {"all": ["CT"], "any": [], "none": []}
    queries = build_queries(keywords, ["europepmc", "openalex"], {"openalex": "  custom  ", "arxiv": "x"})
    assert queries == {"europepmc": "TITLE_ABS:CT", "openalex": "custom"}
    # without keywords only overridden sources get a query (the others are planned as before)
    assert build_queries(None, ["europepmc", "arxiv"], {"arxiv": "abs:x", "europepmc": " "}) == {
        "arxiv": "abs:x"
    }
    assert build_queries(None, ["europepmc"], None) == {}


def test_check_override():
    assert check_override("europepmc", "  TITLE_ABS:x ") == "TITLE_ABS:x"
    with pytest.raises(QueryError, match="comma"):
        check_override("openalex", "a, b")
    with pytest.raises(QueryError):
        check_override("arxiv", "x" * 2001)
    with pytest.raises(QueryError):
        check_override("arxiv", "a\nb")


KW = {"all": ["deep learning"], "any": ["CT", "MRI*"], "none": ["mouse"]}
NEW = [
    ("pubmed", '"deep learning"[tiab] AND (CT[tiab] OR MRI*[tiab]) NOT mouse[tiab]'),
    ("medrxiv", 'TITLE_ABS:"deep learning" AND (TITLE_ABS:CT OR TITLE_ABS:MRI*) NOT TITLE_ABS:mouse'),
    ("biorxiv", 'TITLE_ABS:"deep learning" AND (TITLE_ABS:CT OR TITLE_ABS:MRI*) NOT TITLE_ABS:mouse'),
    ("semantic_scholar", "deep learning CT MRI"),
    ("crossref", "deep learning CT MRI"),
    ("core", '"deep learning" AND (CT OR MRI) AND NOT mouse'),
    ("ieee", '"deep learning" AND (CT OR MRI) NOT mouse'),
    ("springer", '"deep learning" AND (CT OR MRI) NOT mouse'),
    (
        "scopus",
        (
            'TITLE-ABS-KEY("deep learning") AND (TITLE-ABS-KEY(CT) OR TITLE-ABS-KEY(MRI*)) '
            "AND NOT TITLE-ABS-KEY(mouse)"
        ),
    ),
]


@pytest.mark.parametrize("source,expected", NEW)
def test_build_new_sources(source, expected):
    assert build(source, KW) == expected


def test_plain_sources_need_all_or_any_terms():
    with pytest.raises(QueryError):
        build("semantic_scholar", {"none": ["x"]})


@pytest.mark.parametrize(
    "text,expected",
    [
        ("Deep  learning for CT of the chest", True),
        ("deep learning for MRIs", True),  # MRI* is a prefix
        ("deep learning for PET", False),  # no `any` term
        ("CT without the method", False),  # no `all` term
        ("deep learning CT in a mouse model", False),  # a `none` term
        ("deeplearning for CT", False),  # whole words only
    ],
)
def test_matches_requires_all_any_and_no_none(text, expected):
    from research_agent.querybuild import matches

    assert matches(KW, text) is expected


def test_matches_without_any_group_and_with_syntax_characters():
    from research_agent.querybuild import matches

    assert matches({"all": ["U-Net"]}, "a u net model")
    assert matches({}, "anything")


def test_overrides_work_for_new_sources():
    assert build_queries(KW, ["pubmed", "scopus"], {"scopus": "TITLE(x)"}) == {
        "pubmed": NEW[0][1],
        "scopus": "TITLE(x)",
    }
