"""Helpers shared by the research-run and eval importers."""

import hashlib
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import delete, select

from ...connectors import normalize_doi
from ..db.models import (
    Criterion,
    CriterionScore,
    EvalReport,
    EvidenceClaim,
    Paper,
    PaperReview,
    Ranking,
    Review,
    Screening,
)
from ..fields import get_version, legacy_version


class ImportFailed(RuntimeError):
    """The folder cannot be imported faithfully; nothing was written."""


@dataclass
class ImportResult:
    run_id: uuid.UUID
    status: str  # created | updated | unchanged
    warnings: list[str] = field(default_factory=list)


def file_sha256(*paths):
    digest = hashlib.sha256()
    for path in paths:
        path = Path(path)
        digest.update(path.name.encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


def get_or_create_field(db, topic, created_by=None):
    """The field of a legacy (positional topic) run; see `fields.legacy_version`."""
    return legacy_version(db, topic, created_by)[0]


def criterion(db, field_row, key, version=None):
    """The criterion `key` of `version` (else the field's latest with that key); created as a `legacy`
    criterion of that version (or the current one) when a run scored a key the field lacks."""
    stmt = select(Criterion).where(Criterion.field_id == field_row.id, Criterion.key == key)
    if version is not None:
        stmt = stmt.where(Criterion.field_version_id == version.id)
    found = db.scalar(stmt.order_by(Criterion.version.desc()).limit(1))
    if found is None:
        version = version or get_version(db, field_row)
        found = Criterion(
            field_id=field_row.id,
            field_version_id=version.id if version else None,
            kind="legacy",
            key=key,
            question=key,
            version=version.version if version else 1,
            position=1,
        )
        db.add(found)
        db.flush()
    return found


def to_year(value):
    text = str(value or "")
    return int(text) if text.isdigit() else None


def upsert_paper(db, source_id, doi, title, abstract, year):
    paper = db.scalar(select(Paper).where(Paper.source_id == source_id))
    if paper is None:
        paper = Paper(source_id=source_id, doi="", title=title, abstract=abstract or "")
        db.add(paper)
    paper.doi = normalize_doi(doi or "")
    paper.title = title
    paper.abstract = abstract or ""
    paper.year = to_year(year)
    db.flush()
    return paper


def clear_run(db, run_id):
    """Remove a run's derived rows so it can be re-imported under the same id."""
    screening_ids = select(Screening.id).where(Screening.run_id == run_id)
    db.execute(delete(CriterionScore).where(CriterionScore.screening_id.in_(screening_ids)))
    # panel_reports and red_flags go with their paper_reviews (ON DELETE CASCADE)
    for model in (Screening, EvidenceClaim, Review, Ranking, EvalReport, PaperReview):
        db.execute(delete(model).where(model.run_id == run_id))
    db.flush()
