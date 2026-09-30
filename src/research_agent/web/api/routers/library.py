"""The team library: saved papers, collections, history. Static paths come before /library/{item_id}."""

import uuid
from typing import Literal

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy import func, select

from ... import library as svc
from ...db.models import Collection, LibraryItem, LibraryItemCollection, Paper, User
from ..deps import get_db, get_settings, require_role
from ..errors import ApiError
from ..schemas import (
    CollectionCreate,
    CollectionOut,
    CollectionPatch,
    LibraryItemDetail,
    LibraryPage,
    LibraryPatch,
    LibrarySaveOut,
    LibrarySaveRequest,
    SnapshotRequest,
)
from .files import files_of

router = APIRouter(prefix="/library", tags=["library"])
MAX_PAGE = 100_000
Status = Literal["to_read", "read", "relevant", "rejected"]
Sort = Literal["added_at", "title", "year", "score", "status"]


def error(exc):
    return ApiError(exc.status, exc.code, exc.message)


def collection_out(db, collection):
    count = db.scalar(
        select(func.count())
        .select_from(LibraryItemCollection)
        .where(LibraryItemCollection.collection_id == collection.id)
    )
    creator = db.get(User, collection.created_by) if collection.created_by else None
    return CollectionOut(
        id=collection.id,
        name=collection.name,
        description=collection.description,
        archived_at=collection.archived_at,
        item_count=count,
        created_by_name=creator.name if creator else None,
        created_at=collection.created_at,
    )


def load_collection(db, collection_id):
    collection = db.get(Collection, collection_id)
    if collection is None:
        raise ApiError(404, "not_found", "No such collection")
    return collection


def load_item(db, item_id):
    item = db.get(LibraryItem, item_id)
    if item is None:
        raise ApiError(404, "not_found", "No such library item")
    return item


def detail(db, user, item):
    paper = db.get(Paper, item.paper_id)
    (row,) = svc.item_dicts(db, [(item, paper)], user)
    return row | {
        "abstract": paper.abstract,
        "snapshot": item.snapshot,
        "events": svc.events_of(db, item),
        "files": files_of(db, user, paper.id),
    }


def library_query(
    q: str | None = Query(None, max_length=200, description="words matched in title, abstract or note"),
    collection_id: uuid.UUID | None = None,
    status: Status | None = None,
    tag: str | None = Query(None, max_length=50),
    field_id: uuid.UUID | None = None,
    min_score: float | None = Query(None, ge=0, le=100),
    has_red_flags: bool | None = None,
    sort: Sort = "added_at",
    direction: Literal["asc", "desc"] = "desc",
    page: int = Query(1, ge=1, le=MAX_PAGE),
    page_size: int = Query(50, ge=1),
):
    return svc.LibraryQuery(
        q, collection_id, status, tag, field_id, min_score, has_red_flags, sort, direction, page, page_size
    )


@router.get("/collections", response_model=list[CollectionOut])
def list_collections(
    archived: bool = Query(False, description="true: also list archived collections"),
    user=Depends(require_role("viewer")),
    db=Depends(get_db),
):
    stmt = select(Collection).order_by(func.lower(Collection.name))
    if not archived:
        stmt = stmt.where(Collection.archived_at.is_(None))
    return [collection_out(db, c) for c in db.scalars(stmt)]


@router.post("/collections", response_model=CollectionOut, status_code=201)
def create_collection(body: CollectionCreate, user=Depends(require_role("member")), db=Depends(get_db)):
    try:
        collection = svc.create_collection(db, user, body.name, body.description)
    except svc.LibraryError as exc:
        raise error(exc) from None
    db.commit()
    return collection_out(db, collection)


@router.patch("/collections/{collection_id}", response_model=CollectionOut)
def patch_collection(
    collection_id: uuid.UUID, body: CollectionPatch, user=Depends(require_role("member")), db=Depends(get_db)
):
    collection = load_collection(db, collection_id)
    try:
        svc.rename_collection(db, collection, body.name, body.description)
    except svc.LibraryError as exc:
        db.rollback()
        raise error(exc) from None
    db.commit()
    return collection_out(db, collection)


def _archive(db, collection_id, archived):
    collection = load_collection(db, collection_id)
    collection.archived_at = func.now() if archived else None
    db.commit()
    db.refresh(collection)
    return collection_out(db, collection)


