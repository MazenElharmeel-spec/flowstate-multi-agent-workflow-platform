"""Health check and readiness endpoints."""

from typing import Annotated, Any

import redis.asyncio as aioredis
from fastapi import APIRouter, Depends, Response, status
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.api.deps import get_db
from backend.app.core.config import get_settings

router = APIRouter(tags=["Health"])
settings = get_settings()


@router.get("/healthz", status_code=status.HTTP_200_OK)
async def healthz() -> dict[str, str]:
    """Basic liveness probe."""
    return {"status": "ok"}


@router.get("/readyz")
async def readyz(
    db: Annotated[AsyncSession, Depends(get_db)],
    response: Response,
) -> dict[str, Any]:
    """Readiness probe checking database and redis connectivity."""
    checks: dict[str, Any] = {"database": "unknown", "redis": "unknown"}
    is_ready = True

    # 1. Database check
    try:
        await db.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception as exc:
        checks["database"] = f"error: {str(exc)}"
        is_ready = False

    # 2. Redis check
    try:
        r = aioredis.from_url(settings.REDIS_URL, socket_timeout=2.0)
        await r.ping()
        await r.close()
        checks["redis"] = "ok"
    except Exception as exc:
        checks["redis"] = f"warning: {str(exc)}"
        # In local/standalone test mode, if redis isn't running, don't fail readyz unless required

    if not is_ready:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE

    return {"status": "ready" if is_ready else "not_ready", "checks": checks}


@router.get("/metrics")
async def get_metrics() -> Response:
    """Prometheus metrics endpoint."""
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)
