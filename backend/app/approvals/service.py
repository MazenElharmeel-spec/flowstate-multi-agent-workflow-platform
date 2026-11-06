"""Approval service managing human-in-the-loop decisions, argument editing, and expiry."""

import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, Literal, cast

from sqlalchemy import select

from backend.app.approvals.policy_engine import policy_engine
from backend.app.core.errors import ApprovalExpiredError, PermanentError
from backend.app.core.security import Role, has_permission
from backend.app.db.models import ApprovalRequest, AuditLog, User, WorkflowRun
from backend.app.db.session import async_session_factory
from backend.app.observability.metrics import APPROVAL_WAIT_SECONDS
from backend.app.orchestration.events import event_bus
from backend.app.orchestration.state import WorkflowState
from backend.app.tools.registry import tool_registry


class ApprovalService:
    async def create_approval_request(
        self,
        run_id: str,
        tool_name: str,
        arguments: dict[str, Any],
        risk_level: str,
        reason: str,
        checkpoint_id: str | None = None,
        expires_minutes: int = 120,
    ) -> ApprovalRequest:
        now = datetime.now(UTC)
        expires_at = now + timedelta(minutes=expires_minutes)
        approval_id = str(
            uuid.uuid5(
                uuid.NAMESPACE_URL,
                f"{run_id}:{tool_name}:{json.dumps(arguments, sort_keys=True)}",
            )
        )

        async with async_session_factory() as session:
            existing = await session.get(ApprovalRequest, approval_id)
            if existing is not None:
                return existing
            approval = ApprovalRequest(
                id=approval_id,
                run_id=run_id,
                checkpoint_id=checkpoint_id,
                tool_name=tool_name,
                original_arguments=arguments,
                resolved_arguments=arguments,
                risk_level=risk_level,
                reason=reason,
                status="pending",
                expires_at=expires_at,
                created_at=now,
            )
            session.add(approval)

            # Update run status to waiting_approval
            run_res = await session.execute(select(WorkflowRun).where(WorkflowRun.id == run_id))
            run = run_res.scalar_one_or_none()
            if run:
                run.status = "waiting_approval"

            await session.commit()
            await session.refresh(approval)

        await event_bus.publish(
            run_id=run_id,
            event_type="approval.requested",
            payload={
                "approval_id": approval.id,
                "tool_name": tool_name,
                "arguments": arguments,
                "risk_level": risk_level,
                "reason": reason,
                "expires_at": expires_at.isoformat(),
            },
        )
        return approval

    async def decide(
        self,
        approval_id: str,
        decision: Literal["approve", "reject", "edit"],
        decided_by: User,
        rejection_reason: str | None = None,
        edited_arguments: dict[str, Any] | None = None,
        ip_address: str | None = None,
    ) -> tuple[ApprovalRequest, dict[str, Any]]:
        # 1. Verify user role has approve permission
        if not has_permission(Role(decided_by.role), "approve"):
            raise PermanentError("User does not possess approver permissions")

        now = datetime.now(UTC)

        async with async_session_factory() as session:
            stmt = select(ApprovalRequest).where(ApprovalRequest.id == approval_id)
            res = await session.execute(stmt)
            approval = res.scalar_one_or_none()

            if not approval:
                raise PermanentError(f"Approval request '{approval_id}' not found")

            # Check single-use guarantee
            if approval.status != "pending":
                raise PermanentError(
                    f"Approval request already resolved with status '{approval.status}'"
                )

            # Check expiry
            if now > approval.expires_at.replace(tzinfo=UTC):
                approval.status = "expired"
                await session.commit()
                raise ApprovalExpiredError(approval_id)

            resolved_args = approval.original_arguments
            status_to_set = "approved"

            if decision == "reject":
                status_to_set = "rejected"
                approval.rejection_reason = (
                    rejection_reason or "Declined by supervisor without explicit note"
                )

            elif decision == "edit":
                if not edited_arguments:
                    raise PermanentError("Edited arguments must be provided when choosing 'edit'")
                status_to_set = "edited"

                # Re-validate edited arguments against tool schema
                tool = tool_registry.get(approval.tool_name)
                tool.validate_arguments(edited_arguments)

                # Re-check policy with edited arguments
                run_res = await session.execute(
                    select(WorkflowRun).where(WorkflowRun.id == approval.run_id)
                )
                run = run_res.scalar_one_or_none()
                run_state = (run.state_snapshot if run else {}) or {}

                policy_eval = policy_engine.evaluate_tool_call(
                    approval.tool_name, edited_arguments, cast(WorkflowState, run_state)
                )
                if policy_eval.rule_name == "PROMPT_INJECTION_DEFENSE":
                    raise PermanentError(f"Edited arguments failed policy check: {policy_eval.reason}")

                resolved_args = edited_arguments

            approval.status = status_to_set
            approval.resolved_arguments = resolved_args
            approval.decided_by_id = decided_by.id
            approval.decided_at = now

            # Audit record
            audit = AuditLog(
                run_id=approval.run_id,
                user_id=decided_by.id,
                action=f"approval.{status_to_set}",
                details={
                    "approval_id": approval.id,
                    "tool_name": approval.tool_name,
                    "original_args": approval.original_arguments,
                    "resolved_args": resolved_args,
                    "rejection_reason": approval.rejection_reason,
                },
                ip_address=ip_address,
                timestamp=now,
            )
            session.add(audit)
            run_res = await session.execute(
                select(WorkflowRun).where(WorkflowRun.id == approval.run_id)
            )
            run = run_res.scalar_one_or_none()
            if run and decision in ("approve", "reject", "edit"):
                # The worker polls queued runs and reconstructs the resume payload
                # from this durable approval record after a restart.
                run.status = "queued"
                run.worker_id = None
                run.lease_expires_at = None
            await session.commit()
            await session.refresh(approval)

        # Notify event bus
        await event_bus.publish(
            run_id=approval.run_id,
            event_type="approval.resolved",
            payload={
                "approval_id": approval.id,
                "decision": status_to_set,
                "decided_by": decided_by.email,
                "resolved_arguments": resolved_args,
            },
        )
        if approval.created_at is not None:
            created_at = approval.created_at
            if created_at.tzinfo is None:
                created_at = created_at.replace(tzinfo=UTC)
            APPROVAL_WAIT_SECONDS.observe((now - created_at).total_seconds())

        decision_payload = {
            "status": status_to_set,
            "resolved_arguments": resolved_args,
            "rejection_reason": approval.rejection_reason,
        }

        return approval, decision_payload

    async def list_approvals(
        self,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[ApprovalRequest]:
        async with async_session_factory() as session:
            stmt = select(ApprovalRequest)
            if status:
                stmt = stmt.where(ApprovalRequest.status == status)
            stmt = stmt.order_by(ApprovalRequest.created_at.desc()).limit(limit).offset(offset)
            res = await session.execute(stmt)
            return list(res.scalars().all())


approval_service = ApprovalService()
