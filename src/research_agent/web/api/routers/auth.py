import logging

from fastapi import APIRouter, Depends, Request, Response

from ...auth import (
    COOKIE,
    AuthError,
    authenticate_password,
    check_password,
    create_user,
    email_taken,
    normalize_email,
    revoke_session,
    start_session,
)
from ...db.models import AuthSession
from ...fields import settings_row
from ..deps import get_db, get_settings, require_role
from ..errors import ApiError
from ..schemas import LoginIn, SessionOut, SignupIn, SignupOut, SignupStatusOut, UserOut

log = logging.getLogger(__name__)
# The same answer for a new account and for an email that is already taken: signup never reveals who has one.
SIGNUP_DONE = "If this address can be used, its account is ready. Sign in with your email and password."
SIGNUP_CLOSED = "Sign-up is not open on this server. Ask an admin for an invitation."
WRONG_DOMAIN = "Use your work email address to create an account."


def _ip(request):
    return request.client.host if request.client else "-"


router = APIRouter(prefix="/auth", tags=["auth"])


def _user_out(current):
    return UserOut(id=current.id, email=current.email, name=current.name, role=current.role)


@router.post("/login", response_model=SessionOut)
def login(
    body: LoginIn, request: Request, response: Response, db=Depends(get_db), settings=Depends(get_settings)
):
    limiter, by_ip = request.app.state.rate_limiter, request.app.state.login_ip_limiter
    ip = _ip(request)
    key = f"{ip}|{body.email.strip().lower()}"
    if not limiter.allowed(key) or not by_ip.allowed(ip):
        raise ApiError(429, "rate_limited", "Too many attempts; try again later")
    user = authenticate_password(db, body.email, body.password)
    if user is None:
        limiter.record_failure(key)
        by_ip.record_failure(ip)  # many emails from one address count too
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


def _domains(db):
    return [d.lower() for d in (settings_row(db).signup_domains or [])]


@router.get("/signup", response_model=SignupStatusOut)
def signup_status(db=Depends(get_db)):
    """Whether the login screen offers "Create an account" (the allowed domains are not listed)."""
    return SignupStatusOut(open=bool(_domains(db)))


@router.post("/signup", response_model=SignupOut, status_code=202)
def signup(body: SignupIn, request: Request, db=Depends(get_db), settings=Depends(get_settings)):
    """A member account for an allowed email domain. A taken email gets the same answer as a new one (and no
    session: the user signs in), so signup never tells who has an account. Every attempt counts against the
    per-IP limit."""
    limiter, ip = request.app.state.signup_limiter, _ip(request)
    if not limiter.allowed(ip):
        raise ApiError(429, "rate_limited", "Too many attempts; try again later")
    limiter.record_failure(ip)
    domains = _domains(db)
    if not domains:
        raise ApiError(403, "signup_closed", SIGNUP_CLOSED)
    try:
        email = normalize_email(body.email)
    except AuthError:
        raise ApiError(422, "invalid_signup", "Enter a valid email address") from None
    if "*" not in domains and email.rsplit("@", 1)[1] not in domains:
        raise ApiError(422, "domain_not_allowed", WRONG_DOMAIN)
    name = body.name.strip()
    if not name:
        raise ApiError(422, "invalid_signup", "Enter your name")
    try:
        check_password(body.password, settings.min_password_length)
    except AuthError as exc:
        raise ApiError(422, "invalid_signup", str(exc)) from None
    if not email_taken(db, email):
        try:
            created = create_user(
                db,
                email=email,
                name=name,
                role="member",
                password=body.password,
                min_password_length=settings.min_password_length,
            )
            db.commit()
            log.info("user signed up: %s", created.id)
        except AuthError:  # lost a race for the same email: the same answer
            db.rollback()
    return SignupOut(message=SIGNUP_DONE)
