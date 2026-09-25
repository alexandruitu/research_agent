from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Contract(Model):
    topic: str = Field(min_length=3, max_length=500)
    max_papers: int = Field(default=12, ge=1, le=30)
    mode: Literal["demo", "live"] = "demo"
    scope: Literal["abstract_only"] = "abstract_only"
    # Jev screening tier (cascade ahead of the LLM screen). Asymmetric: recall over precision.
    jev: bool = False
    jev_min_confidence: float = Field(default=0.6, ge=0, le=1)
    jev_exclude_min_confidence: float = Field(default=0.9, ge=0, le=1)

    @model_validator(mode="after")
    def _jev_needs_live(self):
        if self.jev and self.mode != "live":
            raise ValueError("Jev screening requires live mode")
        if self.jev_exclude_min_confidence < self.jev_min_confidence:
            raise ValueError("jev_exclude_min_confidence must be >= jev_min_confidence")
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
    provenance: list[Source] = Field(min_length=1)


class Screen(Model):
    decision: Literal["include", "exclude", "uncertain"]
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
