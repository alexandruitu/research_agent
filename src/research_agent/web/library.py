"""The team library: papers saved from runs, with collections, tags, a note, a team status, a frozen snapshot
of the evidence at save time, and a history of every change.

Search (`q`) is ILIKE over title, abstract and note: every whitespace-separated word must match one of them.
The library is small (hundreds to a few thousand items) and people type partial words in mixed languages, so
this beats full-text search (no stemming configuration, no index to maintain); see the slice 4 backend plan.
"""

import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import and_, exists, func, or_, select

from .db.models import (
    Collection,
    Field,
    FieldVersion,
    LibraryEvent,
    LibraryItem,
    LibraryItemCollection,
    LibraryItemTag,
    LibraryTag,
    Paper,
    PaperFile,
    Run,
    Screening,
    User,
)
from .papers import paper_drawer

STATUSES = ("to_read", "read", "relevant", "rejected")
SORTS = ("added_at", "title", "year", "score", "status")
PLAIN = re.compile(r"^[^\x00-\x1f\x7f]*$")
EXPORT_MAX = 5000


class LibraryError(Exception):
    def __init__(self, status, code, message):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


@dataclass
class LibraryQuery:
    q: str | None = None
    collection_id: object = None
    status: str | None = None
    tag: str | None = None
    field_id: object = None
    min_score: float | None = None
    has_red_flags: bool | None = None
    sort: str = "added_at"
    direction: str = "desc"
    page: int = 1
    page_size: int = 50


def _jsonable(value):
    return json.loads(json.dumps(value, default=str))


def normalize_tag(text):
    tag = " ".join(str(text).split()).lower()
    if not 1 <= len(tag) <= 50 or not PLAIN.match(tag):
        raise LibraryError(422, "invalid_tag", "A tag is 1-50 characters of plain text")
    return tag


def build_snapshot(db, run, paper):
    """The evidence of `paper` in `run`, frozen: what the drawer shows, trimmed to what a reader needs."""
    drawer = paper_drawer(db, run, paper)
    if drawer is None:
        raise LibraryError(422, "not_in_run", "This paper is not part of the run")
    version = db.get(FieldVersion, run.field_version_id) if run.field_version_id else None
    field = db.get(Field, run.field_id)
    screening = drawer["screening"]
    panel = drawer["panel"]
    files = db.scalars(select(PaperFile).where(PaperFile.paper_id == paper.id).order_by(PaperFile.created_at))
    snapshot = {
        "schema": 1,
        "taken_at": datetime.now(UTC).isoformat(),
        "paper": drawer["paper"],
        "run": {
            "id": run.id,
            "kind": run.kind,
            "created_at": run.created_at,
            "finished_at": run.finished_at,
        },
        "field": {
            "id": run.field_id,
            "name": version.name if version else field.name,
            "version": version.version if version else None,
        },
        "sources": drawer["sources"],
        "screening": {
            k: screening[k] for k in ("decision", "tier", "reason", "decided_by", "criteria_table")
        },
        "rank": drawer["rank"],
        "panel": None
        if panel is None
        else {
            "score": panel["score"],
            "coverage": panel["coverage"],
            "red_flag_count": panel["red_flag_count"],
            "text_source": panel["text_source"],
            "editor": {"verdict": panel["editor"]["verdict"], "reason": panel["editor"]["reason"]},
            "red_flags": [{"text": f["text"], "source": f["source"]} for f in panel["red_flags"]],
            "reviewers": [
                {k: r[k] for k in ("key", "name", "version", "verdict", "score", "summary")}
                for r in panel["reviews"]
            ],
        },
        "files": [{"id": f.id, "sha256": f.sha256, "filename": f.filename} for f in files],
    }
    return _jsonable(snapshot)


def _apply_snapshot(item, run, snapshot):
    item.snapshot, item.run_id, item.field_id = snapshot, run.id, run.field_id
    panel = snapshot.get("panel") or {}
    rank = snapshot.get("rank") or {}
    item.score = panel.get("score") if panel else rank.get("score")
    item.red_flag_count = panel.get("red_flag_count") if panel else None


def record(db, item, user, kind, detail=None):
    # clock_timestamp(): events of one transaction keep their order (now() is the transaction's start)
    db.add(
        LibraryEvent(
            item_id=item.id,
            user_id=user.id if user else None,
            kind=kind,
            detail=detail or {},
            created_at=func.clock_timestamp(),
        )
    )


def load_collections(db, ids):
    """Collections by id; unknown -> 422 unknown_collection, archived -> 422 archived_collection."""
    rows = (
        {c.id: c for c in db.scalars(select(Collection).where(Collection.id.in_(list(ids))))} if ids else {}
    )
    for cid in ids:
        if cid not in rows:
            raise LibraryError(422, "unknown_collection", "No such collection")
        if rows[cid].archived_at is not None:
            raise LibraryError(422, "archived_collection", f"The collection “{rows[cid].name}” is archived")
    return [rows[cid] for cid in dict.fromkeys(ids)]


