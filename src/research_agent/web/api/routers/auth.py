from fastapi import APIRouter, Depends, Request, Response

from ...auth import COOKIE, authenticate_password, revoke_session, start_session
from ...db.models import AuthSession
from ..deps import get_db, get_settings, require_role
from ..errors import ApiError
from ..schemas import LoginIn, SessionOut, UserOut

router = APIRouter(prefix="/auth", tags=["auth"])


def _user_out(current):
    return UserOut(id=current.id, email=current.email, name=current.name, role=current.role)


@router.post("/login", response_model=SessionOut)
def login(
    body: LoginIn, request: Request, response: Response, db=Depends(get_db), settings=Depends(get_settings)
):
    limiter = request.app.state.rate_limiter
    key = f"{request.client.host if request.client else '-'}|{body.email.strip().lower()}"
    if not limiter.allowed(key):
        raise ApiError(429, "rate_limited", "Too many attempts; try again later")
    user = authenticate_password(db, body.email, body.password)
    if user is None:
        limiter.record_failure(key)
        raise ApiError(401, "invalid_credentials", "Wrong email or password")
    limiter.record_success(key)
    token, row = start_session(db, user, settings)
    db.commit()
    response.set_cookie(
        COOKIE,
        token,
        httponly=True,
        samesite="lax",
        secure=settings.cookie_secure,
        max_age=settings.session_absolute_days * 86400,
        path="/",
    )
    return SessionOut(user=UserOut.model_validate(user), csrf_token=row.csrf_token)


@router.post("/logout", status_code=204)
def logout(response: Response, user=Depends(require_role("viewer")), db=Depends(get_db)):
    row = db.get(AuthSession, user.session_id)
    if row is not None:
        revoke_session(db, row)
        db.commit()
    response.delete_cookie(COOKIE, path="/")


@router.get("/me", response_model=SessionOut)
def me(user=Depends(require_role("viewer"))):
    return SessionOut(user=_user_out(user), csrf_token=user.csrf_token)
