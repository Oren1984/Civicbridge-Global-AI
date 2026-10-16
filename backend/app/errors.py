from __future__ import annotations

from fastapi import Request
from fastapi.responses import JSONResponse


class AppError(Exception):
    def __init__(self, status: int, code: str, message: str, extra: dict | None = None):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.extra = extra or {}


def forbidden(message: str = "You do not have access to this resource.", code: str = "forbidden") -> AppError:
    return AppError(403, code, message)


def not_found(message: str = "Not found.") -> AppError:
    # Used for resources outside the caller's authorization context too, to avoid existence leaks.
    return AppError(404, "not_found", message)


def bad_request(message: str, code: str = "invalid_request", extra: dict | None = None) -> AppError:
    return AppError(400, code, message, extra)


def conflict(message: str, code: str = "conflict", extra: dict | None = None) -> AppError:
    return AppError(409, code, message, extra)


async def app_error_handler(_request: Request, exc: AppError) -> JSONResponse:
    return JSONResponse(status_code=exc.status, content={"error": {"code": exc.code, "message": exc.message, **exc.extra}})
