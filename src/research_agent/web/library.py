"""The two libraries: papers saved from runs, with collections, tags, a note, a team status, a frozen snapshot
of the evidence at save time, and a history of every change.

Two libraries (`scope`): the Company library (`company`, everyone signed in) and each person's own library
(`personal`, `owner_id`, visible to that person only: every query goes through `visible`/`in_library`). A paper
can be in both. The Company library takes only papers with full text (`full_text`: the panel reviewed full text
of the paper in some run, or someone uploaded its PDF); items migrated from the old team library may be
abstract only and stay, flagged. Collections belong to one library too.

Search (`q`) is ILIKE over title, abstract and note: every whitespace-separated word must match one of them.
The library is small (hundreds to a few thousand items) and people type partial words in mixed languages, so
this beats full-text search (no stemming configuration, no index to maintain); see the slice 4 backend plan.
"""

import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import and_, exists, func, or_, select

from .authors import SHOWN, author_condition, authors_of
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
    PaperReview,
    Run,
    Screening,
    User,
)
from .papers import paper_drawer

STATUSES = ("to_read", "read", "relevant", "rejected")
SCOPES = ("personal", "company")
SORTS = ("added_at", "title", "year", "score", "status")
PLAIN = re.compile(r"^[^\x00-\x1f\x7f]*$")
EXPORT_MAX = 5000


class LibraryError(Exception):
    def __init__(self, status, code, message):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


@dataclass
class LibraryQuery:
    scope: str = "company"  # which library: company | personal (the signed-in user's)
    q: str | None = None
    collection_id: object = None
    status: str | None = None
    tag: str | None = None
    field_id: object = None
    min_score: float | None = None
    has_red_flags: bool | None = None
    author_id: object = None  # an author row id
    author_name: str | None = None  # name match: every author with this normalized name
    sort: str = "added_at"
    direction: str = "desc"
    page: int = 1
    page_size: int = 50


def visible(user, model=LibraryItem):
    """Items (or collections) `user` may see: the Company library and their own."""
    return or_(model.scope == "company", and_(model.scope == "personal", model.owner_id == user.id))


def in_library(scope, user, model=LibraryItem):
    """Items (or collections) of one library as `user` sees it."""
    if scope == "company":
        return model.scope == "company"
    if scope == "personal":
        return and_(model.scope == "personal", model.owner_id == user.id)
    raise ValueError(f"unknown library {scope!r}")


def can_see(user, row):
    return row.scope == "company" or (row.scope == "personal" and row.owner_id == user.id)


def can_remove(user, item):
    """Personal items: their owner. Company items: who added it, or an admin."""
    if item.scope == "personal":
        return item.owner_id == user.id
    return user.role == "admin" or item.added_by == user.id


def full_text(db, run, paper_id):
    """{text_source, text_licence} of the full text available for a paper, or None (abstract only): the text
    the panel reviewed in `run`, else in any other run, else the paper's latest uploaded PDF."""
    reviews = db.execute(
        select(PaperReview.run_id, PaperReview.text_source, PaperReview.text_licence)
        .where(PaperReview.paper_id == paper_id, PaperReview.text_source != "abstract")
        .order_by(PaperReview.id)
    ).all()
    if reviews:
        mine = [r for r in reviews if run is not None and r.run_id == run.id]
        best = (mine or reviews)[0]
        return {"text_source": best.text_source, "text_licence": best.text_licence}
    upload = db.scalar(select(PaperFile.id).where(PaperFile.paper_id == paper_id).limit(1))
    if upload is not None:
        return {"text_source": "upload", "text_licence": "user_upload"}
    return None


def eligibility(db, run, paper_ids):
    """Per paper of the run: whether it can go into the Company library, and the text it would rest on."""
    out = []
    for pid in dict.fromkeys(paper_ids):
        text = full_text(db, run, pid)
        out.append(
            {
                "paper_id": pid,
                "has_full_text": text is not None,
                "text_source": text["text_source"] if text else None,
                "text_licence": text["text_licence"] if text else None,
            }
        )
    return out


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
            "text_licence": panel["text_licence"],
            "editor": {"verdict": panel["editor"]["verdict"], "reason": panel["editor"]["reason"]},
            "red_flags": [
                {
                    "text": f["text"],
                    "item_text": f["item_text"],
                    "source": f["source"],
                    # the first supporting quote, so the snapshot shows the evidence with the problem
                    "quote": f["raised_by"][0]["quote"] if f["raised_by"] else "",
                    "section": f["raised_by"][0]["section"] if f["raised_by"] else "",
                }
                for f in panel["red_flags"]
            ],
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