def create_collection(db, user, name, description=""):
    name = " ".join(name.split())
    if not name:
        raise LibraryError(422, "validation_error", "A collection needs a name")
    taken = db.scalar(select(Collection).where(func.lower(Collection.name) == name.lower()))
    if taken is not None:
        raise LibraryError(409, "name_taken", "A collection with this name already exists")
    collection = Collection(name=name, description=description or "", created_by=user.id)
    db.add(collection)
    db.flush()
    return collection


def rename_collection(db, collection, name=None, description=None):
    if name is not None:
        name = " ".join(name.split())
        taken = db.scalar(
            select(Collection).where(
                func.lower(Collection.name) == name.lower(), Collection.id != collection.id
            )
        )
        if not name:
            raise LibraryError(422, "validation_error", "A collection needs a name")
        if taken is not None:
            raise LibraryError(409, "name_taken", "A collection with this name already exists")
        collection.name = name
    if description is not None:
        collection.description = description
    db.flush()
    return collection


def _tag_rows(db, names):
    rows = []
    for name in dict.fromkeys(names):
        tag = db.scalar(select(LibraryTag).where(LibraryTag.name == name))
        if tag is None:
            tag = LibraryTag(name=name)
            db.add(tag)
            db.flush()
        rows.append(tag)
    return rows


def tags_of(db, item_ids):
    out = {i: [] for i in item_ids}
    if item_ids:
        for item_id, name in db.execute(
            select(LibraryItemTag.item_id, LibraryTag.name)
            .join(LibraryTag, LibraryTag.id == LibraryItemTag.tag_id)
            .where(LibraryItemTag.item_id.in_(list(item_ids)))
            .order_by(LibraryTag.name)
        ):
            out[item_id].append(name)
    return out


def collections_of(db, item_ids):
    out = {i: [] for i in item_ids}
    if item_ids:
        for item_id, cid, name in db.execute(
            select(LibraryItemCollection.item_id, Collection.id, Collection.name)
            .join(Collection, Collection.id == LibraryItemCollection.collection_id)
            .where(LibraryItemCollection.item_id.in_(list(item_ids)))
            .order_by(func.lower(Collection.name))
        ):
            out[item_id].append({"id": cid, "name": name})
    return out


def _set_tags(db, item, names, merge=False):
    """Replace (or merge into) the item's tags; returns (added, removed) and records an event on change."""
    current = set(tags_of(db, [item.id])[item.id])
    wanted = set(names) | (current if merge else set())
    added, removed = sorted(wanted - current), sorted(current - wanted)
    for tag in _tag_rows(db, added):
        db.add(LibraryItemTag(item_id=item.id, tag_id=tag.id))
    if removed:
        ids = db.scalars(select(LibraryTag.id).where(LibraryTag.name.in_(removed))).all()
        for link in db.scalars(
            select(LibraryItemTag).where(LibraryItemTag.item_id == item.id, LibraryItemTag.tag_id.in_(ids))
        ):
            db.delete(link)
    db.flush()
    return added, removed


def _set_collections(db, item, collections, merge=False):
    current = {c["id"]: c["name"] for c in collections_of(db, [item.id])[item.id]}
    wanted = {c.id: c.name for c in collections}
    if merge:
        wanted |= current
    added = [wanted[c] for c in wanted if c not in current]
    removed = [current[c] for c in current if c not in wanted]
    for cid in wanted:
        if cid not in current:
            db.add(LibraryItemCollection(item_id=item.id, collection_id=cid))
    for link in db.scalars(select(LibraryItemCollection).where(LibraryItemCollection.item_id == item.id)):
        if link.collection_id not in wanted:
            db.delete(link)
    db.flush()
    return sorted(added), sorted(removed)


def save(db, user, run, paper_ids, *, collections=(), tags=(), note="", status="to_read"):
    """Save papers of `run`. New papers become items with a snapshot; papers already in the library keep
    their status, note and snapshot, and get the collections and tags merged. Returns (created, existing)."""
    ids = list(dict.fromkeys(paper_ids))
    in_run = set(
        db.scalars(select(Screening.paper_id).where(Screening.run_id == run.id, Screening.paper_id.in_(ids)))
    )
    missing = [pid for pid in ids if pid not in in_run]
    if missing:
        raise LibraryError(422, "not_in_run", f"{len(missing)} of these papers are not part of this run")
    tags = [normalize_tag(t) for t in tags]
    created, existing = [], []
    for pid in ids:
        item = db.scalar(select(LibraryItem).where(LibraryItem.paper_id == pid))
        if item is None:
            item = LibraryItem(paper_id=pid, status=status, note=note or "", added_by=user.id)
            _apply_snapshot(item, run, build_snapshot(db, run, db.get(Paper, pid)))
            db.add(item)
            db.flush()
            _set_collections(db, item, collections)
            _set_tags(db, item, tags)
            record(
                db,
                item,
                user,
                "added",
                {
                    "run_id": str(run.id),
                    "status": status,
                    "collections": [c.name for c in collections],
                    "tags": sorted(set(tags)),
                },
            )
            created.append(item)
        else:
            c_added, _ = _set_collections(db, item, collections, merge=True)
            t_added, _ = _set_tags(db, item, tags, merge=True)
            if c_added or t_added:
                record(
                    db,
                    item,
                    user,
                    "resaved",
                    {"run_id": str(run.id), "collections_added": c_added, "tags_added": t_added},
                )
            existing.append(item)
    db.flush()
    return created, existing


