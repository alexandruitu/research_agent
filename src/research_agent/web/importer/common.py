"""Helpers shared by the research-run and eval importers."""

import hashlib
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import delete, select

from ...connectors import normalize_doi
from ...jev import default_criteria
from ..db.models import (
    Criterion,
    CriterionScore,
    EvalReport,
    EvidenceClaim,
    Field,
    Paper,
    Ranking,
    Review,
    Screening,
)


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
    row = db.scalar(select(Field).where(Field.topic == topic))
    if row is None:
        row = Field(name=topic[:80], topic=topic, created_by=created_by)
        db.add(row)
        db.flush()
        question = default_criteria(topic)["topic_match"]["instructions"]
        db.add(Criterion(field_id=row.id, key="topic_match", question=question, version=1, position=0))
        db.flush()
    return row


def criterion(db, field_row, key):
    """Latest version of a criterion; created (version 1) when a run scored a key the field lacks."""
    found = db.scalar(
        select(Criterion)
        .where(Criterion.field_id == field_row.id, Criterion.key == key)
        .order_by(Criterion.version.desc())
    )
    if found is None:
        found = Criterion(field_id=field_row.id, key=key, question=key, version=1, position=1)
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
    for model in (Screening, EvidenceClaim, Review, Ranking, EvalReport):
        db.execute(delete(model).where(model.run_id == run_id))
    db.flush()
