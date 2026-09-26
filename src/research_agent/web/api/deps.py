import hmac

from fastapi import Depends, Request

from ..auth import ROLE_ORDER
from .errors import ApiError

SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


def get_db(request: Request):
    session = request.app.state.session_factory()
    try:
        yield session
    finally:
        session.close()


def get_settings(request: Request):
    return request.app.state.settings


def require_role(role):
    """Dependency factory. Every route declares one (default deny); the guard test relies on `.role`."""
    minimum = ROLE_ORDER[role]

    def dependency(request: Request, db=Depends(get_db)):
        user = request.app.state.auth_provider.current_user(db, request)
        if user is None:
            raise ApiError(401, "unauthorized", "Sign in required")
        if ROLE_ORDER[user.role] < minimum:
            raise ApiError(403, "forbidden", "Your role does not allow this")
        if request.method not in SAFE_METHODS:
            sent = request.headers.get("x-csrf-token", "")
            if not hmac.compare_digest(sent, user.csrf_token):
                raise ApiError(403, "csrf", "Missing or invalid CSRF token")
        return user

    dependency.role = role
    return dependency