def _set_text(item, text):
    item.has_full_text = text is not None
    item.text_source = text["text_source"] if text else None
    item.text_licence = text["text_licence"] if text else None


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


def load_collections(db, ids, scope, user):
    """Collections by id in one library; unknown or not visible -> 422 unknown_collection, of the other
    library -> 422 wrong_library, archived -> 422 archived_collection."""
    rows = (
        {
            c.id: c
            for c in db.scalars(
                select(Collection).where(Collection.id.in_(list(ids)), visible(user, Collection))
            )
        }
        if ids
        else {}
    )
    for cid in ids:
        if cid not in rows:
            raise LibraryError(422, "unknown_collection", "No such collection")
        if rows[cid].scope != scope:
            raise LibraryError(
                422, "wrong_library", f"The collection “{rows[cid].name}” belongs to the other library"
            )
        if rows[cid].archived_at is not None:
            raise LibraryError(422, "archived_collection", f"The collection “{rows[cid].name}” is archived")
    return [rows[cid] for cid in dict.fromkeys(ids)]


def _name_taken(db, name, scope, owner_id, exclude=None):
    stmt = select(Collection.id).where(func.lower(Collection.name) == name.lower(), Collection.scope == scope)
    if scope == "personal":
        stmt = stmt.where(Collection.owner_id == owner_id)
    if exclude is not None:
        stmt = stmt.where(Collection.id != exclude)
    return db.scalar(stmt.limit(1)) is not None


def create_collection(db, user, name, description="", scope="company"):
    name = " ".join(name.split())
    if not name:
        raise LibraryError(422, "validation_error", "A collection needs a name")
    owner = user.id if scope == "personal" else None
    if _name_taken(db, name, scope, owner):
        raise LibraryError(409, "name_taken", "A collection with this name already exists")
    collection = Collection(
        name=name, description=description or "", created_by=user.id, scope=scope, owner_id=owner
    )
    db.add(collection)
    db.flush()
    return collection


def rename_collection(db, collection, name=None, description=None):
    if name is not None:
        name = " ".join(name.split())
        if not name:
            raise LibraryError(422, "validation_error", "A collection needs a name")
        if _name_taken(db, name, collection.scope, collection.owner_id, exclude=collection.id):
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


def find_item(db, scope, user, paper_id):
    return db.scalar(select(LibraryItem).where(LibraryItem.paper_id == paper_id, in_library(scope, user)))


def save(db, user, run, paper_ids, *, scope="personal", collections=(), tags=(), note="", status="to_read"):
    """Save papers of `run` into one library. New papers become items with a snapshot; papers already in that
    library keep their status, note and snapshot, and get the collections and tags merged. The Company library
    refuses (422 needs_full_text) when any paper has only its abstract. Returns (created, existing)."""
    if scope not in SCOPES:
        raise LibraryError(422, "validation_error", "Unknown library")
    ids = list(dict.fromkeys(paper_ids))
    in_run = set(
        db.scalars(select(Screening.paper_id).where(Screening.run_id == run.id, Screening.paper_id.in_(ids)))
    )
    missing = [pid for pid in ids if pid not in in_run]
    if missing:
        raise LibraryError(422, "not_in_run", f"{len(missing)} of these papers are not part of this run")
    tags = [normalize_tag(t) for t in tags]
    texts = {pid: full_text(db, run, pid) for pid in ids}
    if scope == "company":
        abstract_only = [pid for pid in ids if texts[pid] is None]
        if abstract_only:
            n = len(abstract_only)
            raise LibraryError(
                422,
                "needs_full_text",
                f"{n} of these papers {'has' if n == 1 else 'have'} only an abstract: the Company library keeps "
                "papers with full text. Upload the PDF first.",
            )
    created, existing = [], []
    for pid in ids:
        item = find_item(db, scope, user, pid)
        text = texts[pid]
        if item is None:
            item = LibraryItem(
                paper_id=pid,
                status=status,
                note=note or "",
                added_by=user.id,
                scope=scope,
                owner_id=user.id if scope == "personal" else None,
            )
            _apply_snapshot(item, run, build_snapshot(db, run, db.get(Paper, pid)))
            _set_text(item, text)
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
                    "library": scope,
                    "status": status,
                    "collections": [c.name for c in collections],
                    "tags": sorted(set(tags)),
                },
            )
            created.append(item)
        else:
            if (
                text is not None and not item.has_full_text
            ):  # e.g. a migrated abstract-only item, now with text
                _set_text(item, text)
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
    text = full_text(db, run, item.paper_id)
    if text is not None:
        _set_text(item, text)
    record(
        db, item, user, "snapshot", {"from_run": str(previous) if previous else None, "to_run": str(run.id)}
    )
    item.updated_at = func.now()
    db.flush()
    return item


