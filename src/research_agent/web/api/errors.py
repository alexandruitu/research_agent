"""One error shape for every failure: {"code", "message", "request_id"} (+ "fields" for 422)."""

import logging
from uuid import uuid4

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

log = logging.getLogger("research_agent.web")
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
        "request_id": getattr(request.state, "request_id", "-"),
        **extra,
    }


def install_error_handlers(app):
    @app.middleware("http")
    async def request_id(request: Request, call_next):
        rid = request.headers.get("x-request-id") or uuid4().hex[:16]
        request.state.request_id = rid
        response = await call_next(request)
        response.headers["X-Request-ID"] = rid
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
        log.exception("unhandled error, request %s", getattr(request.state, "request_id", "-"))
        return JSONResponse(_body(request, "internal_error", "Unexpected error"), status_code=500)
