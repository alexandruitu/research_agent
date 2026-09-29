"""Uploaded PDFs: stored once by sha256 under RESEARCH_UPLOADS_DIR (outside any web root), never executed.

A run reads them from its own folder: `materialize` hard-links (or copies) the latest upload of every paper to
`<run>/uploads/<safe-id>.pdf`, the name the pipeline looks for (`fulltext.upload_name`)."""

import hashlib
import os
import re
import shutil
import tempfile
from pathlib import Path, PurePosixPath

from sqlalchemy import select

from ..fulltext import upload_name
from .db.models import Paper, PaperFile

MAX_MB = 30  # hard cap (the pipeline refuses larger PDFs too); settings may lower it
MAGIC = b"%PDF-"
CHUNK = 1 << 20
HEX64 = re.compile(r"[0-9a-f]{64}")


class UploadRejected(Exception):
    def __init__(self, status, code, message):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


def blob_path(root, sha256):
    """Where the bytes with this hash live; always inside `root`."""
    if not isinstance(sha256, str) or not HEX64.fullmatch(sha256):
        raise ValueError("not a sha256")
    root = Path(root).resolve()
    path = (root / sha256[:2] / f"{sha256}.pdf").resolve()
    if not path.is_relative_to(root):
        raise ValueError("upload path outside the uploads directory")
    return path


def safe_filename(name):
    """The file's own name, for display and downloads: no path, no control characters or quotes."""
    base = PurePosixPath(str(name or "").replace("\\", "/")).name
    base = re.sub(r'[\x00-\x1f\x7f"<>]', "", base).strip()[:200]
    if not base or base in (".", ".."):
        base = "upload.pdf"
    return base


def store_pdf(root, stream, limit_bytes):
    """Copy `stream` into the store; returns (sha256, size). Refuses anything that is not a PDF or is larger
    than `limit_bytes`; nothing is kept on refusal."""
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    digest, size, head = hashlib.sha256(), 0, b""
    handle = tempfile.NamedTemporaryFile(dir=root, prefix=".upload-", delete=False)  # noqa: SIM115
    temp = Path(handle.name)
    try:
        with handle:
            while chunk := stream.read(CHUNK):
                size += len(chunk)
                if size > limit_bytes:
                    raise UploadRejected(
                        413, "too_large", f"The PDF is larger than {limit_bytes // (1 << 20)} MB"
                    )
                if len(head) < len(MAGIC):
                    head += chunk[: len(MAGIC) - len(head)]
                    if len(head) >= len(MAGIC) and not head.startswith(MAGIC):
                        raise UploadRejected(422, "not_pdf", "Only PDF files can be uploaded")
                digest.update(chunk)
                handle.write(chunk)
        if not head.startswith(MAGIC):
            raise UploadRejected(422, "not_pdf", "Only PDF files can be uploaded")
        sha256 = digest.hexdigest()
        target = blob_path(root, sha256)
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            temp.unlink()
        else:
            os.chmod(temp, 0o640)
            os.replace(temp, target)
        return sha256, size
    finally:
        temp.unlink(missing_ok=True)


def remove_blob_if_unused(db, root, sha256):
    if db.scalar(select(PaperFile.id).where(PaperFile.sha256 == sha256).limit(1)) is None:
        blob_path(root, sha256).unlink(missing_ok=True)


def materialize(db, root, run_dir):
    """Put the latest upload of every paper into `<run_dir>/uploads/` (existing files are kept). Returns the
    file names written."""
    target_dir = Path(run_dir) / "uploads"
    written, seen = [], set()
    rows = db.execute(
        select(Paper.source_id, PaperFile.sha256)
        .join(Paper, Paper.id == PaperFile.paper_id)
        .order_by(PaperFile.created_at.desc(), PaperFile.id)
    )
    for source_id, sha256 in rows:
        if source_id in seen:
            continue
        seen.add(source_id)
        source = blob_path(root, sha256)
        target = target_dir / upload_name(source_id)
        if target.exists() or not source.is_file():
            continue
        target_dir.mkdir(parents=True, exist_ok=True)
        try:
            os.link(source, target)
        except OSError:  # another filesystem, or links not allowed: copy
            shutil.copyfile(source, target)
        written.append(target.name)
    return written
