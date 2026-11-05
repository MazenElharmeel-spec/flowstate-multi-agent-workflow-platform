"""Workflow run execution, inspection, cancellation, and live streaming endpoints."""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.api.deps import get_current_user, get_db, require_role
from backend.app.api.schemas import RunEventOut, WorkflowRunCreate, WorkflowRunOut
from backend.app.core.security import Role
from backend.app.db.models import RunEvent, User, WorkflowRun
from backend.app.orchestration.events import event_bus
from backend.app.orchestration.lifecycle import run_lifecycle

router = APIRouter(prefix="/runs", tags=["Workflow Runs"])


@router.post("", response_model=WorkflowRunOut, status_code=status.HTTP_202_ACCEPTED)
async def create_run(
    payload: WorkflowRunCreate,
    current_user: Annotated[User, Depends(require_role(Role.OPERATOR))],
) -> WorkflowRun:
    """Enqueue a new workflow execution."""
    run = await run_lifecycle.create_run(
        workflow_key=payload.workflow_key,
        inputs=payload.inputs,
        initiated_by=current_user,
        workflow_version=payload.workflow_version,
    )
    return run


@router.get("", response_model=list[WorkflowRunOut])
async def list_runs(
    current_user: Annotated[User, Depends(get_current_user)],
    status: str | None = Query(None, description="Filter by run status"),
    workflow: str | None = Query(None, description="Filter by workflow key"),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
) -> list[WorkflowRun]:
    """List workflow runs with optional status and workflow filters."""
    runs, _ = await run_lifecycle.list_runs(
        status=status, workflow_key=workflow, limit=limit, offset=offset
    )
    return runs


@router.get("/{run_id}", response_model=WorkflowRunOut)
async def get_run(
    run_id: str,
    current_user: Annotated[User, Depends(get_current_user)],
) -> WorkflowRun:
    """Retrieve detailed state and metadata for a specific run."""
    return await run_lifecycle.get_run(run_id)


@router.get("/{run_id}/events", response_model=list[RunEventOut])
async def get_run_events(
    run_id: str,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[RunEvent]:
    """Retrieve full append-only execution event log for a run."""
    stmt = (
        select(RunEvent)
        .where(RunEvent.run_id == run_id)
        .order_by(RunEvent.sequence_number)
    )
    res = await db.execute(stmt)
    return list(res.scalars().all())


@router.get("/{run_id}/checkpoints")
async def get_run_checkpoints(
    run_id: str,
    current_user: Annotated[User, Depends(get_current_user)],
) -> list[dict[str, Any]]:
    """Retrieve list of checkpoints for time travel and replay."""
    return await run_lifecycle.get_run_checkpoints(run_id)


@router.get("/{run_id}/stream")
async def stream_run_events(
    run_id: str,
    current_user: Annotated[User, Depends(get_current_user)],
) -> StreamingResponse:
    """Stream live run events in real-time via Server-Sent Events (SSE)."""
    return StreamingResponse(
        event_bus.subscribe(run_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/{run_id}/cancel", response_model=WorkflowRunOut)
async def cancel_run(
    run_id: str,
    current_user: Annotated[User, Depends(require_role(Role.OPERATOR))],
    reason: str = "User requested cancellation",
) -> WorkflowRun:
    """Cancel an active or queued workflow run."""
    return await run_lifecycle.cancel_run(run_id, reason=reason, user_id=current_user.id)
