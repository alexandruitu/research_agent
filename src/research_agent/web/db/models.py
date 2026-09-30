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
    text,
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
    topic: Mapped[str] = mapped_column(Text)  # mirrors the current version (see field_versions)
    current_version: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = created()


class FieldVersion(Base):
    """One saved version of a field; never deleted. `sources` = {"names": [...], "years": {"from", "to"}}."""

    __tablename__ = "field_versions"
    __table_args__ = (UniqueConstraint("field_id", "version"),)
    id: Mapped[uuid.UUID] = pk()
    field_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("fields.id", ondelete="CASCADE"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    name: Mapped[str] = mapped_column(String(200))
    topic: Mapped[str] = mapped_column(Text)
    sources: Mapped[dict] = mapped_column(JSONB, default=dict)
    note: Mapped[str] = mapped_column(Text, default="")
    description: Mapped[str] = mapped_column(Text, default="", server_default="")
    keywords: Mapped[dict | None] = mapped_column(JSONB, nullable=True)  # {all, any, none}; null: none
    query_override: Mapped[dict | None] = mapped_column(JSONB, nullable=True)  # {source: query}
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
    kind: Mapped[str] = mapped_column(String(16), default="legacy", server_default="legacy")
    field_version_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("field_versions.id", ondelete="CASCADE"), nullable=True, index=True
    )
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
    field_version_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("field_versions.id"), nullable=True, index=True
    )
    kind: Mapped[str] = mapped_column(String(16))  # research | eval
    status: Mapped[str] = mapped_column(String(16))  # queued | running | done | failed
    manifest: Mapped[dict] = mapped_column(JSONB, default=dict)
    folder: Mapped[str | None] = mapped_column(Text, unique=True, nullable=True)
    source_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    gold_set_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("gold_sets.id"), nullable=True)
    settings_version_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("settings_versions.id"), nullable=True, index=True
    )  # the review settings a panel run used (null: a legacy run)
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
    decided_by: Mapped[str | None] = mapped_column(String(100), nullable=True)  # criterion key
    sources: Mapped[list] = mapped_column(JSONB, default=list, server_default="[]")  # found by
    created_at: Mapped[datetime] = created()


class CriterionScore(Base):
    __tablename__ = "criterion_scores"
    screening_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("screenings.id", ondelete="CASCADE"), primary_key=True
    )
    criterion_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("criteria.id"), primary_key=True)
    probability: Mapped[float | None] = mapped_column(Float, nullable=True)  # Jev p; null: Jev did not run
    jev_version: Mapped[str] = mapped_column(String(64), default="")
    llm_answer: Mapped[str | None] = mapped_column(String(16), nullable=True)  # yes | no | unclear
    quote: Mapped[str | None] = mapped_column(Text, nullable=True)


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


class SourceRow(Base):
    __tablename__ = "sources"
    name: Mapped[str] = mapped_column(String(32), primary_key=True)  # europepmc | openalex | arxiv
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    max_results: Mapped[int] = mapped_column(Integer, default=100)
    last_check_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_check_ok: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    last_check_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_check_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = created()


class AppSettings(Base):
    __tablename__ = "app_settings"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)  # always 1
    contact_email: Mapped[str | None] = mapped_column(String(200), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class WorkerStatus(Base):
    """Provider key status per model role, written by the worker. Never a key value."""

    __tablename__ = "worker_status"
    role: Mapped[str] = mapped_column(String(32), primary_key=True)
    provider: Mapped[str | None] = mapped_column(String(32), nullable=True)
    model: Mapped[str | None] = mapped_column(String(200), nullable=True)
    key_present: Mapped[bool] = mapped_column(Boolean, default=False)
    key_accepted: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    detail: Mapped[str] = mapped_column(String(200), default="")
    checked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    worker_id: Mapped[str] = mapped_column(String(100), default="")


class ReviewerProfile(Base):
    """A reviewer of the panel; its content lives in versions (never changed once saved)."""

    __tablename__ = "reviewer_profiles"
    id: Mapped[uuid.UUID] = pk()
    key: Mapped[str] = mapped_column(String(30), unique=True)
    current_version: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = created()


class ReviewerVersion(Base):
    """`items` = [{key, text, weight, source, pass_if, red_flag_if}] (research_agent.schemas.ChecklistItem)."""

    __tablename__ = "reviewer_versions"
    __table_args__ = (UniqueConstraint("profile_id", "version"),)
    id: Mapped[uuid.UUID] = pk()
    profile_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("reviewer_profiles.id", ondelete="CASCADE"), index=True
    )
    version: Mapped[int] = mapped_column(Integer)
    name: Mapped[str] = mapped_column(String(100))
    perspective: Mapped[str] = mapped_column(Text)
    items: Mapped[list] = mapped_column(JSONB, default=list)
    model: Mapped[str | None] = mapped_column(String(200), nullable=True)
    note: Mapped[str] = mapped_column(Text, default="")
    created_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = created()


