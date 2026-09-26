import uuid

from fastapi import APIRouter, Depends
from sqlalchemy import func, select

from ...auth import ROLE_ORDER, AuthError, create_user, revoke_user_sessions
from ...db.models import User
from ...security import hash_password
from ..deps import get_db, get_settings, require_role
from ..errors import ApiError
from ..schemas import UserCreate, UserOut, UserPatch

router = APIRouter(prefix="/users", tags=["users"])


@router.get("", response_model=list[UserOut])
def list_users(user=Depends(require_role("admin")), db=Depends(get_db)):
    return [UserOut.model_validate(u) for u in db.scalars(select(User).order_by(User.email))]


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
    return UserOut.model_validate(created)


def _active_admins(db):
    return db.scalar(
        select(func.count()).select_from(User).where(User.role == "admin", User.active.is_(True))
    )


@router.patch("/{user_id}", response_model=UserOut)
def patch_user(
    user_id: uuid.UUID,
    body: UserPatch,
    user=Depends(require_role("admin")),
    db=Depends(get_db),
    settings=Depends(get_settings),
):
    target = db.get(User, user_id)
    if target is None:
        raise ApiError(404, "not_found", "No such user")
    demoting = body.role is not None and body.role != "admin" and target.role == "admin"
    deactivating = body.active is False and target.active
    if (demoting or deactivating) and target.role == "admin" and target.active and _active_admins(db) <= 1:
        raise ApiError(409, "last_admin", "There must be at least one active admin")
    if body.role is not None:
        if body.role not in ROLE_ORDER:
            raise ApiError(422, "invalid_user", "unknown role")
        target.role = body.role
    if body.name is not None:
        target.name = body.name.strip()
    if body.password is not None:
        if len(body.password) < settings.min_password_length:
            raise ApiError(
                422, "invalid_user", f"password must have at least {settings.min_password_length} characters"
            )
        target.password_hash = hash_password(body.password)
        revoke_user_sessions(db, target.id)
    if body.active is not None:
        target.active = body.active
        if not body.active:
            revoke_user_sessions(db, target.id)
    db.commit()
    return UserOut.model_validate(target)