@router.post("/collections/{collection_id}/archive", response_model=CollectionOut)
def archive_collection(collection_id: uuid.UUID, user=Depends(require_role("admin")), db=Depends(get_db)):
    return _archive(db, collection_id, True)


@router.post("/collections/{collection_id}/restore", response_model=CollectionOut)
def restore_collection(collection_id: uuid.UUID, user=Depends(require_role("admin")), db=Depends(get_db)):
    return _archive(db, collection_id, False)


@router.get("", response_model=LibraryPage)
def list_library(
    query: svc.LibraryQuery = Depends(library_query),
    user=Depends(require_role("viewer")),
    db=Depends(get_db),
    settings=Depends(get_settings),
):
    if query.page_size > settings.max_page_size:
        raise ApiError(422, "validation_error", f"page_size must be at most {settings.max_page_size}")
    try:
        rows, total = svc.search(db, query)
    except svc.LibraryError as exc:
        raise error(exc) from None
    return LibraryPage(
        items=svc.item_dicts(db, rows, user), total=total, page=query.page, page_size=query.page_size
    )


@router.post("", response_model=LibrarySaveOut, status_code=201)
def save_to_library(
    body: LibrarySaveRequest, response: Response, user=Depends(require_role("member")), db=Depends(get_db)
):
    """Save papers of a run. Already-saved papers keep their status, note and snapshot; the requested
    collections and tags are merged into them and they are listed in `existing` (200 when none is new)."""
    try:
        run = svc.load_run(db, body.run_id)
        collections = svc.load_collections(db, body.collection_ids)
        new = None
        if body.new_collection is not None:
            new = svc.create_collection(db, user, body.new_collection.name, body.new_collection.description)
            collections.append(new)
        created, existing = svc.save(
            db,
            user,
            run,
            body.paper_ids,
            collections=collections,
            tags=body.tags,
            note=body.note,
            status=body.status,
        )
    except svc.LibraryError as exc:
        db.rollback()
        raise error(exc) from None
    db.commit()
    if not created:
        response.status_code = 200
    order = {pid: n for n, pid in enumerate(body.paper_ids)}
    items = sorted(created + existing, key=lambda i: order[i.paper_id])
    rows = [(i, db.get(Paper, i.paper_id)) for i in items]
    return LibrarySaveOut(
        created=[i.id for i in created],
        existing=[i.id for i in existing],
        items=svc.item_dicts(db, rows, user),
        collection=collection_out(db, new) if new else None,
    )


@router.get("/{item_id}", response_model=LibraryItemDetail)
def get_item(item_id: uuid.UUID, user=Depends(require_role("viewer")), db=Depends(get_db)):
    return detail(db, user, load_item(db, item_id))


@router.patch("/{item_id}", response_model=LibraryItemDetail)
def patch_item(
    item_id: uuid.UUID, body: LibraryPatch, user=Depends(require_role("member")), db=Depends(get_db)
):
    item = load_item(db, item_id)
    try:
        collections = (
            svc.load_collections(db, body.collection_ids) if body.collection_ids is not None else None
        )
        svc.update(
            db, item, user, status=body.status, note=body.note, tags=body.tags, collections=collections
        )
    except svc.LibraryError as exc:
        db.rollback()
        raise error(exc) from None
    db.commit()
    db.refresh(item)
    return detail(db, user, item)


@router.delete("/{item_id}", status_code=204)
def delete_item(item_id: uuid.UUID, user=Depends(require_role("member")), db=Depends(get_db)):
    item = load_item(db, item_id)
    if user.role != "admin" and item.added_by != user.id:
        raise ApiError(403, "not_owner", "Only the person who saved it or an admin can remove it")
    db.delete(item)
    db.commit()
    return Response(status_code=204)


@router.post("/{item_id}/snapshot", response_model=LibraryItemDetail)
def update_snapshot(
    item_id: uuid.UUID, body: SnapshotRequest, user=Depends(require_role("member")), db=Depends(get_db)
):
    """Replace the frozen evidence with this paper's evidence in another (usually newer) run."""
    item = load_item(db, item_id)
    try:
        svc.refresh_snapshot(db, item, svc.load_run(db, body.run_id), user)
    except svc.LibraryError as exc:
        db.rollback()
        raise error(exc) from None
    db.commit()
    db.refresh(item)
    return detail(db, user, item)
