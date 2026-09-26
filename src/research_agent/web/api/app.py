from fastapi import FastAPI

from ..auth import SessionCookieProvider
from ..db.session import make_engine, make_session_factory
from ..security import RateLimiter
from ..settings import load_settings
from .errors import install_error_handlers
from .routers import auth

API_PREFIX = "/api/v1"


def create_app(settings=None, session_factory=None):
    settings = settings or load_settings()
    if session_factory is None:
        session_factory = make_session_factory(make_engine(settings.database_url))
    # Docs and the schema URL are off (default deny); `research-web openapi` dumps the schema offline.
    app = FastAPI(title="Research Agent", version="1", docs_url=None, redoc_url=None, openapi_url=None)
    app.state.settings = settings
    app.state.session_factory = session_factory
    app.state.rate_limiter = RateLimiter(settings.login_max_attempts, settings.login_window_seconds)
    app.state.auth_provider = SessionCookieProvider(settings)
    install_error_handlers(app)
    app.include_router(auth.router, prefix=API_PREFIX)
    return app