def update(db, item, user, *, status=None, note=None, tags=None, collections=None):
    if status is not None and status != item.status:
        record(db, item, user, "status", {"from": item.status, "to": status})
        item.status = status
    if note is not None and note != item.note:
        record(db, item, user, "note", {"from": item.note, "to": note})
        item.note = note
    if tags is not None:
        added, removed = _set_tags(db, item, [normalize_tag(t) for t in tags])
        if added or removed:
            record(db, item, user, "tags", {"added": added, "removed": removed})
    if collections is not None:
        added, removed = _set_collections(db, item, collections)
        if added or removed:
            record(db, item, user, "collections", {"added": added, "removed": removed})
    item.updated_at = func.now()
    db.flush()
    return item


def refresh_snapshot(db, item, run, user):
    paper = db.get(Paper, item.paper_id)
    snapshot = build_snapshot(db, run, paper)
    previous = item.run_id
    _apply_snapshot(item, run, snapshot)
    record(
        db, item, user, "snapshot", {"from_run": str(previous) if previous else None, "to_run": str(run.id)}
    )
    item.updated_at = func.now()
    db.flush()
    return item


def _like(word):
    return "%" + word.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


def _filtered(q):
    stmt = select(LibraryItem, Paper).join(Paper, Paper.id == LibraryItem.paper_id)
    for word in (q.q or "").split():
        pattern = _like(word)
        stmt = stmt.where(
            or_(
                Paper.title.ilike(pattern, escape="\\"),
                Paper.abstract.ilike(pattern, escape="\\"),
                LibraryItem.note.ilike(pattern, escape="\\"),
            )
        )
    if q.collection_id:
        stmt = stmt.where(
            exists().where(
                LibraryItemCollection.item_id == LibraryItem.id,
                LibraryItemCollection.collection_id == q.collection_id,
            )
        )
    if q.status:
        stmt = stmt.where(LibraryItem.status == q.status)
    if q.tag:
        stmt = stmt.where(
            exists().where(
                and_(
                    LibraryItemTag.item_id == LibraryItem.id,
                    LibraryItemTag.tag_id == LibraryTag.id,
                    LibraryTag.name == normalize_tag(q.tag),
                )
            )
        )
    if q.field_id:
        stmt = stmt.where(LibraryItem.field_id == q.field_id)
    if q.min_score is not None:
        stmt = stmt.where(LibraryItem.score >= q.min_score)
    if q.has_red_flags is True:
        stmt = stmt.where(LibraryItem.red_flag_count > 0)
    elif q.has_red_flags is False:
        stmt = stmt.where(or_(LibraryItem.red_flag_count.is_(None), LibraryItem.red_flag_count == 0))
    return stmt


def _order(q):
    keys = {
        "added_at": LibraryItem.added_at,
        "title": func.lower(Paper.title),
        "year": Paper.year,
        "score": LibraryItem.score,
        "status": LibraryItem.status,
    }
    if q.sort not in keys:
        raise ValueError(f"unknown sort {q.sort!r}")
    key = keys[q.sort]
    return (key.desc().nulls_last() if q.direction == "desc" else key.asc().nulls_last()), LibraryItem.id


def search(db, q, limit=None):
    """(rows [(item, paper)], total) for one page, or every match up to `limit` when given (export)."""
    stmt = _filtered(q)
    total = db.scalar(select(func.count()).select_from(stmt.with_only_columns(LibraryItem.id).subquery()))
    stmt = stmt.order_by(*_order(q))
    if limit is not None:
        stmt = stmt.limit(limit)
    else:
        stmt = stmt.limit(q.page_size).offset((q.page - 1) * q.page_size)
    return db.execute(stmt).all(), total


