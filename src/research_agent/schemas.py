import json
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_serializer, model_validator


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


EMAIL = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"


# Search sources a field may use (research_agent.sources.REGISTRY describes each one).
SEARCH_SOURCES = (
    "europepmc",
    "openalex",
    "arxiv",
    "semantic_scholar",
    "crossref",
    "pubmed",
    "medrxiv",
    "biorxiv",
    "core",
    "ieee",
    "springer",
    "scopus",
)
SourceName = Literal[
    "europepmc",
    "openalex",
    "arxiv",
    "semantic_scholar",
    "crossref",
    "pubmed",
    "medrxiv",
    "biorxiv",
    "core",
    "ieee",
    "springer",
    "scopus",
]
# Full-text resolvers, in the default resolution order (a review may enable any subset, in any order).
FULLTEXT_SOURCES = (
    "pmc_oa",
    "europepmc",
    "core",
    "springer_oa",
    "semantic_scholar_oa",
    "unpaywall",
    "ieee",
    "sciencedirect",
    "upload",
)
FulltextSource = Literal[
    "pmc_oa",
    "europepmc",
    "core",
    "springer_oa",
    "semantic_scholar_oa",
    "unpaywall",
    "ieee",
    "sciencedirect",
    "upload",
]


class SourceSpec(Model):
    name: SourceName
    max_results: int = Field(default=100, ge=1, le=200)
    contact: str | None = Field(default=None, max_length=200, pattern=EMAIL)


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


Term = Annotated[str, Field(min_length=1, max_length=80)]


class Keywords(Model):
    """A field's keywords: every `all` term, at least one `any` term, no `none` term (research_agent.querybuild)."""

    all: list[Term] = Field(default_factory=list, max_length=20)
    any: list[Term] = Field(default_factory=list, max_length=20)
    none: list[Term] = Field(default_factory=list, max_length=20)


OPTIONAL_DOMAIN_KEYS = ("description", "keywords", "queries")


class DomainSpec(Model):
    """domain.json: the frozen contract between the web app and one pipeline run.

    `queries` ({source: query}, built in code from `keywords`) are searched as they are; a source without one
    gets the LLM-planned queries. The three optional keys are left out of dumps when null, so older contracts
    (and their cache keys) are unchanged."""

    model_config = ALIASED
    schema_version: Literal[1] = Field(alias="schema")
    field: FieldRef | None = None
    topic: str = Field(min_length=3, max_length=500)
    criteria: Criteria
    sources: list[SourceSpec] = Field(min_length=1, max_length=len(SEARCH_SOURCES))
    years: Years = Field(default_factory=Years)
    thresholds: Thresholds = Field(default_factory=Thresholds)
    description: str | None = Field(default=None, max_length=2000)
    keywords: Keywords | None = None
    queries: dict[SourceName, Annotated[str, Field(min_length=1, max_length=2000)]] | None = None

    @model_validator(mode="after")
    def _unique_sources(self):
        names = [s.name for s in self.sources]
        if len(set(names)) != len(names):
            raise ValueError("each source may be listed once")
        if self.queries and not set(self.queries) <= set(names):
            raise ValueError("queries may only name sources of this field")
        return self

    @model_serializer(mode="wrap")
    def _without_empty_additions(self, handler):
        data = handler(self)
        for key in OPTIONAL_DOMAIN_KEYS:
            if data.get(key) is None:
                data.pop(key, None)
        return data


class DomainError(ValueError):
    """domain.json cannot be read or is invalid; the message lists every problem."""


def _read_spec(path, model, name, error):
    path = Path(path)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise error(f"cannot read {path}: {exc.strerror}") from None
    except ValueError as exc:
        raise error(f"{path.name} is not valid JSON ({exc})") from None
    try:
        return model.model_validate(data)
    except ValidationError as exc:
        problems = "; ".join(
            f"{'.'.join(str(part) for part in e['loc']) or '(root)'}: {e['msg']}" for e in exc.errors()
        )
        raise error(f"{name} is invalid: {problems}") from None