class SettingsVersion(Base):
    """Review settings, one row per save; the current one is the highest version not created by the importer.
    models {plan, screen, screen_criteria, extract}; screening (Jev thresholds); fulltext {sources, contact,
    max_chars, upload_max_mb}; default_panel [reviewer keys]; editor {model, instructions}."""

    __tablename__ = "settings_versions"
    id: Mapped[uuid.UUID] = pk()
    version: Mapped[int] = mapped_column(Integer, unique=True)
    models: Mapped[dict] = mapped_column(JSONB, default=dict)
    screening: Mapped[dict] = mapped_column(JSONB, default=dict)
    fulltext: Mapped[dict] = mapped_column(JSONB, default=dict)
    default_panel: Mapped[list] = mapped_column(JSONB, default=list)
    editor: Mapped[dict] = mapped_column(JSONB, default=dict)
    note: Mapped[str] = mapped_column(Text, default="")
    imported: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    created_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = created()


class RunReviewer(Base):
    """The reviewer versions of a panel run, in panel order."""

    __tablename__ = "run_reviewers"
    run_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("runs.id", ondelete="CASCADE"), primary_key=True
    )
    position: Mapped[int] = mapped_column(Integer, primary_key=True)
    reviewer_version_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("reviewer_versions.id"), index=True
    )


class PaperFile(Base):
    """A PDF a user uploaded for a paper; the bytes live under RESEARCH_UPLOADS_DIR, named by sha256."""

    __tablename__ = "paper_files"
    __table_args__ = (UniqueConstraint("paper_id", "sha256"),)
    id: Mapped[uuid.UUID] = pk()
    paper_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("papers.id", ondelete="CASCADE"), index=True)
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    filename: Mapped[str] = mapped_column(String(200))
    size: Mapped[int] = mapped_column(Integer)
    uploaded_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = created()


class PaperReview(Base):
    """One paper's panel review in one run (report.json state.review[pid])."""

    __tablename__ = "paper_reviews"
    __table_args__ = (UniqueConstraint("run_id", "paper_id"),)
    id: Mapped[uuid.UUID] = pk()
    run_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("runs.id", ondelete="CASCADE"), index=True)
    paper_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("papers.id"), index=True)
    text_source: Mapped[str] = mapped_column(String(16))  # pmc_oa | unpaywall | upload | abstract
    text_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    text_origin: Mapped[str | None] = mapped_column(Text, nullable=True)
    text_sections: Mapped[list] = mapped_column(JSONB, default=list)
    text_truncated: Mapped[bool] = mapped_column(Boolean, default=False)
    text_chars: Mapped[int | None] = mapped_column(Integer, nullable=True)
    editor_verdict: Mapped[str | None] = mapped_column(String(16), nullable=True)
    editor_reason: Mapped[str] = mapped_column(Text, default="")
    disagreements: Mapped[list] = mapped_column(JSONB, default=list)
    editor_call_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    score: Mapped[float | None] = mapped_column(Float, nullable=True)
    coverage: Mapped[float | None] = mapped_column(Float, nullable=True)
    red_flag_count: Mapped[int] = mapped_column(Integer, default=0)


