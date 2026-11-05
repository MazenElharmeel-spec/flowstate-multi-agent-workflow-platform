"""Workflow definition management endpoints."""

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.api.deps import get_current_user, get_db, require_role
from backend.app.api.schemas import WorkflowDefinitionCreate, WorkflowDefinitionOut
from backend.app.core.security import Role
from backend.app.db.models import User, WorkflowDefinition

router = APIRouter(prefix="/workflows", tags=["Workflows"])


@router.get("", response_model=list[WorkflowDefinitionOut])
async def list_workflows(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[WorkflowDefinition]:
    """List all workflow definitions and their latest versions."""
    stmt = (
        select(WorkflowDefinition)
        .where(WorkflowDefinition.is_active == True)  # noqa: E712
        .order_by(WorkflowDefinition.key, desc(WorkflowDefinition.version))
    )
    res = await db.execute(stmt)
    return list(res.scalars().all())


@router.get("/{key}", response_model=WorkflowDefinitionOut)
async def get_workflow(
    key: str,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    version: int | None = None,
) -> WorkflowDefinition:
    """Get a specific workflow definition by key and optional version."""
    stmt = select(WorkflowDefinition).where(WorkflowDefinition.key == key)
    if version:
        stmt = stmt.where(WorkflowDefinition.version == version)
    else:
        stmt = stmt.order_by(desc(WorkflowDefinition.version))

    res = await db.execute(stmt)
    wf = res.scalars().first()
    if not wf:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Workflow definition '{key}' not found",
        )
    return wf


@router.post("", response_model=WorkflowDefinitionOut, status_code=status.HTTP_201_CREATED)
async def register_workflow(
    payload: WorkflowDefinitionCreate,
    current_user: Annotated[User, Depends(require_role(Role.ADMIN))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> WorkflowDefinition:
    """Register a new workflow or increment version of existing workflow (Admin only)."""
    # Check max existing version for this key
    stmt = (
        select(WorkflowDefinition)
        .where(WorkflowDefinition.key == payload.key)
        .order_by(desc(WorkflowDefinition.version))
    )
    res = await db.execute(stmt)
    latest = res.scalars().first()
    next_version = (latest.version + 1) if latest else 1

    wf = WorkflowDefinition(
        key=payload.key,
        version=next_version,
        name=payload.name,
        description=payload.description,
        input_schema=payload.input_schema,
        graph_definition=payload.graph_definition,
        is_active=True,
        created_at=datetime.now(UTC),
    )
    db.add(wf)
    await db.commit()
    await db.refresh(wf)
    return wf
