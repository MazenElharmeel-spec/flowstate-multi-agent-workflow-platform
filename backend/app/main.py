"""FastAPI application initialization, middleware, and lifecycle."""

import time
import uuid
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any, cast

from fastapi import FastAPI, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from backend.app.api.auth import router as auth_router
from backend.app.api.health import router as health_router
from backend.app.core.config import get_settings
from backend.app.core.errors import WorkflowEngineError
from backend.app.core.logging import setup_logging
from backend.app.db.session import init_db

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    # Startup
    setup_logging(level=settings.LOG_LEVEL)
    if "sqlite" in settings.DATABASE_URL:
        await init_db()
    yield
    # Shutdown


app = FastAPI(
    title=settings.PROJECT_NAME,
    version="0.1.0",
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
    lifespan=lifespan,
)

# CORS Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Restricted in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Correlation ID and Request Timing Middleware
@app.middleware("http")
async def add_correlation_and_timing(request: Request, call_next: Any) -> Response:
    trace_id = request.headers.get("X-Trace-Id", str(uuid.uuid4()))
    request.state.trace_id = trace_id
    start_time = time.perf_counter()

    response = await call_next(request)

    duration_ms = (time.perf_counter() - start_time) * 1000
    res = cast(Response, response)
    res.headers["X-Trace-Id"] = trace_id
    res.headers["X-Response-Time-Ms"] = f"{duration_ms:.2f}"
    return res


# Global Exception Handlers
@app.exception_handler(WorkflowEngineError)
async def workflow_engine_error_handler(request: Request, exc: WorkflowEngineError) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_400_BAD_REQUEST,
        content={
            "error": exc.__class__.__name__,
            "message": exc.message,
            "details": exc.details,
            "trace_id": getattr(request.state, "trace_id", None),
        },
    )


# Mount Top-level & API routers
app.include_router(health_router)
app.include_router(auth_router, prefix="/api/v1")
