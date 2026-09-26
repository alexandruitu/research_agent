"""Tables for slice 1 (spec section "Data model"). Every table has created_at; keys are UUIDs."""

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


def pk():
    return mapped_column(Uuid, primary_key=True, default=uuid.uuid4)


def created():
    return mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class User(Base):
    __tablename__ = "users"
    id: Mapped[uuid.UUID] = pk()
    email: Mapped[str] = mapped_column(String(320), unique=True)
    name: Mapped[str] = mapped_column(String(200))
    role: Mapped[str] = mapped_column(String(16))  # viewer | member | admin
    password_hash: Mapped[str] = mapped_column(Text)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = created()


class AuthSession(Base):
    __tablename__ = "sessions"
    id: Mapped[uuid.UUID] = pk()
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="CASCADE"))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    csrf_token: Mapped[str] = mapped_column(String(64))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = created()


class Field(Base):
    __tablename__ = "fields"
    id: Mapped[uuid.UUID] = pk()
    name: Mapped[str] = mapped_column(String(200))
    topic: Mapped[str] = mapped_column(Text, unique=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = created()


class Criterion(Base):
    __tablename__ = "criteria"
    __table_args__ = (UniqueConstraint("field_id", "key", "version"),)
    id: Mapped[uuid.UUID] = pk()
    field_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("fields.id", ondelete="CASCADE"))
    key: Mapped[str] = mapped_column(String(100))
    question: Mapped[str] = mapped_column(Text)
    version: Mapped[int] = mapped_column(Integer, default=1)
    position: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = created()


class Paper(Base):
    __tablename__ = "papers"
    id: Mapped[uuid.UUID] = pk()
    source_id: Mapped[str] = mapped_column(String(200), unique=True)
    doi: Mapped[str] = mapped_column(String(300), default="", index=True)
    title: Mapped[str] = mapped_column(Text)
    abstract: Mapped[str] = mapped_column(Text, default="")
    year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    fulltext_ref: Mapped[str | None] = mapped_column(Text, nullable=True)  # reserved for step 2
    created_at: Mapped[datetime] = created()


class GoldSet(Base):
    __tablename__ = "gold_sets"
    id: Mapped[uuid.UUID] = pk()
    name: Mapped[str] = mapped_column(String(200), unique=True)
    citation: Mapped[str] = mapped_column(Text)
    sha256: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = created()


class Run(Base):
    __tablename__ = "runs"
    id: Mapped[uuid.UUID] = pk()
    field_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("fields.id"), index=True)
    kind: Mapped[str] = mapped_column(String(16))  # research | eval
    status: Mapped[str] = mapped_column(String(16))  # queued | running | done | failed
    manifest: Mapped[dict] = mapped_column(JSONB, default=dict)
    folder: Mapped[str | None] = mapped_column(Text, unique=True, nullable=True)
    source_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    gold_set_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("gold_sets.id"), nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id"), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = created()


class Screening(Base):
    __tablename__ = "screenings"
    __table_args__ = (UniqueConstraint("run_id", "paper_id"),)
    id: Mapped[uuid.UUID] = pk()
    run_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("runs.id", ondelete="CASCADE"), index=True)
    paper_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("papers.id"), index=True)
    found_by: Mapped[str] = mapped_column(String(16), default="query")  # query | lookup
    tier: Mapped[str] = mapped_column(String(16))  # jev | llm | rule
    decision: Mapped[str] = mapped_column(String(16))  # include | exclude | uncertain
    jev_decision: Mapped[str | None] = mapped_column(
        String(16), nullable=True
    )  # include | exclude | escalate
    llm_decision: Mapped[str | None] = mapped_column(String(16), nullable=True)
    reason: Mapped[str] = mapped_column(Text, default="")
    call_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = created()


class CriterionScore(Base):
    __tablename__ = "criterion_scores"
    screening_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("screenings.id", ondelete="CASCADE"), primary_key=True
    )
    criterion_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("criteria.id"), primary_key=True)
    probability: Mapped[float] = mapped_column(Float)
    jev_version: Mapped[str] = mapped_column(String(64), default="")


class EvidenceClaim(Base):
    __tablename__ = "evidence_claims"
    id: Mapped[uuid.UUID] = pk()
    run_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("runs.id", ondelete="CASCADE"), index=True)
    paper_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("papers.id"), index=True)
    statement: Mapped[str] = mapped_column(Text)
    quote: Mapped[str] = mapped_column(Text)
    call_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = created()


class Review(Base):
    __tablename__ = "reviews"
    __table_args__ = (UniqueConstraint("run_id", "paper_id", "role"),)
    id: Mapped[uuid.UUID] = pk()
    run_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("runs.id", ondelete="CASCADE"), index=True)
    paper_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("papers.id"), index=True)
    role: Mapped[str] = mapped_column(String(16))  # a | b | adjudicator
    verdict: Mapped[str] = mapped_column(String(16))
    relevance: Mapped[int] = mapped_column(Integer)
    methods: Mapped[int] = mapped_column(Integer)
    support: Mapped[int] = mapped_column(Integer)
    detail: Mapped[dict] = mapped_column(JSONB, default=dict)
    call_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = created()


class Ranking(Base):
    __tablename__ = "rankings"
    run_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("runs.id", ondelete="CASCADE"), primary_key=True
    )
    paper_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("papers.id"), primary_key=True)
    score: Mapped[float] = mapped_column(Float)
    position: Mapped[int] = mapped_column(Integer)


class GoldLabel(Base):
    __tablename__ = "gold_labels"
    gold_set_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("gold_sets.id", ondelete="CASCADE"), primary_key=True
    )
    paper_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("papers.id"), primary_key=True)
    label: Mapped[str] = mapped_column(String(16))  # include | not_included
    label_source: Mapped[str] = mapped_column(String(32), default="sr_included_list")
    via: Mapped[str] = mapped_column(String(16), default="query")


class EvalReport(Base):
    __tablename__ = "eval_reports"
    id: Mapped[uuid.UUID] = pk()
    gold_set_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("gold_sets.id"))
    run_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("runs.id", ondelete="CASCADE"), unique=True)
    metrics: Mapped[dict] = mapped_column(JSONB)
    agreement: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = created()


class Job(Base):
    __tablename__ = "jobs"
    __table_args__ = (
        UniqueConstraint("created_by", "idempotency_key"),
        Index("ix_jobs_status_created", "status", "created_at"),
    )
    id: Mapped[uuid.UUID] = pk()
    kind: Mapped[str] = mapped_column(String(16))  # research | import
    payload: Mapped[dict] = mapped_column(JSONB, default=dict)
    status: Mapped[str] = mapped_column(String(16), default="queued")
    progress: Mapped[dict] = mapped_column(JSONB, default=dict)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    locked_by: Mapped[str | None] = mapped_column(String(100), nullable=True)
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id"), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = created()
