"""Field versioning: every save is a new version; old versions and their criteria are never changed.

`fields.name`/`fields.topic` mirror the current version. `current_version` is the last version a user saved;
a version the importer creates for an unknown snapshot (`note = "imported"`) never becomes current.
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select

from ..jev import default_criteria
from ..querybuild import QueryError, build_queries, normalize_keywords
from ..schemas import SEARCH_SOURCES, DomainSpec
from .db.models import AppSettings, Criterion, Field, FieldVersion, SourceRow

SOURCE_NAMES = SEARCH_SOURCES  # a field may search any of these (research_agent.sources.REGISTRY)
NO_YEARS = {"from": None, "to": None}
LEGACY_SOURCES = {"names": ["europepmc"], "years": NO_YEARS}
KINDS = ("include", "exclude", "legacy")


class FieldConflict(Exception):
    def __init__(self, status, code, message):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


def criteria_of(db, version):
    """{"include": [Criterion], "exclude": [...], "legacy": [...]}, each in saved order."""
    grouped = {kind: [] for kind in KINDS}
    rows = db.scalars(
        select(Criterion)
        .where(Criterion.field_version_id == version.id)
        .order_by(Criterion.position, Criterion.key)
    )
    for row in rows:
        grouped.setdefault(row.kind, []).append(row)
    return grouped


def is_legacy(db, version):
    grouped = criteria_of(db, version)
    return not (grouped["include"] or grouped["exclude"])


def get_version(db, field, number=None):
    return db.scalar(
        select(FieldVersion).where(
            FieldVersion.field_id == field.id, FieldVersion.version == (number or field.current_version)
        )
    )


def _next_number(db, field):
    return (
        db.scalar(select(func.max(FieldVersion.version)).where(FieldVersion.field_id == field.id)) or 0
    ) + 1


def add_version(
    db,
    field,
    *,
    name,
    topic,
    include,
    exclude,
    sources,
    note,
    created_by,
    legacy=(),
    description="",
    keywords=None,
    query_override=None,
):
    """A new version with criteria keyed i1.., e1.. by position. `include`/`exclude` are lists of texts;
    `legacy` a list of (key, question). Returns the version; does not touch `current_version`."""
    version = FieldVersion(
        field_id=field.id,
        version=_next_number(db, field),
        name=name,
        topic=topic,
        sources=sources,
        note=note,
        description=description or "",
        keywords=normalize_keywords(keywords),
        query_override={k: v for k, v in (query_override or {}).items() if v} or None,
        created_by=created_by,
    )
    db.add(version)
    db.flush()
    position = 0
    for kind, prefix, texts in (("include", "i", include), ("exclude", "e", exclude)):
        for n, text in enumerate(texts, start=1):
            db.add(
                Criterion(
                    field_id=field.id,
                    field_version_id=version.id,
                    kind=kind,
                    key=f"{prefix}{n}",
                    question=text,
                    version=version.version,
                    position=position,
                )
            )
            position += 1
    for key, question in legacy:
        db.add(
            Criterion(
                field_id=field.id,
                field_version_id=version.id,
                kind="legacy",
                key=key,
                question=question,
                version=version.version,
                position=position,
            )
        )
        position += 1
    db.flush()
    return version


def _make_current(field, version):
    field.current_version, field.name, field.topic = version.version, version.name, version.topic


def _body_sources(body):
    sources = {"names": list(body.sources), "years": {"from": body.years.start, "to": body.years.end}}
    if body.required_sources:  # left out when empty, so versions saved before partial search look the same
        sources["required"] = [n for n in body.sources if n in set(body.required_sources)]
    return sources


def body_keywords(body):
    """description, keywords and query_override of an editor body, as add_version takes them."""
    return {
        "description": body.description,
        "keywords": body.keywords.model_dump() if body.keywords else None,
        "query_override": body.query_override.model_dump() if body.query_override else None,
    }


def create_field(db, body, user_id):
    field = Field(name=body.name, topic=body.topic, created_by=user_id, current_version=1)
    db.add(field)
    db.flush()
    version = add_version(
        db,
        field,
        name=body.name,
        topic=body.topic,
        include=[c.text for c in body.include],
        exclude=[c.text for c in body.exclude],
        sources=_body_sources(body),
        note=body.note,
        created_by=user_id,
        **body_keywords(body),
    )
    _make_current(field, version)
    db.flush()
    return field


def save_version(db, field, body, base_version, user_id):
    """Optimistic concurrency: the row is locked, then `base_version` must equal `current_version`."""
    db.refresh(field, with_for_update=True)
    if field.archived_at is not None:
        raise FieldConflict(409, "archived", "This field is archived; restore it first")
    if base_version != field.current_version:
        raise FieldConflict(
            409, "stale_version", f"This field changed since you opened it (now v{field.current_version})"
        )
    version = add_version(
        db,
        field,
        name=body.name,
        topic=body.topic,
        include=[c.text for c in body.include],
        exclude=[c.text for c in body.exclude],
        sources=_body_sources(body),
        note=body.note,
        created_by=user_id,
        **body_keywords(body),
    )
    _make_current(field, version)
    db.flush()
    return version


def set_archived(db, field, archived):
    field.archived_at = datetime.now(UTC) if archived else None
    db.flush()
    return field


def legacy_version(db, topic, created_by=None):
    """The field version of a legacy (positional topic) run: an existing legacy version with this topic,
    or a new field with version 1 holding one `topic_match` criterion (today's behaviour)."""
    for version in db.scalars(
        select(FieldVersion).where(FieldVersion.topic == topic).order_by(FieldVersion.created_at)
    ):
        if is_legacy(db, version):
            return db.get(Field, version.field_id), version
    field = Field(name=topic[:80], topic=topic, created_by=created_by, current_version=1)
    db.add(field)
    db.flush()
    question = default_criteria(topic)["topic_match"]["instructions"]
    version = add_version(
        db,
        field,
        name=field.name,
        topic=topic,
        include=[],
        exclude=[],
        sources=LEGACY_SOURCES,
        note="imported",
        created_by=created_by,
        legacy=[("topic_match", question)],
    )
    return field, version


def version_content(topic, include, exclude, names, years, keywords=None):
    """What makes two versions the same field definition (for linking imported runs)."""
    return {
        "topic": topic,
        "include": list(include),
        "exclude": list(exclude),
        "sources": sorted(names),
        "years": {"from": years.get("from"), "to": years.get("to")},
        "keywords": normalize_keywords(keywords),
    }


def stored_content(db, version):
    grouped = criteria_of(db, version)
    return version_content(
        version.topic,
        [c.question for c in grouped["include"]],
        [c.question for c in grouped["exclude"]],
        (version.sources or {}).get("names", []),
        (version.sources or {}).get("years") or NO_YEARS,
        version.keywords,
    )


def domain_content(domain):
    return version_content(
        domain["topic"],
        [c["text"] for c in domain["criteria"]["include"]],
        [c["text"] for c in domain["criteria"]["exclude"]],
        [s["name"] for s in domain["sources"]],
        domain.get("years") or NO_YEARS,
        domain.get("keywords"),
    )


def _matches(stored, wanted):
    """Same topic, criteria and years, and the run's sources are among the version's (a run searches only
    the version's sources that were enabled when it started)."""
    same = {k: v for k, v in stored.items() if k != "sources"} == {
        k: v for k, v in wanted.items() if k != "sources"
    }
    return same and set(wanted["sources"]) <= set(stored["sources"])


def version_for_domain(db, domain, created_by=None):
    """The field version a field run used: the version the snapshot names when its content matches, else
    any version with matching content (see `_matches`), else a new version (`note = "imported"`) of the
    named field, or of a new field."""
    wanted = domain_content(domain)
    ref = domain.get("field") or {}
    same = [
        version
        for version in db.scalars(
            select(FieldVersion)
            .where(FieldVersion.topic == domain["topic"])
            .order_by(FieldVersion.created_at, FieldVersion.version)
        )
        if _matches(stored_content(db, version), wanted)
    ]
    if same:
        named = [v for v in same if str(v.field_id) == ref.get("id")]
        exact = [v for v in named if v.version == ref.get("version")]
        version = (exact or named or same)[0]
        return db.get(Field, version.field_id), version
    field = None
    if ref.get("id"):
        try:
            field = db.get(Field, uuid.UUID(ref["id"]))
        except ValueError:
            field = None
    name = (ref.get("name") or domain["topic"])[:200]
    first = field is None
    if first:
        field = Field(name=name, topic=domain["topic"], created_by=created_by, current_version=1)
        db.add(field)
        db.flush()
    version = add_version(
        db,
        field,
        name=name,
        topic=domain["topic"],
        include=wanted["include"],
        exclude=wanted["exclude"],
        sources={
            "names": wanted["sources"],
            "years": wanted["years"],
            **(
                {"required": required}
                if (required := [s["name"] for s in domain["sources"] if s.get("required")])
                else {}
            ),
        },
        note="imported",
        created_by=created_by,
        description=domain.get("description") or "",
        keywords=wanted["keywords"],
    )
    if first:
        _make_current(field, version)
    return field, version


def settings_row(db):
    row = db.get(AppSettings, 1)
    if row is None:  # the migration seeds it; recreate it if someone deleted it
        row = AppSettings(id=1, contact_email=None)
        db.add(row)
        db.flush()
    return row


def enabled_sources(db):
    return {row.name: row for row in db.scalars(select(SourceRow).where(SourceRow.enabled.is_(True)))}


def build_domain(
    db,
    field,
    version,
    *,
    topic,
    include,
    exclude,
    names,
    years,
    description="",
    keywords=None,
    query_override=None,
    required=(),
):
    """domain.json for a run or a criteria test: the version's criteria, its sources that are enabled (with
    their limits and the contact email) and the default thresholds, plus the per-source queries built from
    the keywords (research_agent.querybuild; an override wins). Raises FieldConflict(422) when none of its
    sources is enabled or the keywords make no query. Validated by the pipeline's own DomainSpec."""
    enabled = enabled_sources(db)
    contact = settings_row(db).contact_email
    sources = []
    for name in names:
        if name in enabled:
            entry = {"name": name, "max_results": enabled[name].max_results}
            if name == "openalex" and contact:
                entry["contact"] = contact
            if name in required:
                entry["required"] = True
            sources.append(entry)
    if not sources:
        raise FieldConflict(422, "no_enabled_source", "None of this field's sources is enabled")
    domain = {
        "schema": 1,
        "field": {
            "id": str(field.id),
            "name": version.name if version else field.name,
            "version": version.version,
        }
        if version
        else None,
        "topic": topic,
        "criteria": {
            "include": [{"key": f"i{n}", "text": t} for n, t in enumerate(include, start=1)],
            "exclude": [{"key": f"e{n}", "text": t} for n, t in enumerate(exclude, start=1)],
        },
        "sources": sources,
        "years": {"from": years.get("from"), "to": years.get("to")},
    }
    keywords = normalize_keywords(keywords)
    try:
        queries = build_queries(keywords, [s["name"] for s in sources], query_override)
    except QueryError as exc:
        raise FieldConflict(422, "no_keywords", str(exc)) from None
    if description:
        domain["description"] = description
    if keywords:
        domain["keywords"] = keywords
    if queries:
        domain["queries"] = queries
    return DomainSpec.model_validate(domain).model_dump(mode="json")


def domain_for_version(db, field, version):
    grouped = criteria_of(db, version)
    stored = version.sources or {}
    return build_domain(
        db,
        field,
        version,
        topic=version.topic,
        include=[c.question for c in grouped["include"]],
        exclude=[c.question for c in grouped["exclude"]],
        names=stored.get("names", []),
        years=stored.get("years") or NO_YEARS,
        required=stored.get("required") or (),
        description=version.description,
        keywords=version.keywords,
        query_override=version.query_override,
    )
