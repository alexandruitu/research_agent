import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)


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
    id: uuid.UUID
    key: str
    question: str
    version: int
    position: int


class FieldOut(Model):
    id: uuid.UUID
    name: str
    topic: str
    criteria: list[CriterionOut]


class RunCounts(Model):
    screened: int
    kept: int
    dropped: int
    escalated: int
    in_sr: int | None  # null: the run has no gold set


class RunOut(Model):
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


class RunDetailOut(RunOut):
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


class ScreenCell(Model):
    tier: str
    decision: str
    jev_decision: str | None
    llm_decision: str | None
    criteria: dict[str, float]


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
    paper: PaperRef
    found_by: str
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


class ScreeningOut(Model):
    tier: str
    decision: str
    jev_decision: str | None
    llm_decision: str | None
    reason: str
    call_key: str | None
    criteria: list[CriterionScoreOut]


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
    paper: PaperDetail
    found_by: str
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
