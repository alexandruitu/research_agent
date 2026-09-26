import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict


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
    in_sr: int


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
