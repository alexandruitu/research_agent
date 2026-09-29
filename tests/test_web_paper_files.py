"""Uploaded full-text PDFs: validation, storage by hash, members-only downloads, owner or admin deletes."""

import hashlib
import io
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from research_agent.web.db.models import Paper, PaperFile, SettingsVersion
from research_agent.web.uploads import blob_path, materialize, safe_filename, store_pdf

API = "/api/v1"
PDF = b"%PDF-1.4\n1 0 obj << >> endobj\ntrailer << >>\n%%EOF\n"


@pytest.fixture
def paper(db):
    row = Paper(source_id="MED:42", title="A paper", abstract="An abstract.")
    db.add(row)
    db.commit()
    return row


def upload(client, csrf, paper_id, data=PDF, name="paper.pdf"):
    return client.post(
        f"{API}/papers/{paper_id}/files", files={"file": (name, data, "application/pdf")}, headers=csrf
    )


def set_fulltext(db, **changes):
    row = db.scalar(select(SettingsVersion).order_by(SettingsVersion.version.desc()))
    row.fulltext = {**row.fulltext, **changes}
    db.commit()


def test_member_uploads_a_pdf_stored_once_by_hash(sign_in, paper, settings):
    member, csrf = sign_in("member")
    r = upload(member, csrf, paper.id)
    assert r.status_code == 201, r.text
    data = r.json()
    sha = hashlib.sha256(PDF).hexdigest()
    assert (data["filename"], data["size"], data["sha256"]) == ("paper.pdf", len(PDF), sha)
    assert data["uploaded_by_name"] == "Member" and data["can_delete"] is True
    path = blob_path(settings.uploads_dir, sha)
    assert path.read_bytes() == PDF and path.parent.parent == settings.uploads_dir
    assert not path.is_relative_to(settings.runs_dir)
    again = upload(member, csrf, paper.id, name="other.pdf")
    assert again.status_code == 200 and again.json()["id"] == data["id"]
    assert len(list(settings.uploads_dir.glob("*/*.pdf"))) == 1
    assert not list(settings.uploads_dir.glob(".upload-*"))


def test_uploads_are_validated(sign_in, paper, db, settings):
    member, csrf = sign_in("member")
    viewer, viewer_csrf = sign_in("viewer")
    for bad in (b"hello, not a pdf", b"", b"%PD"):
        r = upload(member, csrf, paper.id, data=bad)
        assert r.status_code == 422 and r.json()["code"] == "not_pdf", bad
    assert upload(viewer, viewer_csrf, paper.id).status_code == 403
    assert member.post(f"{API}/papers/{paper.id}/files", files={"file": ("p.pdf", PDF)}).status_code == 403
    missing = "00000000-0000-0000-0000-000000000000"
    assert upload(member, csrf, missing).status_code == 404
    set_fulltext(db, upload_max_mb=1)
    big = PDF + b"0" * (1 << 20)
    r = upload(member, csrf, paper.id, data=big)
    assert r.status_code == 413 and r.json() == {
        "code": "too_large",
        "message": "The PDF is larger than 1 MB",
        "request_id": r.json()["request_id"],
    }
    set_fulltext(db, sources=["pmc_oa"])
    r = upload(member, csrf, paper.id)
    assert r.status_code == 409 and r.json()["code"] == "uploads_disabled"
    assert not list(settings.uploads_dir.glob("**/*.pdf"))


def test_list_download_and_filename_sanitizing(sign_in, paper):
    member, csrf = sign_in("member")
    viewer, _ = sign_in("viewer")
    file_id = upload(member, csrf, paper.id, name="../../etc/evil.pdf").json()["id"]
    [listed] = viewer.get(f"{API}/papers/{paper.id}/files").json()
    assert listed["filename"] == "evil.pdf" and listed["can_delete"] is False
    assert viewer.get(f"{API}/papers/{paper.id}/files/{file_id}").status_code == 403
    r = member.get(f"{API}/papers/{paper.id}/files/{file_id}")
    assert r.status_code == 200 and r.content == PDF
    assert r.headers["content-type"] == "application/pdf"
    assert r.headers["content-disposition"].startswith("attachment;")
    assert r.headers["x-content-type-options"] == "nosniff"
    other = "00000000-0000-0000-0000-000000000000"
    assert member.get(f"{API}/papers/{other}/files/{file_id}").status_code == 404


def test_only_the_uploader_or_an_admin_deletes(sign_in, paper, db, users, settings):
    from research_agent.web.auth import create_user

    create_user(db, email="other@example.org", name="Other", role="member", password="correct horse battery")
    db.commit()
    member, csrf = sign_in("member")
    admin, admin_csrf = sign_in("admin")
    file_id = upload(member, csrf, paper.id).json()["id"]
    other = TestClient(member.app)
    login = other.post(
        f"{API}/auth/login", json={"email": "other@example.org", "password": "correct horse battery"}
    )
    other_csrf = {"X-CSRF-Token": login.json()["csrf_token"]}
    r = other.delete(f"{API}/papers/{paper.id}/files/{file_id}", headers=other_csrf)
    assert r.status_code == 403 and r.json()["code"] == "not_owner"
    assert member.delete(f"{API}/papers/{paper.id}/files/{file_id}").status_code == 403  # no CSRF
    assert member.delete(f"{API}/papers/{paper.id}/files/{file_id}", headers=csrf).status_code == 204
    assert not list(settings.uploads_dir.glob("**/*.pdf"))
    file_id = upload(member, csrf, paper.id).json()["id"]
    assert admin.delete(f"{API}/papers/{paper.id}/files/{file_id}", headers=admin_csrf).status_code == 204
    assert db.scalar(select(PaperFile)) is None


def test_materialize_links_the_latest_upload_of_each_paper(db, paper, settings, tmp_path):
    older, newer = PDF + b"%old", PDF + b"%new"
    for day, data in ((1, older), (2, newer)):
        sha, size = store_pdf(settings.uploads_dir, io.BytesIO(data), 1 << 20)
        when = datetime(2026, 9, day, tzinfo=UTC)
        db.add(PaperFile(paper_id=paper.id, sha256=sha, filename="f.pdf", size=size, created_at=when))
        db.commit()
    run_dir = tmp_path / "runs" / "r1"
    assert materialize(db, settings.uploads_dir, run_dir) == ["MED_42.pdf"]
    assert (run_dir / "uploads" / "MED_42.pdf").read_bytes() == newer
    assert materialize(db, settings.uploads_dir, run_dir) == []  # kept as it is


def test_blob_paths_stay_inside_the_store(tmp_path):
    with pytest.raises(ValueError):
        blob_path(tmp_path, "../" + "a" * 61)
    with pytest.raises(ValueError):
        blob_path(tmp_path, "A" * 64)


def test_filenames_are_sanitized():
    assert safe_filename('..\\..\\x/"evil"\n<b>.pdf') == "evilb.pdf"
    assert safe_filename("") == safe_filename("..") == "upload.pdf"
    assert len(safe_filename("a" * 500 + ".pdf")) == 200
