"""The two libraries (Company and each user's own): saved papers, collections, history. A personal item or
collection is answered as 404 to anyone but its owner, admins included. Static paths come before
/library/{item_id}."""

import uuid
from typing import Literal

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy import func, select

from ... import library as svc
from ...authors import authors_of
from ...db.models import Collection, LibraryItem, LibraryItemCollection, Paper, User
from ..deps import get_db, get_settings, require_role
from ..errors import ApiError
from ..schemas import (
    CollectionCreate,
    CollectionOut,
    CollectionPatch,
    EligibilityOut,
    EligibilityRequest,
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
Scope = Literal["personal", "company"]
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
        scope=collection.scope,
        name=collection.name,
        description=collection.description,
        archived_at=collection.archived_at,
        item_count=count,
        created_by_name=creator.name if creator else None,
        created_at=collection.created_at,
    )


def load_collection(db, collection_id, user):
    collection = db.get(Collection, collection_id)
    if collection is None or not svc.can_see(user, collection):
        raise ApiError(404, "not_found", "No such collection")
    return collection


def load_item(db, item_id, user):
    item = db.get(LibraryItem, item_id)
    if item is None or not svc.can_see(user, item):
        raise ApiError(404, "not_found", "No such library item")
    return item


def detail(db, user, item):
    paper = db.get(Paper, item.paper_id)
    (row,) = svc.item_dicts(db, [(item, paper)], user)
    return row | {
        "abstract": paper.abstract,
        "authors": authors_of(db, [paper.id])[paper.id]["authors"],
        "snapshot": item.snapshot,
        "events": svc.events_of(db, item),
        "files": files_of(db, user, paper.id),
    }


def library_query(
    scope: Scope = Query("company", description="which library: company, or personal (your own)"),
    q: str | None = Query(None, max_length=200, description="words matched in title, abstract or note"),
    collection_id: uuid.UUID | None = None,
    status: Status | None = None,
    tag: str | None = Query(None, max_length=50),
    field_id: uuid.UUID | None = None,
    min_score: float | None = Query(None, ge=0, le=100),
    has_red_flags: bool | None = None,
    author_id: uuid.UUID | None = Query(None, description="items whose paper has this stored author"),
    author_name: str | None = Query(
        None, min_length=1, max_length=200, description="name match: any author with this normalized name"
    ),
    sort: Sort = "added_at",
    direction: Literal["asc", "desc"] = "desc",
    page: int = Query(1, ge=1, le=MAX_PAGE),
    page_size: int = Query(50, ge=1),
):
    return svc.LibraryQuery(
        scope=scope,
        q=q,
        collection_id=collection_id,
        status=status,
        tag=tag,
        field_id=field_id,
        min_score=min_score,
        has_red_flags=has_red_flags,
        author_id=author_id,
        author_name=(author_name or "").strip() or None,
        sort=sort,
        direction=direction,
        page=page,
        page_size=page_size,
    )


@router.get("/collections", response_model=list[CollectionOut])
def list_collections(
    archived: bool = Query(False, description="true: also list archived collections"),
    scope: Scope = Query("company", description="which library's collections"),
    user=Depends(require_role("viewer")),
    db=Depends(get_db),
):
    stmt = (
        select(Collection)
        .where(svc.in_library(scope, user, Collection))
        .order_by(func.lower(Collection.name))
    )
    if not archived:
        stmt = stmt.where(Collection.archived_at.is_(None))
    return [collection_out(db, c) for c in db.scalars(stmt)]


@router.post("/collections", response_model=CollectionOut, status_code=201)
def create_collection(body: CollectionCreate, user=Depends(require_role("member")), db=Depends(get_db)):
    try:
        collection = svc.create_collection(db, user, body.name, body.description, body.scope)
    except svc.LibraryError as exc:
        raise error(exc) from None
    db.commit()
    return collection_out(db, collection)


@router.patch("/collections/{collection_id}", response_model=CollectionOut)
def patch_collection(
    collection_id: uuid.UUID, body: CollectionPatch, user=Depends(require_role("member")), db=Depends(get_db)
):
    collection = load_collection(db, collection_id, user)
    try:
        svc.rename_collection(db, collection, body.name, body.description)
    except svc.LibraryError as exc:
        db.rollback()
        raise error(exc) from None
    db.commit()
    return collection_out(db, collection)


def _archive(db, user, collection_id, archived):
    """Company collections: admins. Personal collections: their owner."""
    collection = load_collection(db, collection_id, user)
    if collection.scope == "company" and user.role != "admin":
        raise ApiError(403, "forbidden", "Only an admin can archive or restore a Company collection")
    collection.archived_at = func.now() if archived else None
    db.commit()
    db.refresh(collection)
    return collection_out(db, collection)


