import logging
import uuid

from fastapi import APIRouter, Depends
from sqlalchemy import delete, func, select

from ...auth import (
    ROLE_ORDER,
    AuthError,
    check_password,
    create_user,
    email_taken,
    normalize_email,
    revoke_user_sessions,
    utcnow,
)
from ...db.models import AuthSession, Base, User
from ...security import hash_password, new_token
from ..deps import get_db, get_settings, require_role
from ..errors import ApiError
from ..schemas import UserCreate, UserDeleteOut, UserOut, UserPasswordReset, UserPatch, UserReferencesOut

router = APIRouter(prefix="/users", tags=["users"])
log = logging.getLogger(__name__)

DELETED_NAME = "Deleted user"


@router.get("", response_model=list[UserOut])
def list_users(include_deleted: bool = False, user=Depends(require_role("admin")), db=Depends(get_db)):
    query = select(User).order_by(User.email)
    if not include_deleted:
        query = query.where(User.deleted_at.is_(None))
    return [UserOut.model_validate(u) for u in db.scalars(query)]


@router.post("", response_model=UserOut, status_code=201)
def invite(
    body: UserCreate, user=Depends(require_role("admin")), db=Depends(get_db), settings=Depends(get_settings)
):
    try:
        created = create_user(
            db,
            email=body.email,
            name=body.name,
            role=body.role,
            password=body.password,
            min_password_length=settings.min_password_length,
        )
    except AuthError as exc:
        status, code = (409, "conflict") if "already" in str(exc) else (422, "invalid_user")
        raise ApiError(status, code, str(exc)) from None
    db.commit()
    log.info("user invited: %s by %s", created.id, user.id)
    return UserOut.model_validate(created)


def _active_admins(db):
    return db.scalar(
        select(func.count())
        .select_from(User)
        .where(User.role == "admin", User.active.is_(True), User.deleted_at.is_(None))
    )


def _target(db, user_id):
    target = db.get(User, user_id)
    if target is None or target.deleted_at is not None:
        raise ApiError(404, "not_found", "No such user")
    return target


def _guard_removal(db, actor, target, action):
    """Removing admin rights from an active admin (demote, deactivate, delete): never yourself, never the last."""
    if target.role == "admin" and target.active and _active_admins(db) <= 1:
        raise ApiError(409, "last_admin", "There must be at least one active admin")
    if target.id == actor.id:
        raise ApiError(409, "self", f"You cannot {action} your own account")


def _name(value):
    name = value.strip()
    if not name or len(name) > 200:
        raise ApiError(422, "invalid_user", "name must have 1 to 200 characters")
    return name


@router.patch("/{user_id}", response_model=UserOut)
def patch_user(
    user_id: uuid.UUID,
    body: UserPatch,
    user=Depends(require_role("admin")),
    db=Depends(get_db),
    settings=Depends(get_settings),
):
    target = _target(db, user_id)
    if body.role is not None and body.role not in ROLE_ORDER:
        raise ApiError(422, "invalid_user", "unknown role")
    if body.role is not None and body.role != "admin" and target.role == "admin":
        _guard_removal(db, user, target, "demote")
    if body.active is False and target.active:
        _guard_removal(db, user, target, "deactivate")
    if body.email is not None:
        try:
            email = normalize_email(body.email)
        except AuthError as exc:
            raise ApiError(422, "invalid_user", str(exc)) from None
        if email_taken(db, email, except_id=target.id):
            raise ApiError(409, "conflict", "email already registered")
        target.email = email
    if body.name is not None:
        target.name = _name(body.name)
    if body.role is not None:
        target.role = body.role
    if body.password is not None:
        _set_password(db, target, body.password, settings)
    if body.active is not None:
        target.active = body.active
        if not body.active:
            revoke_user_sessions(db, target.id)
    db.commit()
    log.info(
        "user updated: %s by %s (fields: %s)",
        target.id,
        user.id,
        sorted(body.model_fields_set - {"password"}),
    )
    return UserOut.model_validate(target)


def _set_password(db, target, password, settings):
    try:
        check_password(password, settings.min_password_length)
    except AuthError as exc:
        raise ApiError(422, "invalid_user", str(exc)) from None
    target.password_hash = hash_password(password)
    revoke_user_sessions(db, target.id)


@router.post("/{user_id}/password", status_code=204)
def reset_password(
    user_id: uuid.UUID,
    body: UserPasswordReset,
    user=Depends(require_role("admin")),
    db=Depends(get_db),
    settings=Depends(get_settings),
):
    """An admin sets a new password; every session of that user ends. The password is never echoed or logged."""
    target = _target(db, user_id)
    _set_password(db, target, body.password, settings)
    db.commit()
    log.info("user password reset: %s by %s", target.id, user.id)


def _references(db, user_id):
    """Rows in any table that point to the user (sessions excepted: they go with the user)."""
    counts = {}
    for table in Base.metadata.sorted_tables:
        if table.name == AuthSession.__tablename__:
            continue
        for fk in table.foreign_keys:
            if fk.column.table.name != User.__tablename__:
                continue
            n = db.scalar(select(func.count()).select_from(table).where(fk.parent == user_id))
            if n:
                key = f"{table.name}.{fk.parent.name}"
                counts[key] = counts.get(key, 0) + n
    return counts


@router.get("/{user_id}/references", response_model=UserReferencesOut)
def references(user_id: uuid.UUID, user=Depends(require_role("admin")), db=Depends(get_db)):
    """What a delete would do: hard delete when nothing points to the user, else anonymise."""
    _target(db, user_id)
    counts = _references(db, user_id)
    total = sum(counts.values())
    return UserReferencesOut(total=total, by_table=counts, outcome="anonymize" if total else "delete")


@router.delete("/{user_id}", response_model=UserDeleteOut)
def delete_user(user_id: uuid.UUID, user=Depends(require_role("admin")), db=Depends(get_db)):
    target = _target(db, user_id)
    _guard_removal(db, user, target, "delete")
    if not _references(db, user_id):
        db.execute(delete(AuthSession).where(AuthSession.user_id == target.id))
        db.delete(target)
        db.commit()
        log.info("user deleted: %s by %s", user_id, user.id)
        return UserDeleteOut(outcome="deleted")
    revoke_user_sessions(db, target.id)
    target.name = DELETED_NAME
    target.email = f"deleted-{uuid.uuid4()}@invalid"
    target.password_hash = hash_password(new_token())  # nobody knows it: the account cannot sign in
    target.active = False
    target.deleted_at = utcnow()
    db.commit()
    log.info("user anonymized: %s by %s", user_id, user.id)
    return UserDeleteOut(outcome="anonymized", user=UserOut.model_validate(target))
