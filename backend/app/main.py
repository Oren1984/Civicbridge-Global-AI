"""CivicBridge Global AI - FastAPI modular monolith."""
from __future__ import annotations

import logging
import time
import uuid

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app import logging_setup
from app.errors import AppError, app_error_handler
from app.routers import (
    ai,
    auth,
    authority,
    cases,
    consent,
    documents,
    governance,
    incidents,
    life_events,
    meetings,
    notifications,
    privacy,
    public,
    rights,
    sync,
    translations,
    workspaces,
)

logging_setup.setup()
log = logging.getLogger("civicbridge.http")

app = FastAPI(
    title="CivicBridge Global AI API",
    version="1.0.0",
    description="Citizen-controlled civic continuity platform (local synthetic demo). "
    "Authority exchanges are simulated; nothing here is an official government submission.",
    docs_url="/api/docs",
    redoc_url=None,
    openapi_url="/api/openapi.json",
)
app.add_exception_handler(AppError, app_error_handler)


@app.exception_handler(RequestValidationError)
async def validation_handler(_request: Request, exc: RequestValidationError) -> JSONResponse:
    errors = [{"field": ".".join(str(x) for x in e.get("loc", [])[1:]), "message": e.get("msg", "")} for e in exc.errors()][:20]
    return JSONResponse(status_code=422, content={"error": {"code": "validation_error", "message": "Some fields are invalid.", "fields": errors}})


@app.exception_handler(Exception)
async def unhandled(_request: Request, exc: Exception) -> JSONResponse:
    log.exception("unhandled error")
    return JSONResponse(status_code=500, content={"error": {"code": "internal_error", "message": "Something went wrong. Please try again."}})


@app.middleware("http")
async def headers_and_logging(request: Request, call_next):
    rid = uuid.uuid4().hex[:12]
    start = time.monotonic()
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Cache-Control", "no-store")
    response.headers["X-Request-Id"] = rid
    if request.url.path.startswith("/api/") and not request.url.path.startswith("/api/health"):
        log.info("request", extra={"method": request.method, "path": request.url.path, "status": response.status_code,
                                   "duration_ms": int((time.monotonic() - start) * 1000), "request_id": rid})
    return response


for r in (public, auth, workspaces, cases, life_events, documents, consent, authority, incidents, rights, ai, translations,
          meetings, notifications, sync, privacy, governance):
    app.include_router(r.router)