class PanelReport(Base):
    """One reviewer's report on one paper; answers = [{key, answer, quote, section}]."""

    __tablename__ = "panel_reports"
    __table_args__ = (UniqueConstraint("paper_review_id", "reviewer_key"),)
    id: Mapped[uuid.UUID] = pk()
    paper_review_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("paper_reviews.id", ondelete="CASCADE"), index=True
    )
    position: Mapped[int] = mapped_column(Integer, default=0)
    reviewer_key: Mapped[str] = mapped_column(String(30))
    reviewer_version_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("reviewer_versions.id"), nullable=True, index=True
    )
    name: Mapped[str] = mapped_column(String(100))
    version: Mapped[int] = mapped_column(Integer, default=1)
    verdict: Mapped[str] = mapped_column(String(16))
    strengths: Mapped[list] = mapped_column(JSONB, default=list)
    weaknesses: Mapped[list] = mapped_column(JSONB, default=list)
    summary: Mapped[str] = mapped_column(Text, default="")
    score: Mapped[float | None] = mapped_column(Float, nullable=True)
    coverage: Mapped[float | None] = mapped_column(Float, nullable=True)
    answers: Mapped[list] = mapped_column(JSONB, default=list)
    call_key: Mapped[str | None] = mapped_column(String(64), nullable=True)


class RedFlag(Base):
    """A red flag of one paper review: grouped item, with every reviewer answer that raised it."""

    __tablename__ = "red_flags"
    id: Mapped[uuid.UUID] = pk()
    paper_review_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("paper_reviews.id", ondelete="CASCADE"), index=True
    )
    position: Mapped[int] = mapped_column(Integer, default=0)
    text: Mapped[str] = mapped_column(Text)
    source: Mapped[str | None] = mapped_column(String(60), nullable=True)
    raised_by: Mapped[list] = mapped_column(JSONB, default=list)


class Collection(Base):
    """A team collection of library items. Names are unique case-insensitively; archived ones stay readable."""

    __tablename__ = "collections"
    __table_args__ = (Index("ux_collections_lower_name", text("lower(name)"), unique=True),)
    id: Mapped[uuid.UUID] = pk()
    name: Mapped[str] = mapped_column(String(100))
    description: Mapped[str] = mapped_column(Text, default="", server_default="")
    created_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id"), nullable=True)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = created()


class LibraryItem(Base):
    """A paper the team saved, once per paper. `snapshot` freezes the evidence of the run it was saved from;
    field_id, run_id, score and red_flag_count mirror the snapshot for filtering and sorting."""

    __tablename__ = "library_items"
    id: Mapped[uuid.UUID] = pk()
    paper_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("papers.id", ondelete="CASCADE"), unique=True
    )
    status: Mapped[str] = mapped_column(String(16), default="to_read")  # to_read | read | relevant | rejected
    note: Mapped[str] = mapped_column(Text, default="", server_default="")
    snapshot: Mapped[dict] = mapped_column(JSONB, default=dict)
    run_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("runs.id", ondelete="SET NULL"), nullable=True, index=True
    )
    field_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("fields.id", ondelete="SET NULL"), nullable=True, index=True
    )
    score: Mapped[float | None] = mapped_column(Float, nullable=True)
    red_flag_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    added_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id"), nullable=True)
    added_at: Mapped[datetime] = created()
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class LibraryItemCollection(Base):
    __tablename__ = "library_item_collections"
    item_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("library_items.id", ondelete="CASCADE"), primary_key=True
    )
    collection_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("collections.id", ondelete="CASCADE"), primary_key=True, index=True
    )


class LibraryTag(Base):
    """A free-text tag, stored lower-case."""

    __tablename__ = "library_tags"
    id: Mapped[uuid.UUID] = pk()
    name: Mapped[str] = mapped_column(String(50), unique=True)


class LibraryItemTag(Base):
    __tablename__ = "library_item_tags"
    item_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("library_items.id", ondelete="CASCADE"), primary_key=True
    )
    tag_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("library_tags.id", ondelete="CASCADE"), primary_key=True, index=True
    )


class LibraryEvent(Base):
    """History of a library item: added | resaved | status | note | tags | collections | snapshot."""

    __tablename__ = "library_events"
    id: Mapped[uuid.UUID] = pk()
    item_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("library_items.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id"), nullable=True)
    kind: Mapped[str] = mapped_column(String(16))
    detail: Mapped[dict] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = created()
