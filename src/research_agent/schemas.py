import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator


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


class SourceSpec(Model):
    name: Literal["europepmc", "openalex", "arxiv"]
    max_results: int = Field(default=100, ge=1, le=200)
    contact: str | None = Field(default=None, max_length=200, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


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


class DomainSpec(Model):
    """domain.json: the frozen contract between the web app and one pipeline run."""

    model_config = ALIASED
    schema_version: Literal[1] = Field(alias="schema")
    field: FieldRef | None = None
    topic: str = Field(min_length=3, max_length=500)
    criteria: Criteria
    sources: list[SourceSpec] = Field(min_length=1, max_length=3)
    years: Years = Field(default_factory=Years)
    thresholds: Thresholds = Field(default_factory=Thresholds)

    @model_validator(mode="after")
    def _unique_sources(self):
        names = [s.name for s in self.sources]
        if len(set(names)) != len(names):
            raise ValueError("each source may be listed once")
        return self


class DomainError(ValueError):
    """domain.json cannot be read or is invalid; the message lists every problem."""


def read_domain(path):
    path = Path(path)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise DomainError(f"cannot read {path}: {exc.strerror}") from None
    except ValueError as exc:
        raise DomainError(f"{path.name} is not valid JSON ({exc})") from None
    try:
        return DomainSpec.model_validate(data)
    except ValidationError as exc:
        problems = "; ".join(
            f"{'.'.join(str(part) for part in error['loc']) or '(root)'}: {error['msg']}"
            for error in exc.errors()
        )
        raise DomainError(f"domain.json is invalid: {problems}") from None


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

    @model_validator(mode="after")
    def _jev_needs_live(self):
        if self.jev and self.mode != "live":
            raise ValueError("Jev screening requires live mode")
        if self.jev_exclude_min_confidence < self.jev_min_confidence:
            raise ValueError("jev_exclude_min_confidence must be >= jev_min_confidence")
        if self.domain is not None and self.topic != self.domain.topic:
            raise ValueError("topic must equal domain.topic")
        return self


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
