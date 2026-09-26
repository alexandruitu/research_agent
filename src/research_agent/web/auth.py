"""Users, sessions and roles. Sign-in sits behind AuthProvider so SSO can replace it later."""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol

from sqlalchemy import select, update

from .db.models import AuthSession, User
from .security import hash_password, new_token, token_hash, verify_password

ROLE_ORDER = {"viewer": 0, "member": 1, "admin": 2}
COOKIE = "ra_session"
TOUCH_SECONDS = 60


class AuthError(ValueError):
    pass


@dataclass(frozen=True)
class CurrentUser:
    id: uuid.UUID
    email: str
    name: str
    role: str
    csrf_token: str
    session_id: uuid.UUID


def utcnow():
    return datetime.now(UTC)


_DUMMY_HASH = hash_password("dummy-password-for-timing")


def create_user(db, *, email, name, role, password, min_password_length=12):
    email = email.strip().lower()
    if role not in ROLE_ORDER:
        raise AuthError("unknown role")
    if "@" not in email:
        raise AuthError("invalid email")
    if len(password) < min_password_length:
        raise AuthError(f"password must have at least {min_password_length} characters")
    if db.scalar(select(User).where(User.email == email)):
        raise AuthError("email already registered")
    user = User(email=email, name=name.strip(), role=role, password_hash=hash_password(password), active=True)
    db.add(user)
    db.flush()
    return user


def authenticate_password(db, email, password):
    user = db.scalar(select(User).where(User.email == email.strip().lower()))
    if user is None:
        verify_password(_DUMMY_HASH, password)  # equalise timing so unknown emails are not distinguishable
        return None
    if not verify_password(user.password_hash, password) or not user.active:
        return None
    return user


def start_session(db, user, settings, now=None):
    now = now or utcnow()
    token = new_token()
    row = AuthSession(
        user_id=user.id,
        token_hash=token_hash(token),
        csrf_token=new_token(),
        expires_at=now + timedelta(days=settings.session_absolute_days),
        last_seen_at=now,
    )
    db.add(row)
    db.flush()
    return token, row


def load_session(db, token, settings, now=None):
    """Return (session_row, user) for a valid token, else None. Slides the idle timer."""
    now = now or utcnow()
    row = db.scalar(select(AuthSession).where(AuthSession.token_hash == token_hash(token)))
    if row is None or row.revoked_at is not None or row.expires_at <= now:
        return None
    if now - row.last_seen_at > timedelta(hours=settings.session_idle_hours):
        return None
    user = db.get(User, row.user_id)
    if user is None or not user.active:
        return None
    if (now - row.last_seen_at).total_seconds() > TOUCH_SECONDS:
        row.last_seen_at = now
    return row, user


def revoke_session(db, row, now=None):
    row.revoked_at = now or utcnow()


def revoke_user_sessions(db, user_id, now=None):
    db.execute(
        update(AuthSession)
        .where(AuthSession.user_id == user_id, AuthSession.revoked_at.is_(None))
        .values(revoked_at=now or utcnow())
    )


class AuthProvider(Protocol):
    def current_user(self, db, request) -> CurrentUser | None: ...


class SessionCookieProvider:
    def __init__(self, settings, clock=utcnow):
        self.settings, self.clock = settings, clock

    def current_user(self, db, request):
        token = request.cookies.get(COOKIE)
        if not token:
            return None
        loaded = load_session(db, token, self.settings, self.clock())
        if loaded is None:
            return None
        row, user = loaded
        db.commit()  # persists the slid idle timer (a no-op when nothing changed)
        return CurrentUser(user.id, user.email, user.name, user.role, row.csrf_token, row.id)