@router.post("/collections/{collection_id}/archive", response_model=CollectionOut)
def archive_collection(collection_id: uuid.UUID, user=Depends(require_role("member")), db=Depends(get_db)):
    return _archive(db, user, collection_id, True)


@router.post("/collections/{collection_id}/restore", response_model=CollectionOut)
def restore_collection(collection_id: uuid.UUID, user=Depends(require_role("member")), db=Depends(get_db)):
    return _archive(db, user, collection_id, False)


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
        rows, total = svc.search(db, query, user)
    except svc.LibraryError as exc:
        raise error(exc) from None
    return LibraryPage(
        items=svc.item_dicts(db, rows, user), total=total, page=query.page, page_size=query.page_size
    )


@router.get(
    "/export",
    response_class=Response,
    responses={200: {"content": {"text/csv": {}, "application/x-bibtex": {}}}},
)
def export_library(
    format: Literal["csv", "bibtex"] = "csv",
    query: svc.LibraryQuery = Depends(library_query),
    user=Depends(require_role("viewer")),
    db=Depends(get_db),
):
    """Every item matching the list filters (at most 5000), as CSV or BibTeX, downloaded as a file."""
    try:
        rows, _total = svc.search(db, query, user, limit=svc.EXPORT_MAX)
    except svc.LibraryError as exc:
        raise error(exc) from None
    items = svc.item_dicts(db, rows, user)
    if format == "csv":
        body, media, name = svc.to_csv(items), "text/csv; charset=utf-8", "library.csv"
    else:
        body, media, name = svc.to_bibtex(items), "application/x-bibtex; charset=utf-8", "library.bib"
    return Response(
        content=body.encode("utf-8"),
        media_type=media,
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )


@router.post("/eligibility", response_model=EligibilityOut)
def check_eligibility(body: EligibilityRequest, user=Depends(require_role("viewer")), db=Depends(get_db)):
    """Which papers of a run can go into the Company library (full text stored or uploaded) and the text they
    would rest on. The save checks this again."""
    try:
        run = svc.load_run(db, body.run_id)
    except svc.LibraryError as exc:
        raise error(exc) from None
    return EligibilityOut(papers=svc.eligibility(db, run, body.paper_ids))


@router.post("", response_model=LibrarySaveOut, status_code=201)
def save_to_library(
    body: LibrarySaveRequest, response: Response, user=Depends(require_role("member")), db=Depends(get_db)
):
    """Save papers of a run into one library (`scope`; personal by default). The Company library takes only
    papers with full text (422 needs_full_text otherwise). Already-saved papers keep their status, note and snapshot; the requested
    collections and tags are merged into them and they are listed in `existing` (200 when none is new)."""
    try:
        run = svc.load_run(db, body.run_id)
        collections = svc.load_collections(db, body.collection_ids, body.scope, user)
        new = None
        if body.new_collection is not None:
            new = svc.create_collection(
                db, user, body.new_collection.name, body.new_collection.description, body.scope
            )
            collections.append(new)
        created, existing = svc.save(
            db,
            user,
            run,
            body.paper_ids,
            scope=body.scope,
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
    return detail(db, user, load_item(db, item_id, user))


@router.patch("/{item_id}", response_model=LibraryItemDetail)
def patch_item(
    item_id: uuid.UUID, body: LibraryPatch, user=Depends(require_role("member")), db=Depends(get_db)
):
    item = load_item(db, item_id, user)
    try:
        collections = (
            svc.load_collections(db, body.collection_ids, item.scope, user)
            if body.collection_ids is not None
            else None
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
    item = load_item(db, item_id, user)
    if not svc.can_remove(user, item):
        raise ApiError(403, "not_owner", "Only the person who saved it or an admin can remove it")
    db.delete(item)
    db.commit()
    return Response(status_code=204)


@router.post("/{item_id}/snapshot", response_model=LibraryItemDetail)
def update_snapshot(
    item_id: uuid.UUID, body: SnapshotRequest, user=Depends(require_role("member")), db=Depends(get_db)
):
    """Replace the frozen evidence with this paper's evidence in another (usually newer) run."""
    item = load_item(db, item_id, user)
    try:
        svc.refresh_snapshot(db, item, svc.load_run(db, body.run_id), user)
    except svc.LibraryError as exc:
        db.rollback()
        raise error(exc) from None
    db.commit()
    db.refresh(item)
    return detail(db, user, item)
