"""Approval inbox and decision endpoints."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.api.deps import get_current_user, get_db, require_role
from backend.app.api.schemas import ApprovalDecisionRequest, ApprovalRequestOut
from backend.app.approvals.service import approval_service
from backend.app.core.security import Role
from backend.app.db.models import ApprovalRequest, User

router = APIRouter(prefix="/approvals", tags=["Approvals"])


@router.get("", response_model=list[ApprovalRequestOut])
async def list_approvals(
    current_user: Annotated[User, Depends(get_current_user)],
    status: str | None = Query(None, description="Filter by pending/approved/rejected/edited/expired"),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
) -> list[ApprovalRequest]:
    """Retrieve pending or past approval requests."""
    return await approval_service.list_approvals(status=status, limit=limit, offset=offset)


@router.get("/{approval_id}", response_model=ApprovalRequestOut)
async def get_approval(
    approval_id: str,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApprovalRequest:
    """Retrieve single approval request by ID."""
    stmt = select(ApprovalRequest).where(ApprovalRequest.id == approval_id)
    res = await db.execute(stmt)
    approval = res.scalar_one_or_none()
    if not approval:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Approval request '{approval_id}' not found",
        )
    return approval


@router.post("/{approval_id}/decide", response_model=ApprovalRequestOut)
async def decide_approval(
    approval_id: str,
    payload: ApprovalDecisionRequest,
    current_user: Annotated[User, Depends(require_role(Role.APPROVER))],
    request: Request,
) -> ApprovalRequest:
    """Submit approval decision: approve, reject, or edit arguments."""
    ip_address = request.client.host if request.client else None
    approval, _ = await approval_service.decide(
        approval_id=approval_id,
        decision=payload.decision,
        decided_by=current_user,
        rejection_reason=payload.rejection_reason,
        edited_arguments=payload.edited_arguments,
        ip_address=ip_address,
    )
    return approval
