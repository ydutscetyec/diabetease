from __future__ import annotations

import logging
import time
from contextlib import asynccontextmanager
from collections import defaultdict, deque

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from .config import get_settings
from .database import Base, engine
from .routers import admin, assessment, auth, chatbot, facilities, health

settings = get_settings()

# Log lines carry method, path and status only. No request bodies, no query values,
# because an assessment body is health information.
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("diabetease")

@asynccontextmanager
async def lifespan(_: FastAPI):
    Base.metadata.create_all(bind=engine)
    if not settings.admin_configured:
        log.warning("admin endpoints disabled: SECRET_KEY, ADMIN_USERNAME and "
                    "ADMIN_PASSWORD_HASH are not all set")
    yield
    from .services import llm as _llm
    await _llm.aclose()


app = FastAPI(
    lifespan=lifespan,
    title=settings.app_name,
    version=settings.build,
    description=(
        "Backend for DiabetEASE. The assessment endpoint returns a rule-based triage "
        "result against published diagnostic thresholds; it returns a model prediction "
        "only when an active, provenance-tagged artifact is loaded."
    ),
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
)

if settings.cors_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "DELETE"],
        allow_headers=["Authorization", "Content-Type"],
    )

_hits: dict[str, deque] = defaultdict(deque)


@app.middleware("http")
async def rate_limit_and_log(request: Request, call_next):
    """In-process fixed-window limiter. Single worker only; use a reverse proxy or
    Redis-backed limiter if you ever run more than one process."""
    if request.url.path.startswith("/api/"):
        key = request.client.host if request.client else "unknown"
        now = time.time()
        window = _hits[key]
        while window and now - window[0] > 60:
            window.popleft()
        # Drop clients that have gone quiet. Without this the table gains one
        # entry per address ever seen and never shrinks.
        if len(_hits) > 2000:
            for stale in [k for k, w in _hits.items() if not w or now - w[-1] > 60]:
                _hits.pop(stale, None)
        if len(window) >= settings.rate_limit_per_minute:
            return JSONResponse(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                content={"error": "rate_limited", "detail": "Too many requests. Wait a minute."},
            )
        window.append(now)

    response = await call_next(request)
    log.info("%s %s -> %s", request.method, request.url.path, response.status_code)
    return response


@app.exception_handler(RequestValidationError)
async def validation_handler(request: Request, exc: RequestValidationError):
    # Field names and messages only. Never echo submitted values back into a
    # response or a log, since those values are health information.
    return JSONResponse(
        status_code=422,
        content={
            "error": "validation_failed",
            "detail": "One or more fields were rejected.",
            "fields": [
                {"field": ".".join(str(p) for p in e["loc"][1:]), "message": e["msg"]}
                for e in exc.errors()
            ],
        },
    )


@app.exception_handler(Exception)
async def unhandled_handler(request: Request, exc: Exception):
    log.exception("unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"error": "internal_error",
                 "detail": "The server could not complete the request."},
    )


app.include_router(health.router)
app.include_router(assessment.router)
app.include_router(facilities.router)
app.include_router(chatbot.router)
app.include_router(admin.router)
app.include_router(auth.router)


# Static frontend last, so it never shadows an API route.
if settings.serve_frontend and settings.frontend_dir.is_dir():
    app.mount("/", StaticFiles(directory=str(settings.frontend_dir), html=True), name="frontend")