def read_domain(path):
    return _read_spec(path, DomainSpec, "domain.json", DomainError)


ModelName = Field(default=None, min_length=1, max_length=200)


class ChecklistItem(Model):
    key: str = Field(pattern=r"^[a-z][a-z0-9_]{0,19}$")
    text: str = Field(min_length=3, max_length=500)
    weight: int = Field(default=1, ge=1, le=3)
    source: str | None = Field(default=None, max_length=60)  # e.g. "CLAIM 2020 #21", "TRIPOD+AI 10"
    pass_if: Literal["yes", "no"] = "yes"  # "no" for items phrased negatively
    red_flag_if: Literal["yes", "no"] | None = None


class ReviewerSpec(Model):
    key: str = Field(pattern=r"^[a-z][a-z0-9_]{1,29}$")
    name: str = Field(min_length=1, max_length=100)
    version: int = Field(default=1, ge=1)
    perspective: str = Field(min_length=10, max_length=2000)
    model: str | None = ModelName
    items: list[ChecklistItem] = Field(min_length=1, max_length=20)

    @model_validator(mode="after")
    def _unique_items(self):
        keys = [i.key for i in self.items]
        if len(set(keys)) != len(keys):
            raise ValueError("item keys must be unique within a reviewer")
        return self


class EditorSpec(Model):
    model: str | None = ModelName
    instructions: str = Field(default="", max_length=2000)


class RoleModels(Model):
    plan: str | None = ModelName
    screen: str | None = ModelName
    screen_criteria: str | None = ModelName
    extract: str | None = ModelName


class FulltextSpec(Model):
    sources: list[FulltextSource] = Field(
        default_factory=lambda: ["pmc_oa", "upload"], max_length=len(FULLTEXT_SOURCES)
    )
    contact: str | None = Field(default=None, max_length=200, pattern=EMAIL)
    max_chars: int = Field(default=60000, ge=2000, le=200000)

    @model_validator(mode="after")
    def _sources(self):
        if len(set(self.sources)) != len(self.sources):
            raise ValueError("each full-text source may be listed once")
        if "unpaywall" in self.sources and not self.contact:
            raise ValueError("fulltext.contact is required when unpaywall is a source")
        return self


class ReviewSpec(Model):
    """review.json: the frozen review panel and settings of one run (written by the web worker)."""

    model_config = ALIASED
    schema_version: Literal[1] = Field(alias="schema")
    panel: list[ReviewerSpec] = Field(min_length=1, max_length=5)
    editor: EditorSpec = Field(default_factory=EditorSpec)
    models: RoleModels = Field(default_factory=RoleModels)
    screening: Thresholds | None = None  # replaces domain.thresholds for this run's field screen
    fulltext: FulltextSpec = Field(default_factory=FulltextSpec)

    @model_validator(mode="after")
    def _unique_reviewers(self):
        keys = [r.key for r in self.panel]
        if len(set(keys)) != len(keys):
            raise ValueError("reviewer keys must be unique")
        return self


class ReviewError(ValueError):
    """review.json cannot be read or is invalid; the message lists every problem."""


def read_review(path):
    return _read_spec(path, ReviewSpec, "review.json", ReviewError)


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
    # A panel run (review.json); None: today's review_a/review_b/adjudicate.
    review: ReviewSpec | None = None

    @model_validator(mode="after")
    def _jev_needs_live(self):
        if self.jev and self.mode != "live":
            raise ValueError("Jev screening requires live mode")
        if self.jev_exclude_min_confidence < self.jev_min_confidence:
            raise ValueError("jev_exclude_min_confidence must be >= jev_min_confidence")
        if self.domain is not None and self.topic != self.domain.topic:
            raise ValueError("topic must equal domain.topic")
        return self


