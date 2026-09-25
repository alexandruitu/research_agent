"""Gold-set schema. One gold file = one systematic review, frozen with a content hash."""

import json
from pathlib import Path
from typing import Literal

import yaml
from pydantic import Field, field_validator, model_validator

from ..connectors import digest
from ..schemas import Model, Paper, Source

GOLD_VERSION = 1


class GoldIntegrityError(ValueError):
    """The gold file changed after it was frozen, or has an unsupported version."""


class StudyRef(Model):
    """One SR-included study, as listed in sr.yaml."""

    doi: str = ""
    title: str = ""
    year: str = ""

    @field_validator("doi", "title", "year", mode="before")
    @classmethod
    def _text(cls, value):
        return "" if value is None else str(value)

    @model_validator(mode="after")
    def _identifiable(self):
        if not (self.doi or self.title):
            raise ValueError("included study needs a doi or a title")
        return self


class SRSpec(Model):
    name: str = Field(pattern=r"^[A-Za-z0-9._-]+$")
    citation: str
    topic: str = Field(min_length=3)
    query: str = Field(min_length=3)
    included: list[StudyRef] = Field(min_length=1)


def load_sr_spec(path):
    return SRSpec.model_validate(yaml.safe_load(Path(path).read_text()))


class GoldCandidate(Model):
    id: str
    doi: str = ""
    title: str
    abstract: str = ""
    year: str = ""
    label: Literal["include", "not_included"]
    label_source: Literal["sr_included_list", "expert"] = "sr_included_list"
    via: Literal["query", "lookup"] = "query"
    flags: list[str] = Field(default_factory=list)


class UnmatchedStudy(Model):
    """An SR-included study that could not be resolved (matches empty) or was ambiguous."""

    reference: StudyRef
    matches: list[str] = Field(default_factory=list)


class GoldSet(Model):
    version: int = GOLD_VERSION
    name: str
    citation: str
    topic: str
    query: str
    built_at: str
    content_sha256: str = ""
    candidates: list[GoldCandidate]
    unresolved: list[UnmatchedStudy] = Field(default_factory=list)
    ambiguous: list[UnmatchedStudy] = Field(default_factory=list)


def content_hash(gold):
    return digest(gold.model_dump(exclude={"content_sha256"}))


def write_gold(gold, path):
    """Freeze (stamp the content hash) and write. Returns the frozen gold set."""
    gold = gold.model_copy(update={"content_sha256": content_hash(gold)})
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(gold.model_dump(), ensure_ascii=False, indent=2))
    return gold


def load_gold(path):
    gold = GoldSet.model_validate_json(Path(path).read_text())
    if gold.version != GOLD_VERSION:
        raise GoldIntegrityError(f"unsupported gold version {gold.version}")
    if gold.content_sha256 != content_hash(gold):
        raise GoldIntegrityError("gold file changed after it was frozen; rebuild it with build-gold")
    return gold


def gold_paper(candidate, gold):
    """A pipeline-shaped Paper for a candidate, so cache keys match the real screening node."""
    return Paper(
        id=candidate.id,
        title=candidate.title,
        abstract=candidate.abstract,
        year=candidate.year,
        doi=candidate.doi,
        provenance=[
            Source(
                connector="gold",
                record_id=candidate.id,
                url=f"gold:{gold.name}/{candidate.id}",
                query=gold.query,
                retrieved_at=gold.built_at,
                raw_sha256=gold.content_sha256,
            )
        ],
    )
