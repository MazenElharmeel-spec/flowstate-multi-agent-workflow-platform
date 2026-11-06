"""FastAPI application initialization, middleware, and lifecycle."""

import os
import time
import uuid
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, cast

from fastapi import FastAPI, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from backend.app.api.approvals import router as approvals_router
from backend.app.api.auth import router as auth_router
from backend.app.api.health import router as health_router
from backend.app.api.runs import router as runs_router
from backend.app.api.tools import router as tools_router
from backend.app.api.workflows import router as workflows_router
from backend.app.core.config import get_settings
from backend.app.core.errors import WorkflowEngineError
from backend.app.core.logging import setup_logging
from backend.app.db.seed import seed_database
from backend.app.observability.tracing import setup_tracing
from backend.app.orchestration.events import event_bus
from backend.app.tools.mcp_client import mcp_manager
from backend.app.tools.setup import register_native_tools, setup_mcp_clients

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    # Startup
    setup_logging(level=settings.LOG_LEVEL)
    setup_tracing(app)
    await event_bus.start(listen=True)
    try:
        if "sqlite" in settings.DATABASE_URL:
            await seed_database()
        register_native_tools()
        setup_mcp_clients()
        await mcp_manager.initialize_all()
        yield
    finally:
        await event_bus.stop()


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
app.include_router(tools_router, prefix="/api/v1")
app.include_router(workflows_router, prefix="/api/v1")
app.include_router(runs_router, prefix="/api/v1")
app.include_router(approvals_router, prefix="/api/v1")

# The hosted demo image includes the React build and serves it from the same
# origin as the API. Local Compose continues to use the separate Nginx web tier.
frontend_dist = Path(__file__).resolve().parents[2] / "frontend" / "dist"
if os.getenv("SERVE_FRONTEND", "false").lower() == "true" and frontend_dist.is_dir():
    app.mount("/", StaticFiles(directory=frontend_dist, html=True), name="frontend")