def _like(word):
    return "%" + word.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


def _filtered(q, user):
    stmt = (
        select(LibraryItem, Paper)
        .join(Paper, Paper.id == LibraryItem.paper_id)
        .where(in_library(q.scope, user))
    )
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
    by_author = author_condition(LibraryItem.paper_id, q.author_id, q.author_name)
    if by_author is not None:
        stmt = stmt.where(by_author)
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


def search(db, q, user, limit=None):
    """(rows [(item, paper)], total) of one library as `user` sees it, for one page, or every match up to
    `limit` when given (export)."""
    stmt = _filtered(q, user)
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
    people = authors_of(db, [paper.id for _, paper in rows], limit=SHOWN)
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
                "scope": item.scope,
                "has_full_text": item.has_full_text,
                "text_source": item.text_source or panel.get("text_source"),
                "text_licence": item.text_licence,
                "editor_verdict": (panel.get("editor") or {}).get("verdict"),
                "added_by_name": names.get(item.added_by),
                "added_at": item.added_at,
                "updated_at": item.updated_at,
                "can_delete": can_remove(user, item),
                "authors": people[paper.id]["authors"],
                "author_count": people[paper.id]["count"],
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


def library_refs(db, paper_ids, user):
    """{paper_id: ref} for the papers among `paper_ids` saved in a library `user` sees. The ref describes the
    Company item when there is one, else the user's own (item_id, scope, status, collections), and names both
    item ids (company_item_id, personal_item_id; null: not in that library)."""
    items = (
        db.scalars(select(LibraryItem).where(LibraryItem.paper_id.in_(list(paper_ids)), visible(user))).all()
        if paper_ids and user is not None
        else []
    )
    collections = collections_of(db, [i.id for i in items])
    by_paper = {}
    for i in items:
        by_paper.setdefault(i.paper_id, {})[i.scope] = i
    out = {}
    for paper_id, scopes in by_paper.items():
        main = scopes.get("company") or scopes["personal"]
        out[paper_id] = {
            "item_id": main.id,
            "scope": main.scope,
            "status": main.status,
            "collections": collections[main.id],
            "company_item_id": scopes["company"].id if "company" in scopes else None,
            "personal_item_id": scopes["personal"].id if "personal" in scopes else None,
        }
    return out


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


# What an export may read of an item: metadata only. Never text, quotes or sections, whatever their licence
# (publisher_licensed text is reviewed under an entitlement, never redistributed).
EXPORT_KEYS = frozenset(
    {
        "paper",
        "status",
        "score",
        "red_flag_count",
        "collections",
        "tags",
        "note",
        "field",
        "added_by_name",
        "added_at",
    }
)
PAPER_EXPORT_KEYS = ("title", "year", "doi", "source_id")


def export_view(item):
    view = {k: item[k] for k in EXPORT_KEYS if k in item}
    view["paper"] = {k: item["paper"].get(k) for k in PAPER_EXPORT_KEYS}
    return view


def to_csv(items):
    import csv
    import io

    items = [export_view(i) for i in items]

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
    items = [export_view(i) for i in items]
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