def item_dicts(db, rows, user):
    """API shape of library items (LibraryItemOut) for [(item, paper)]."""
    ids = [item.id for item, _ in rows]
    tags, collections = tags_of(db, ids), collections_of(db, ids)
    names = {}
    out = []
    for item, paper in rows:
        if item.added_by and item.added_by not in names:
            adder = db.get(User, item.added_by)
            names[item.added_by] = adder.name if adder else None
        snapshot = item.snapshot or {}
        panel = snapshot.get("panel") or {}
        field = snapshot.get("field")
        out.append(
            {
                "id": item.id,
                "paper": {
                    "id": paper.id,
                    "source_id": paper.source_id,
                    "title": paper.title,
                    "year": paper.year,
                    "doi": paper.doi,
                },
                "status": item.status,
                "note": item.note,
                "tags": tags[item.id],
                "collections": collections[item.id],
                "field": field if item.field_id else None,
                "run_id": item.run_id,
                "score": item.score,
                "red_flag_count": item.red_flag_count,
                "text_source": panel.get("text_source"),
                "editor_verdict": (panel.get("editor") or {}).get("verdict"),
                "added_by_name": names.get(item.added_by),
                "added_at": item.added_at,
                "updated_at": item.updated_at,
                "can_delete": user.role == "admin" or item.added_by == user.id,
            }
        )
    return out


def events_of(db, item):
    rows = db.execute(
        select(LibraryEvent, User.name)
        .outerjoin(User, User.id == LibraryEvent.user_id)
        .where(LibraryEvent.item_id == item.id)
        .order_by(LibraryEvent.created_at, LibraryEvent.id)
    )
    return [
        {"id": e.id, "kind": e.kind, "detail": e.detail, "user_name": name, "created_at": e.created_at}
        for e, name in rows
    ]


def library_refs(db, paper_ids):
    """{paper_id: {item_id, status, collections}} for the saved ones among `paper_ids`."""
    items = (
        db.scalars(select(LibraryItem).where(LibraryItem.paper_id.in_(list(paper_ids)))).all()
        if paper_ids
        else []
    )
    collections = collections_of(db, [i.id for i in items])
    return {
        i.paper_id: {"item_id": i.id, "status": i.status, "collections": collections[i.id]} for i in items
    }


def load_run(db, run_id):
    run = db.get(Run, run_id)
    if run is None:
        raise LibraryError(404, "not_found", "No such run")
    return run


CSV_COLUMNS = (
    "title",
    "year",
    "doi",
    "source_id",
    "status",
    "score",
    "red_flags",
    "collections",
    "tags",
    "note",
    "field",
    "added_by",
    "added_at",
)
FORMULA = ("=", "+", "-", "@", "\t", "\r")


def _cell(value):
    """A spreadsheet never evaluates a cell we write: text starting like a formula gets a leading quote."""
    text = "" if value is None else str(value)
    return "'" + text if text.startswith(FORMULA) else text


def to_csv(items):
    import csv
    import io

    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\r\n")
    writer.writerow(CSV_COLUMNS)
    for i in items:
        writer.writerow(
            _cell(v)
            for v in (
                i["paper"]["title"],
                i["paper"]["year"],
                i["paper"]["doi"],
                i["paper"]["source_id"],
                i["status"],
                i["score"],
                i["red_flag_count"],
                "; ".join(c["name"] for c in i["collections"]),
                "; ".join(i["tags"]),
                i["note"],
                (i["field"] or {}).get("name"),
                i["added_by_name"],
                i["added_at"].isoformat() if hasattr(i["added_at"], "isoformat") else i["added_at"],
            )
        )
    return out.getvalue()


BIBTEX_SPECIAL = {
    "\\": r"\textbackslash{}",
    "{": r"\{",
    "}": r"\}",
    "&": r"\&",
    "%": r"\%",
    "$": r"\$",
    "#": r"\#",
    "_": r"\_",
    "~": r"\textasciitilde{}",
    "^": r"\textasciicircum{}",
}
CONTROL = re.compile(r"[\x00-\x1f\x7f]+")


def bibtex_escape(value):
    text = CONTROL.sub(" ", "" if value is None else str(value))
    return "".join(BIBTEX_SPECIAL.get(c, c) for c in text).strip()


def to_bibtex(items):
    entries, used = [], set()
    for i in items:
        paper = i["paper"]
        base = "ra_" + (re.sub(r"[^A-Za-z0-9]", "", paper["source_id"]) or "paper")
        key, n = base, 1
        while key in used:
            n += 1
            key = f"{base}_{n}"
        used.add(key)
        fields = [("title", paper["title"]), ("year", paper["year"]), ("doi", paper["doi"])]
        if paper["source_id"].startswith("arxiv:"):
            fields.append(("eprint", paper["source_id"].split(":", 1)[1]))
        fields += [("keywords", ", ".join(i["tags"])), ("note", i["note"])]
        body = ",\n".join(f"  {name} = {{{bibtex_escape(v)}}}" for name, v in fields if v not in (None, ""))
        entries.append(f"@article{{{key},\n{body}\n}}\n")
    return "\n".join(entries)
