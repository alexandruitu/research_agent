import re
import uuid
from datetime import datetime
from typing import Any, ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


def _added_fields_are_optional(schema, cls):
    """Fields added to an existing response model (`ADDED`) are always sent, but the schema does not list
    them as required, so the generated TypeScript types (and the frontend code and fixtures written against
    the old shape) stay valid: adding a field never breaks a client."""
    added = getattr(cls, "ADDED", frozenset())
    if added and "required" in schema:
        schema["required"] = [name for name in schema["required"] if name not in added]
    for name in added:  # openapi-typescript turns a field with a default into a required one
        schema.get("properties", {}).get(name, {}).pop("default", None)


class Model(BaseModel):
    model_config = ConfigDict(
        extra="forbid", from_attributes=True, json_schema_extra=_added_fields_are_optional
    )


class LoginIn(Model):
    email: str
    password: str


class UserOut(Model):
    id: uuid.UUID
    email: str
    name: str
    role: str
    active: bool = True


class SessionOut(Model):
    user: UserOut
    csrf_token: str


class UserCreate(Model):
    email: str
    name: str
    role: str
    password: str


class UserPatch(Model):
    name: str | None = None
    role: str | None = None
    active: bool | None = None
    password: str | None = None


class CriterionOut(Model):
    ADDED: ClassVar[frozenset] = frozenset(["kind"])
    id: uuid.UUID
    key: str
    question: str
    version: int
    position: int
    kind: str = "legacy"  # include | exclude | legacy


PLAIN = r"^[^\x00-\x1f\x7f]*$"  # plain text: no control characters (line breaks included)
SourceName = Literal["europepmc", "openalex", "arxiv"]


class Years(Model):
    model_config = ConfigDict(
        extra="forbid",
        from_attributes=True,
        validate_by_name=True,
        validate_by_alias=True,
        serialize_by_alias=True,
    )
    start: int | None = Field(default=None, alias="from", ge=1900, le=2100)
    end: int | None = Field(default=None, alias="to", ge=1900, le=2100)

    @model_validator(mode="after")
    def _order(self):
        if self.start is not None and self.end is not None and self.start > self.end:
            raise ValueError("years.from must not be after years.to")
        return self


class CriterionIn(Model):
    text: str = Field(min_length=3, max_length=500, pattern=PLAIN)

    @field_validator("text", mode="before")
    @classmethod
    def _strip(cls, value):
        return value.strip() if isinstance(value, str) else value


class FieldDraft(Model):
    """A field definition as the editor sends it. Criterion keys are generated (i1.., e1..) on save."""

    name: str = Field(min_length=1, max_length=200, pattern=PLAIN)
    topic: str = Field(min_length=3, max_length=500, pattern=PLAIN)
    include: list[CriterionIn] = Field(default_factory=list, max_length=10)
    exclude: list[CriterionIn] = Field(default_factory=list, max_length=10)
    sources: list[SourceName] = Field(min_length=1, max_length=3)
    years: Years = Field(default_factory=Years)

    @field_validator("name", "topic", mode="before")
    @classmethod
    def _strip(cls, value):
        return value.strip() if isinstance(value, str) else value

    @model_validator(mode="after")
    def _rules(self):
        if not (self.include or self.exclude):
            raise ValueError("at least one inclusion or exclusion criterion is required")
        if len(set(self.sources)) != len(self.sources):
            raise ValueError("each source may be listed once")
        return self


class FieldCreate(FieldDraft):
    note: str = Field(default="", max_length=500, pattern=PLAIN)


class FieldSave(FieldCreate):
    base_version: int = Field(ge=1)


class CriterionText(Model):
    key: str
    text: str


class FieldVersionOut(Model):
    version: int
    name: str
    topic: str
    include: list[CriterionText]
    exclude: list[CriterionText]
    legacy: list[CriterionText]
    sources: list[str]
    years: Years
    note: str
    imported: bool
    created_by_name: str | None
    created_at: datetime
    run_count: int


class FieldVersionSummary(Model):
    version: int
    note: str
    imported: bool
    created_by_name: str | None
    created_at: datetime
    run_count: int
    include_count: int
    exclude_count: int


class FieldRunRef(Model):
    id: uuid.UUID
    kind: str
    status: str
    created_at: datetime
    field_version: int | None