class KeywordSuggestion(Model):
    term: Term
    synonyms: list[Term] = Field(default_factory=list, max_length=6)


class FieldSuggestions(Model):
    """The field assist's answer: keywords per group (with synonyms) and draft criteria sentences.
    Suggestions only; the user accepts each one."""

    all: list[KeywordSuggestion] = Field(default_factory=list, max_length=10)
    any: list[KeywordSuggestion] = Field(default_factory=list, max_length=15)
    none: list[KeywordSuggestion] = Field(default_factory=list, max_length=10)
    include: list[Annotated[str, Field(min_length=3, max_length=500)]] = Field(min_length=2, max_length=6)
    exclude: list[Annotated[str, Field(min_length=3, max_length=500)]] = Field(
        default_factory=list, max_length=4
    )


class Plan(Model):
    queries: list[str] = Field(min_length=1, max_length=3)
    rationale: str


class Source(Model):
    connector: str
    record_id: str
    url: str
    query: str
    retrieved_at: str
    raw_sha256: str


class Paper(Model):
    id: str
    title: str
    abstract: str
    year: str = ""
    doi: str = ""
    pmcid: str = ""  # PMC Open Access id (full text); provenance-like, never sent to a model
    sources: list[str] = Field(default_factory=list)  # connectors that found it (after dedup: all of them)
    provenance: list[Source] = Field(min_length=1)
    # Cross-source identifiers (dedup); left out of dumps when empty so older dumps and cache keys are unchanged.
    pmid: str = ""
    arxiv: str = ""
    s2: str = ""

    @model_serializer(mode="wrap")
    def _without_empty_ids(self, handler):
        data = handler(self)
        for key in PAPER_OPTIONAL_IDS:
            if not data.get(key):
                data.pop(key, None)
        return data


PAPER_OPTIONAL_IDS = ("pmid", "arxiv", "s2")


class Screen(Model):
    decision: Literal["include", "exclude", "uncertain"]
    reason: str


class CriterionAnswer(Model):
    key: str
    answer: Literal["yes", "no", "unclear"]
    quote: str  # exact abstract text; required for 'no' on inclusion and 'yes' on exclusion, else ""


class CriteriaScreen(Model):
    answers: list[CriterionAnswer] = Field(min_length=1, max_length=20)
    reason: str


class Claim(Model):
    statement: str
    quote: str = Field(min_length=10)


class Evidence(Model):
    claims: list[Claim] = Field(min_length=1, max_length=5)
    study_design: str
    limitations: list[str] = Field(min_length=1)


class Review(Model):
    verdict: Literal["include", "exclude", "uncertain"]
    relevance: int = Field(ge=0, le=4)
    methods: int = Field(ge=0, le=4)
    support: int = Field(ge=0, le=4)
    strengths: list[str] = Field(min_length=1)
    weaknesses: list[str] = Field(min_length=1)
    assessment: str
    takeaways: list[str] = Field(min_length=1)


class Decision(Model):
    review: Review
    reason: str


class ItemAnswer(Model):
    key: str
    answer: Literal["yes", "no", "unclear", "not_reported"]
    quote: str  # exact span of the text reviewed; required for yes/no, else ""
    section: str  # section of the quote ("" when unknown or no quote)


class PanelReview(Model):
    answers: list[ItemAnswer] = Field(min_length=1, max_length=20)
    verdict: Literal["include", "exclude", "uncertain"]
    strengths: list[str] = Field(min_length=1, max_length=5)
    weaknesses: list[str] = Field(min_length=1, max_length=5)
    summary: str


class Disagreement(Model):
    item: str
    reviewers: list[str] = Field(min_length=1, max_length=5)
    note: str


class EditorDecision(Model):
    verdict: Literal["include", "exclude", "uncertain"]
    reason: str
    disagreements: list[Disagreement] = Field(default_factory=list, max_length=20)
