"""Review panel settings: reviewers (versioned profiles), review settings (versioned), available models.
Everyone reads; admins write."""

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select

from ... import review as svc
from ...db.models import ReviewerProfile, ReviewerVersion, Run, RunReviewer, SettingsVersion, User
from ..deps import get_db, require_role
from ..errors import ApiError
from ..schemas import (
    ModelsAvailableOut,
    ReviewerCreate,
    ReviewerOut,
    ReviewerSave,
    ReviewerVersionOut,
    ReviewerVersionSummary,
    ReviewSettingsOut,
    ReviewSettingsSave,
    ReviewSettingsSummary,
    ReviewSettingsVersionOut,
)

router = APIRouter(tags=["review"])


def _author(db, user_id):
    user = db.get(User, user_id) if user_id else None
    return user.name if user else None


def _reviewer_runs(db, version):
    return db.scalar(
        select(func.count()).select_from(RunReviewer).where(RunReviewer.reviewer_version_id == version.id)
    )


def reviewer_version_out(db, version):
    return ReviewerVersionOut(
        version=version.version,
        name=version.name,
        perspective=version.perspective,
        model=version.model,
        items=version.items,
        note=version.note,
        imported=version.note == svc.IMPORTED,
        created_by_name=_author(db, version.created_by),
        created_at=version.created_at,
        run_count=_reviewer_runs(db, version),
    )


def reviewer_out(db, profile, detail=False, panel=None):
    panel = svc.current_settings(db).default_panel if panel is None else panel
    versions = []
    if detail:
        for v in db.scalars(
            select(ReviewerVersion)
            .where(ReviewerVersion.profile_id == profile.id)
            .order_by(ReviewerVersion.version.desc())
        ):
            versions.append(
                ReviewerVersionSummary(
                    version=v.version,
                    note=v.note,
                    imported=v.note == svc.IMPORTED,
                    created_by_name=_author(db, v.created_by),
                    created_at=v.created_at,
                    run_count=_reviewer_runs(db, v),
                    item_count=len(v.items),
                )
            )
    return ReviewerOut(
        key=profile.key,
        current_version=profile.current_version,
        archived_at=profile.archived_at,
        in_default_panel=profile.key in panel,
        current=reviewer_version_out(db, svc.get_reviewer_version(db, profile)),
        default=svc.default_reviewer(profile.key),
        versions=versions,
    )


def load_reviewer(db, key):
    profile = svc.get_profile(db, key) if svc.KEY.match(key) else None
    if profile is None:
        raise ApiError(404, "not_found", "No such reviewer")
    return profile


def conflict(exc):
    return ApiError(exc.status, exc.code, exc.message)


@router.get("/reviewers", response_model=list[ReviewerOut])
def list_reviewers(
    archived: bool = Query(False, description="true: also list archived reviewers"),
    user=Depends(require_role("viewer")),
    db=Depends(get_db),
):
    """Reviewers in default-panel order first, then by key."""
    panel = svc.current_settings(db).default_panel
    stmt = select(ReviewerProfile)
    if not archived:
        stmt = stmt.where(ReviewerProfile.archived_at.is_(None))
    profiles = sorted(
        db.scalars(stmt),
        key=lambda p: (panel.index(p.key) if p.key in panel else len(panel), p.key),
    )
    return [reviewer_out(db, p, panel=panel) for p in profiles]


@router.get("/reviewers/{key}", response_model=ReviewerOut)
def get_reviewer(key: str, user=Depends(require_role("viewer")), db=Depends(get_db)):
    return reviewer_out(db, load_reviewer(db, key), detail=True)


@router.get("/reviewers/{key}/versions/{number}", response_model=ReviewerVersionOut)
def get_reviewer_version(key: str, number: int, user=Depends(require_role("viewer")), db=Depends(get_db)):
    version = svc.get_reviewer_version(db, load_reviewer(db, key), number) if number >= 1 else None
    if version is None:
        raise ApiError(404, "not_found", "No such version")
    return reviewer_version_out(db, version)


@router.post("/reviewers", response_model=ReviewerOut, status_code=201)
def create_reviewer(body: ReviewerCreate, user=Depends(require_role("admin")), db=Depends(get_db)):
    try:
        profile = svc.create_reviewer(db, body, user.id)
    except svc.ReviewConflict as exc:
        db.rollback()
        raise conflict(exc) from None
    db.commit()
    return reviewer_out(db, profile, detail=True)


@router.post("/reviewers/{key}/versions", response_model=ReviewerOut, status_code=201)
def save_reviewer(key: str, body: ReviewerSave, user=Depends(require_role("admin")), db=Depends(get_db)):
    profile = load_reviewer(db, key)
    try:
        svc.save_reviewer(db, profile, body, body.base_version, user.id)
    except svc.ReviewConflict as exc:
        db.rollback()
        raise conflict(exc) from None
    db.commit()
    return reviewer_out(db, profile, detail=True)


def _set_archived(db, key, archived):
    profile = load_reviewer(db, key)
    try:
        svc.set_reviewer_archived(db, profile, archived)
    except svc.ReviewConflict as exc:
        db.rollback()
        raise conflict(exc) from None
    db.commit()
    return reviewer_out(db, profile, detail=True)


@router.post("/reviewers/{key}/archive", response_model=ReviewerOut)
def archive_reviewer(key: str, user=Depends(require_role("admin")), db=Depends(get_db)):
    return _set_archived(db, key, True)


@router.post("/reviewers/{key}/restore", response_model=ReviewerOut)
def restore_reviewer(key: str, user=Depends(require_role("admin")), db=Depends(get_db)):
    return _set_archived(db, key, False)


def _settings_runs(db, row):
    return db.scalar(select(func.count()).select_from(Run).where(Run.settings_version_id == row.id))


def settings_out(db):
    current = svc.current_settings(db)
    versions = [
        ReviewSettingsSummary(
            version=row.version,
            note=row.note,
            imported=row.imported,
            created_by_name=_author(db, row.created_by),
            created_at=row.created_at,
            run_count=_settings_runs(db, row),
        )
        for row in db.scalars(select(SettingsVersion).order_by(SettingsVersion.version.desc()))
    ]
    contact = current.fulltext.get("contact")
    return ReviewSettingsOut(
        current=ReviewSettingsVersionOut(
            **svc.settings_content(current),
            version=current.version,
            note=current.note,
            imported=current.imported,
            created_by_name=_author(db, current.created_by),
            created_at=current.created_at,
            run_count=_settings_runs(db, current),
        ),
        versions=versions,
        defaults=svc.default_settings_content(contact),
    )


@router.get("/settings/review", response_model=ReviewSettingsOut)
def get_review_settings(user=Depends(require_role("viewer")), db=Depends(get_db)):
    return settings_out(db)


@router.post("/settings/review", response_model=ReviewSettingsOut, status_code=201)
def save_review_settings(body: ReviewSettingsSave, user=Depends(require_role("admin")), db=Depends(get_db)):
    content = body.model_dump(include={"models", "screening", "fulltext", "default_panel", "editor"})
    try:
        svc.save_settings(db, content, body.note, body.base_version, user.id)
    except svc.ReviewConflict as exc:
        db.rollback()
        raise conflict(exc) from None
    db.commit()
    return settings_out(db)


@router.get("/models/available", response_model=ModelsAvailableOut)
def models_available(user=Depends(require_role("viewer")), db=Depends(get_db)):
    return svc.available_models(db)
