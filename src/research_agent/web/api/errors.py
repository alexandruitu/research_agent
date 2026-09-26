"""One error shape for every failure: {"code", "message", "request_id"} (+ "fields" for 422)."""

import logging
import re
import traceback
from uuid import uuid4

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from ..runner import redact

log = logging.getLogger("research_agent.web")
REQUEST_ID = re.compile(r"[A-Za-z0-9._-]{1,64}")
CODES = {
    401: "unauthorized",
    403: "forbidden",
    404: "not_found",
    405: "method_not_allowed",
    409: "conflict",
    429: "rate_limited",
}


class ApiError(Exception):
    def __init__(self, status, code, message):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


def _body(request, code, message, **extra):
    return {
        "code": code,
        "message": message,
        "request_id": _request_id(request),
        **extra,
    }


SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "Cache-Control": "no-store",
    "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'",
    "Referrer-Policy": "no-referrer",
}


def _request_id(request):
    return getattr(request.state, "request_id", "-")


def _internal_error(request, exc):
    """Log a redacted traceback (never a secret's value) and answer a bare 500 carrying the usual headers.
    The traceback is formatted and redacted here, not handed to the logger as exc_info."""
    trace = "".join(traceback.format_exception(exc))
    log.error("unhandled error, request %s\n%s", _request_id(request), redact(trace))
    response = JSONResponse(_body(request, "internal_error", "Unexpected error"), status_code=500)
    response.headers.update(SECURITY_HEADERS)
    response.headers["X-Request-ID"] = _request_id(request)
    return response


def install_error_handlers(app):
    # Registered first, so innermost: an unexpected error becomes a response here and still passes through
    # the request-id and security-header middlewares below. It is not re-raised, so the server never logs
    # the raw (unredacted) traceback either.
    @app.middleware("http")
    async def unexpected_errors(request: Request, call_next):
        try:
            return await call_next(request)
        except Exception as exc:  # noqa: BLE001 -- API boundary: a redacted log and a bare 500
            return _internal_error(request, exc)

    @app.middleware("http")
    async def request_id(request: Request, call_next):
        rid = request.headers.get("x-request-id", "")
        if not REQUEST_ID.fullmatch(rid):  # never echo arbitrary client text into headers and logs
            rid = uuid4().hex[:16]
        request.state.request_id = rid
        response = await call_next(request)
        response.headers["X-Request-ID"] = rid
        return response

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers.update(SECURITY_HEADERS)
        return response

    @app.exception_handler(ApiError)
    async def api_error(request, exc):
        return JSONResponse(_body(request, exc.code, exc.message), status_code=exc.status)

    @app.exception_handler(StarletteHTTPException)
    async def http_error(request, exc):
        return JSONResponse(
            _body(request, CODES.get(exc.status_code, "error"), str(exc.detail)), status_code=exc.status_code
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, exc):
        fields = [{"loc": ".".join(str(p) for p in e["loc"]), "message": e["msg"]} for e in exc.errors()]
        return JSONResponse(
            _body(request, "validation_error", "Request validation failed", fields=fields), status_code=422
        )

    @app.exception_handler(Exception)
    async def unexpected(request, exc):
        # Last resort (an error in a middleware itself): same redacted log and headers.
        return _internal_error(request, exc)
