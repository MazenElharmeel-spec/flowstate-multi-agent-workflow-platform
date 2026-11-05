"""Workflow run lifecycle management: creation, status transitions, cancellation, and replay."""

from datetime import UTC, datetime
from typing import Any

import jsonschema
from sqlalchemy import desc, func, select

from backend.app.core.errors import PermanentError
from backend.app.db.models import AuditLog, CheckpointRecord, User, WorkflowDefinition, WorkflowRun
from backend.app.db.session import async_session_factory
from backend.app.observability.metrics import RETRIES_TOTAL
from backend.app.orchestration.events import event_bus


class RunLifecycleManager:
    async def create_run(
        self,
        workflow_key: str,
        inputs: dict[str, Any],
        initiated_by: User | None = None,
        workflow_version: int | None = None,
    ) -> WorkflowRun:
        """Validate input schema and enqueue a new workflow run."""
        async with async_session_factory() as session:
            # Fetch active workflow definition
            stmt = select(WorkflowDefinition).where(WorkflowDefinition.key == workflow_key)
            if workflow_version:
                stmt = stmt.where(WorkflowDefinition.version == workflow_version)
            else:
                stmt = stmt.order_by(desc(WorkflowDefinition.version))

            result = await session.execute(stmt)
            definition = result.scalars().first()

            if not definition:
                raise PermanentError(
                    f"Workflow '{workflow_key}' (v{workflow_version or 'latest'}) not found"
                )

            # Validate inputs against definition's input_schema
            if definition.input_schema:
                try:
                    jsonschema.validate(instance=inputs, schema=definition.input_schema)
                except jsonschema.ValidationError as err:
                    raise PermanentError(
                        f"Input validation failed for workflow '{workflow_key}': {err.message}",
                        details={"path": list(err.path), "error": err.message},
                    ) from err

            now = datetime.now(UTC)
            run = WorkflowRun(
                workflow_definition_id=definition.id,
                workflow_version=definition.version,
                status="queued",
                inputs=inputs,
                outputs={},
                state_snapshot={},
                current_node=None,
                initiated_by_id=initiated_by.id if initiated_by else None,
                created_at=now,
            )
            session.add(run)
            await session.commit()
            await session.refresh(run)

            # Audit log
            audit = AuditLog(
                run_id=run.id,
                user_id=initiated_by.id if initiated_by else None,
                action="run.created",
                details={"workflow_key": workflow_key, "version": definition.version},
                timestamp=now,
            )
            session.add(audit)
            await session.commit()

        # Emit event
        await event_bus.publish(
            run_id=run.id,
            event_type="run.queued",
            payload={"workflow_key": workflow_key, "version": run.workflow_version, "inputs": inputs},
        )

        return run

    async def get_run(self, run_id: str) -> WorkflowRun:
        async with async_session_factory() as session:
            result = await session.execute(select(WorkflowRun).where(WorkflowRun.id == run_id))
            run = result.scalar_one_or_none()
            if not run:
                raise PermanentError(f"Run '{run_id}' not found", details={"run_id": run_id})
            return run

    async def list_runs(
        self,
        status: str | None = None,
        workflow_key: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[WorkflowRun], int]:
        async with async_session_factory() as session:
            stmt = select(WorkflowRun)
            count_stmt = select(func.count(WorkflowRun.id))

            if status:
                stmt = stmt.where(WorkflowRun.status == status)
                count_stmt = count_stmt.where(WorkflowRun.status == status)

            if workflow_key:
                # Join definition to filter by key
                stmt = stmt.join(WorkflowDefinition).where(WorkflowDefinition.key == workflow_key)
                count_stmt = count_stmt.join(WorkflowDefinition).where(
                    WorkflowDefinition.key == workflow_key
                )

            stmt = stmt.order_by(desc(WorkflowRun.created_at)).limit(limit).offset(offset)

            runs_res = await session.execute(stmt)
            count_res = await session.execute(count_stmt)

            runs = list(runs_res.scalars().all())
            total = int(count_res.scalar() or 0)
            return runs, total

    async def cancel_run(
        self,
        run_id: str,
        reason: str = "User requested cancellation",
        user_id: str | None = None,
    ) -> WorkflowRun:
        async with async_session_factory() as session:
            result = await session.execute(select(WorkflowRun).where(WorkflowRun.id == run_id))
            run = result.scalar_one_or_none()
            if not run:
                raise PermanentError(f"Run '{run_id}' not found")

            if run.status in ("completed", "failed", "cancelled", "timed_out"):
                raise PermanentError(f"Cannot cancel run in terminal state '{run.status}'")

            run.status = "cancelled"
            run.finished_at = datetime.now(UTC)
            await session.commit()
            await session.refresh(run)

            audit = AuditLog(
                run_id=run.id,
                user_id=user_id,
                action="run.cancelled",
                details={"reason": reason},
            )
            session.add(audit)
            await session.commit()

        await event_bus.publish(
            run_id=run_id,
            event_type="run.cancelled",
            payload={"reason": reason, "cancelled_by": user_id},
        )
        return run

    async def retry_run(self, run_id: str, initiated_by: User | None = None) -> WorkflowRun:
        """Create a new version-pinned run from a failed run's validated inputs."""
        async with async_session_factory() as session:
            result = await session.execute(select(WorkflowRun).where(WorkflowRun.id == run_id))
            previous = result.scalar_one_or_none()
            if previous is None:
                raise PermanentError(f"Run '{run_id}' not found")
            if previous.status != "failed":
                raise PermanentError(f"Only failed runs can be retried; got '{previous.status}'")
            definition_result = await session.execute(
                select(WorkflowDefinition).where(
                    WorkflowDefinition.id == previous.workflow_definition_id
                )
            )
            definition = definition_result.scalar_one_or_none()
            if definition is None:
                raise PermanentError(f"Definition {previous.workflow_definition_id} not found")
            workflow_key = definition.key
            workflow_version = previous.workflow_version
            inputs = dict(previous.inputs or {})

        RETRIES_TOTAL.inc()
        return await self.create_run(
            workflow_key,
            inputs,
            initiated_by=initiated_by,
            workflow_version=workflow_version,
        )

    async def get_run_checkpoints(self, run_id: str) -> list[dict[str, Any]]:
        async with async_session_factory() as session:
            stmt = (
                select(CheckpointRecord)
                .where(CheckpointRecord.thread_id == run_id)
                .order_by(desc(CheckpointRecord.created_at))
            )
            res = await session.execute(stmt)
            records = res.scalars().all()
            return [
                {
                    "checkpoint_id": r.checkpoint_id,
                    "parent_checkpoint_id": r.parent_checkpoint_id,
                    "metadata": r.metadata_data,
                    "created_at": r.created_at.isoformat(),
                }
                for r in records
            ]


run_lifecycle = RunLifecycleManager()