class FieldOut(Model):
    ADDED: ClassVar[frozenset] = frozenset(
        ["current_version", "archived_at", "current", "last_run", "versions"]
    )
    id: uuid.UUID
    name: str
    topic: str
    criteria: list[CriterionOut]  # the current version's criteria
    current_version: int = 1
    archived_at: datetime | None = None
    current: FieldVersionOut | None = None
    last_run: FieldRunRef | None = None
    versions: list[FieldVersionSummary] = Field(default_factory=list)  # newest first; detail only


class CriteriaTestRequest(Model):
    """Test the saved current version (`draft` null) or unsaved edits (`draft`)."""

    draft: FieldDraft | None = None
    mode: Literal["live", "demo"] = "live"


class SourceOut(Model):
    name: str
    label: str
    enabled: bool
    max_results: int
    last_check_at: datetime | None
    last_check_ok: bool | None
    last_check_ms: int | None
    last_check_error: str | None


class SourcePatch(Model):
    enabled: bool | None = None
    max_results: int | None = Field(default=None, ge=1, le=200)


class SettingsOut(Model):
    contact_email: str | None


class SettingsPatch(Model):
    contact_email: str | None = Field(default=None, max_length=200, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class WorkerStatusOut(Model):
    role: str
    provider: str | None
    model: str | None
    key_present: bool
    key_accepted: bool | None  # null: not checked (no cheap check for this provider) or the check failed
    detail: str
    checked_at: datetime
    worker_id: str


class RunCounts(Model):
    screened: int
    kept: int
    dropped: int
    escalated: int
    in_sr: int | None  # null: the run has no gold set


class RunOut(Model):
    ADDED: ClassVar[frozenset] = frozenset(["field_version"])
    id: uuid.UUID
    field_id: uuid.UUID
    field_name: str
    kind: str
    status: str
    finished_at: datetime | None
    created_at: datetime
    gold_set_name: str | None
    paper_count: int
    error: str | None
    models: dict[str, str]
    field_version: int | None = None  # null: imported before field versions existed and not linked


class RunDetailOut(RunOut):
    ADDED: ClassVar[frozenset] = frozenset(["field_version"])
    manifest: dict[str, Any]
    counts: RunCounts


class StageOut(Model):
    id: str
    title: str
    summary: str
    limits: str
    status: Literal["input", "measured", "caveat", "unmeasured"]
    headline: str | None
    caveat: str | None
    data_link: str | None


class GoldSetOut(Model):
    id: uuid.UUID
    name: str
    citation: str


class Ratio(Model):
    k: int
    n: int


class Recommended(Model):
    min_confidence: float
    exclude_min_confidence: float


class EvalHeadline(Model):
    retrieval_recall: Ratio | None
    cascade_recall: Ratio | None
    recommended: Recommended | None
    kappa: float | None
    same_family: bool | None
    screened: int | None


class EvalSummaryOut(Model):
    id: uuid.UUID
    gold_set: GoldSetOut
    run_id: uuid.UUID
    created_at: datetime
    headline: EvalHeadline


class EvalDetailOut(Model):
    id: uuid.UUID
    gold_set: GoldSetOut
    run_id: uuid.UUID
    created_at: datetime
    metrics: dict[str, Any]
    agreement: dict[str, Any] | None


class PaperRef(Model):
    id: uuid.UUID
    source_id: str
    title: str
    year: int | None
    doi: str


class CriterionCell(Model):
    kind: str  # include | exclude | legacy
    jev_p: float | None  # null: Jev did not score it
    llm: str | None  # yes | no | unclear; null: the LLM did not screen it
    quote: str | None  # verified quote from the abstract, when the LLM gave one


class ScreenCell(Model):
    ADDED: ClassVar[frozenset] = frozenset(["decided_by", "cells"])
    tier: str
    decision: str
    jev_decision: str | None
    llm_decision: str | None
    criteria: dict[str, float]  # Jev probabilities only (unchanged); see `cells` for everything
    decided_by: str | None = None  # the criterion that dropped the paper
    cells: dict[str, CriterionCell] = Field(default_factory=dict)


class ExtractCell(Model):
    claims: int
    quotes_verified: bool


class MissingCell(Model):
    missing: Literal[True]


class ReviewsCell(Model):
    a: str | None
    b: str | None
    adjudicated: bool
    adjudicator: str | None


class RankCell(Model):
    score: float
    position: int


class PaperRow(Model):
    ADDED: ClassVar[frozenset] = frozenset(["sources"])
    paper: PaperRef
    found_by: str
    sources: list[str] = Field(default_factory=list)  # europepmc | openalex | arxiv | demo
    in_sr: bool | None
    screen: ScreenCell
    extract: ExtractCell | MissingCell | None
    reviews: ReviewsCell | MissingCell | None
    rank: RankCell | None


class PaperPage(Model):
    items: list[PaperRow]
    total: int
    page: int
    page_size: int


class PaperDetail(Model):
    id: uuid.UUID
    source_id: str
    title: str
    abstract: str
    year: int | None
    doi: str


class CriterionScoreOut(Model):
    key: str
    question: str
    probability: float
    jev_version: str


class CriterionRowOut(Model):
    key: str
    kind: str  # include | exclude | legacy
    text: str
    jev_p: float | None
    llm: str | None
    quote: str | None
    decided: bool  # this criterion dropped the paper


class ScreeningOut(Model):
    ADDED: ClassVar[frozenset] = frozenset(["decided_by", "criteria_table"])
    tier: str
    decision: str
    jev_decision: str | None
    llm_decision: str | None
    reason: str
    call_key: str | None
    criteria: list[CriterionScoreOut]  # Jev probabilities only (unchanged)
    decided_by: str | None = None
    criteria_table: list[CriterionRowOut] = Field(default_factory=list)  # every criterion of the version


class ClaimOut(Model):
    statement: str
    quote: str
    call_key: str | None


class ReviewOut(Model):
    role: str
    verdict: str
    relevance: int
    methods: int
    support: int
    detail: dict[str, Any]
    call_key: str | None


class DrawerOut(Model):
    ADDED: ClassVar[frozenset] = frozenset(["sources"])
    paper: PaperDetail
    found_by: str
    sources: list[str] = Field(default_factory=list)
    in_sr: bool | None
    label_source: str | None
    screening: ScreeningOut
    claims: list[ClaimOut]
    reviews: list[ReviewOut]
    rank: RankCell | None


class CallOut(Model):
    key: str
    role: str
    model: str
    prompt_version: str
    input: dict[str, Any]
    output: dict[str, Any]


class RunRequest(Model):
    field_id: uuid.UUID
    max_papers: int = Field(default=12, ge=1)
    mode: Literal["live", "demo"] = "live"


class JobOut(Model):
    id: uuid.UUID
    kind: str
    status: str
    progress: dict[str, Any]
    error: str | None
    run_id: uuid.UUID | None
    attempts: int
    created_at: datetime


class StartRunOut(Model):
    job: JobOut
    run_id: uuid.UUID


class ImportRequest(Model):
    kind: Literal["research", "eval"]
    name: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$", max_length=200)


TEXT = r"^[^\x00-\x08\x0b\x0c\x0e-\x1f\x7f]*$"  # like PLAIN, but line breaks and tabs are allowed
ModelId = Field(default=None, min_length=1, max_length=200, pattern=PLAIN)


def _stripped(value):
    return value.strip() if isinstance(value, str) else value


class ChecklistItemIn(Model):
    """A checklist item as the reviewer editor sends it; a missing key is generated on save."""

    key: str | None = Field(default=None, pattern=r"^[a-z][a-z0-9_]{0,19}$")
    text: str = Field(min_length=3, max_length=500, pattern=PLAIN)
    weight: int = Field(default=1, ge=1, le=3)
    source: str | None = Field(default=None, max_length=60, pattern=PLAIN)  # e.g. "CLAIM 2020 #21"
    pass_if: Literal["yes", "no"] = "yes"  # "no" for items phrased negatively
    red_flag_if: Literal["yes", "no"] | None = None

    @field_validator("text", "source", mode="before")
    @classmethod
    def _strip(cls, value):
        return _stripped(value)


class ChecklistItemOut(Model):
    key: str
    text: str
    weight: int
    source: str | None
    pass_if: str
    red_flag_if: str | None


class ReviewerContent(Model):
    name: str
    perspective: str
    model: str | None
    items: list[ChecklistItemOut]


class ReviewerDraft(Model):
    name: str = Field(min_length=1, max_length=100, pattern=PLAIN)
    perspective: str = Field(min_length=10, max_length=2000, pattern=TEXT)
    model: str | None = ModelId  # null: the worker's default reviewer model
    items: list[ChecklistItemIn] = Field(min_length=1, max_length=20)
    note: str = Field(default="", max_length=500, pattern=PLAIN)

    @field_validator("name", "perspective", "model", mode="before")
    @classmethod
    def _strip(cls, value):
        return _stripped(value)

    @model_validator(mode="after")
    def _unique_keys(self):
        keys = [i.key for i in self.items if i.key]
        if len(set(keys)) != len(keys):
            raise ValueError("item keys must be unique within a reviewer")
        return self


class ReviewerCreate(ReviewerDraft):
    key: str | None = Field(default=None, pattern=r"^[a-z][a-z0-9_]{1,29}$")  # null: made from the name


class ReviewerSave(ReviewerDraft):
    base_version: int = Field(ge=1)


class ReviewerVersionOut(Model):
    version: int
    name: str
    perspective: str
    model: str | None
    items: list[ChecklistItemOut]
    note: str
    imported: bool
    created_by_name: str | None
    created_at: datetime
    run_count: int


class ReviewerVersionSummary(Model):
    version: int
    note: str
    imported: bool
    created_by_name: str | None
    created_at: datetime
    run_count: int
    item_count: int


class ReviewerOut(Model):
    key: str
    current_version: int
    archived_at: datetime | None
    in_default_panel: bool  # in the current review settings' default panel
    current: ReviewerVersionOut
    default: ReviewerContent | None  # the seeded content ("Reset to default"); null for a new reviewer
    versions: list[ReviewerVersionSummary] = Field(default_factory=list)  # newest first; detail only


class RoleModelsIO(Model):
    plan: str | None = ModelId
    screen: str | None = ModelId
    screen_criteria: str | None = ModelId
    extract: str | None = ModelId


class ScreeningIO(Model):
    keep_min: float = Field(ge=0, le=1)
    include_fail_max: float = Field(ge=0, le=1)
    exclude_hit_min: float = Field(ge=0, le=1)
    exclude_clear_max: float = Field(ge=0, le=1)


class FulltextIO(Model):
    sources: list[Literal["pmc_oa", "unpaywall", "upload"]] = Field(max_length=3)
    contact: str | None = Field(default=None, max_length=200, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    max_chars: int = Field(ge=2000, le=200000)
    upload_max_mb: int = Field(default=30, ge=1, le=30)


class EditorIO(Model):
    model: str | None = ModelId
    instructions: str = Field(default="", max_length=2000, pattern=TEXT)


class ReviewSettingsContent(Model):
    models: RoleModelsIO
    screening: ScreeningIO
    fulltext: FulltextIO
    default_panel: list[str] = Field(min_length=1, max_length=5)
    editor: EditorIO


class ReviewSettingsSave(ReviewSettingsContent):
    note: str = Field(default="", max_length=500, pattern=PLAIN)
    base_version: int = Field(ge=1)

    @field_validator("default_panel")
    @classmethod
    def _keys(cls, value):
        if any(not re.fullmatch(r"[a-z][a-z0-9_]{1,29}", k) for k in value):
            raise ValueError("default_panel lists reviewer keys")
        if len(set(value)) != len(value):
            raise ValueError("each reviewer may be listed once")
        return value


class ReviewSettingsVersionOut(ReviewSettingsContent):
    version: int
    note: str
    imported: bool
    created_by_name: str | None
    created_at: datetime
    run_count: int


class ReviewSettingsSummary(Model):
    version: int
    note: str
    imported: bool
    created_by_name: str | None
    created_at: datetime
    run_count: int


class ReviewSettingsOut(Model):
    current: ReviewSettingsVersionOut  # what the next run uses
    versions: list[ReviewSettingsSummary]  # newest first
    defaults: ReviewSettingsContent  # "Reset to default"


class ProviderOut(Model):
    provider: str  # anthropic | openai | typesafe
    key_present: bool
    key_accepted: bool | None  # null: not checked


class AvailableModelOut(Model):
    id: str  # e.g. "anthropic:claude-sonnet-5"
    provider: str | None
    available: bool  # the provider key was accepted by the worker's last check
    roles: list[str]  # worker roles configured with it (from the worker's environment)
    in_settings: bool  # used by the current review settings or a current reviewer version


class ModelsAvailableOut(Model):
    models: list[AvailableModelOut]
    providers: list[ProviderOut]
