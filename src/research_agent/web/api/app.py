from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse

from ..auth import SessionCookieProvider
from ..db.session import make_engine, make_session_factory
from ..security import RateLimiter
from ..settings import load_settings
from .errors import ApiError, install_error_handlers
from .routers import (
    admin,
    alerts,
    auth,
    authors,
    evals,
    fields,
    files,
    gold_sets,
    health,
    imports,
    jobs,
    library,
    me,
    papers,
    ratings,
    reader,
    review,
    runs,
    stages,
    users,
)

API_PREFIX = "/api/v1"
PREVIEWS_PER_MINUTE = 10


def create_app(settings=None, session_factory=None):
    settings = settings or load_settings()
    if session_factory is None:
        session_factory = make_session_factory(make_engine(settings.database_url))
    # Docs and the schema URL are off (default deny); `research-web openapi` dumps the schema offline.
    app = FastAPI(title="Research Agent", version="1", docs_url=None, redoc_url=None, openapi_url=None)
    app.state.settings = settings
    app.state.session_factory = session_factory
    app.state.rate_limiter = RateLimiter(settings.login_max_attempts, settings.login_window_seconds)
    app.state.login_ip_limiter = RateLimiter(settings.login_ip_max_attempts, settings.login_window_seconds)
    app.state.signup_limiter = RateLimiter(settings.signup_max_attempts, settings.signup_window_seconds)
    app.state.auth_provider = SessionCookieProvider(settings)
    app.state.preview_limiter = RateLimiter(PREVIEWS_PER_MINUTE, 60)  # per user, in-process
    install_error_handlers(app)
    app.include_router(auth.router, prefix=API_PREFIX)
    app.include_router(users.router, prefix=API_PREFIX)
    for module in (
        admin,
        review,
        fields,
        runs,
        papers,
        ratings,
        files,
        library,
        authors,
        reader,
        alerts,
        stages,
        evals,
        gold_sets,
        jobs,
        me,
        imports,
        health,
    ):
        app.include_router(module.router, prefix=API_PREFIX)
    if settings.static_dir:
        mount_frontend(app, settings.static_dir)
    return app


def mount_frontend(app, root):
    """Serve the built React app: real files under `root`, `index.html` for client-side routes. Unknown
    /api paths stay 404 JSON. Security headers (CSP) come from the `security_headers` middleware."""
    root = Path(root).resolve()
    index = root / "index.html"
    if not index.is_file():
        raise RuntimeError(f"RESEARCH_WEB_STATIC_DIR has no index.html: {root}")

    @app.get("/{path:path}", include_in_schema=False)
    def frontend(path: str):
        if path == "api" or path.startswith("api/"):
            raise ApiError(404, "not_found", "Not found")
        target = (root / path).resolve()
        if path and target.is_relative_to(root) and target.is_file():
            cache = "public, max-age=31536000, immutable" if path.startswith("assets/") else "no-cache"
            return FileResponse(target, headers={"Cache-Control": cache})
        return FileResponse(index, headers={"Cache-Control": "no-cache"})
