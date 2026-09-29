"""Full-text PDFs uploaded for a paper. Members upload and download; the uploader or an admin deletes;
everyone signed in sees the list (metadata only)."""

import uuid

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import FileResponse
from sqlalchemy import select
from starlette.concurrency import run_in_threadpool

from ...db.models import Paper, PaperFile, User
from ...review import current_settings
from ...uploads import MAX_MB, UploadRejected, blob_path, remove_blob_if_unused, safe_filename, store_pdf
from ..deps import get_db, get_settings, require_role
from ..errors import ApiError
from ..schemas import PaperFileOut

router = APIRouter(prefix="/papers", tags=["files"])
FORM_OVERHEAD = 64 * 1024  # multipart boundaries and headers around the file
UPLOAD_BODY = {
    "requestBody": {
        "required": True,
        "content": {
            "multipart/form-data": {
                "schema": {
                    "type": "object",
                    "required": ["file"],
                    "properties": {"file": {"type": "string", "format": "binary"}},
                }
            }
        },
    }
}


def load_paper(db, paper_id):
    paper = db.get(Paper, paper_id)
    if paper is None:
        raise ApiError(404, "not_found", "No such paper")
    return paper


def can_delete(user, row):
    return user.role == "admin" or row.uploaded_by == user.id


def file_out(db, user, row):
    uploader = db.get(User, row.uploaded_by) if row.uploaded_by else None
    return PaperFileOut(
        id=row.id,
        filename=row.filename,
        size=row.size,
        sha256=row.sha256,
        uploaded_by_name=uploader.name if uploader else None,
        created_at=row.created_at,
        can_delete=can_delete(user, row),
    )


def files_of(db, user, paper_id):
    rows = db.scalars(
        select(PaperFile).where(PaperFile.paper_id == paper_id).order_by(PaperFile.created_at.desc())
    )
    return [file_out(db, user, row) for row in rows]


def upload_limit(db):
    """Bytes allowed per upload; 409 when uploads are not a full-text source in the current settings."""
    fulltext = current_settings(db).fulltext or {}
    if "upload" not in (fulltext.get("sources") or []):
        raise ApiError(409, "uploads_disabled", "Uploads are turned off in Settings → Full text")
    return min(int(fulltext.get("upload_max_mb") or MAX_MB), MAX_MB) << 20


@router.get("/{paper_id}/files", response_model=list[PaperFileOut])
def list_files(paper_id: uuid.UUID, user=Depends(require_role("viewer")), db=Depends(get_db)):
    load_paper(db, paper_id)
    return files_of(db, user, paper_id)


@router.post(
    "/{paper_id}/files",
    response_model=PaperFileOut,
    status_code=201,
    openapi_extra=UPLOAD_BODY,
    responses={200: {"model": PaperFileOut, "description": "The same PDF was already uploaded"}},
)
async def upload_file(
    paper_id: uuid.UUID,
    request: Request,
    response: Response,
    user=Depends(require_role("member")),
    db=Depends(get_db),
    settings=Depends(get_settings),
):
    """Multipart form with one field `file` (a PDF). The size is checked before the body is read."""
    await run_in_threadpool(load_paper, db, paper_id)
    limit = await run_in_threadpool(upload_limit, db)
    try:
        declared = int(request.headers.get("content-length", ""))
    except ValueError:
        raise ApiError(411, "length_required", "Send the upload with a Content-Length") from None
    if declared > limit + FORM_OVERHEAD:
        raise ApiError(413, "too_large", f"The PDF is larger than {limit >> 20} MB")
    async with request.form(max_files=1, max_fields=1) as form:
        upload = form.get("file")
        if upload is None or isinstance(upload, str):
            raise ApiError(422, "validation_error", "Send the PDF in a form field named file")
        try:
            sha256, size = await run_in_threadpool(store_pdf, settings.uploads_dir, upload.file, limit)
        except UploadRejected as exc:
            raise ApiError(exc.status, exc.code, exc.message) from None
        filename = safe_filename(upload.filename)

    def record():
        existing = db.scalar(
            select(PaperFile).where(PaperFile.paper_id == paper_id, PaperFile.sha256 == sha256)
        )
        if existing is not None:
            response.status_code = 200
            return file_out(db, user, existing)
        row = PaperFile(paper_id=paper_id, sha256=sha256, filename=filename, size=size, uploaded_by=user.id)
        db.add(row)
        db.commit()
        return file_out(db, user, row)

    return await run_in_threadpool(record)


def load_file(db, paper_id, file_id):
    row = db.get(PaperFile, file_id)
    if row is None or row.paper_id != paper_id:
        raise ApiError(404, "not_found", "No such file")
    return row


@router.get(
    "/{paper_id}/files/{file_id}",
    response_class=FileResponse,
    responses={200: {"content": {"application/pdf": {}}, "description": "The PDF, as an attachment"}},
)
def download_file(
    paper_id: uuid.UUID,
    file_id: uuid.UUID,
    user=Depends(require_role("member")),
    db=Depends(get_db),
    settings=Depends(get_settings),
):
    row = load_file(db, paper_id, file_id)
    path = blob_path(settings.uploads_dir, row.sha256)
    if not path.is_file():
        raise ApiError(404, "not_found", "The file is missing from the store")
    return FileResponse(
        path,
        media_type="application/pdf",
        filename=row.filename,
        content_disposition_type="attachment",
    )


@router.delete("/{paper_id}/files/{file_id}", status_code=204)
def delete_file(
    paper_id: uuid.UUID,
    file_id: uuid.UUID,
    user=Depends(require_role("member")),
    db=Depends(get_db),
    settings=Depends(get_settings),
):
    row = load_file(db, paper_id, file_id)
    if not can_delete(user, row):
        raise ApiError(403, "not_owner", "Only the uploader or an admin can delete this file")
    sha256 = row.sha256
    db.delete(row)
    db.commit()
    remove_blob_if_unused(db, settings.uploads_dir, sha256)  # after the commit: a failed delete keeps it
    return Response(status_code=204)
