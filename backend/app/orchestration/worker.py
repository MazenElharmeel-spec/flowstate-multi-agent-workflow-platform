"""Background workflow execution worker process with crash-resilience and checkpoint resumption."""

import asyncio
import logging
import signal
from contextlib import suppress
from typing import Any

from sqlalchemy import select, update

from backend.app.core.config import get_settings
from backend.app.core.logging import setup_logging
from backend.app.db.models import ApprovalRequest, WorkflowRun
from backend.app.db.session import async_session_factory
from backend.app.orchestration.runner import runner
from backend.app.tools.mcp_client import mcp_manager
from backend.app.tools.setup import register_native_tools, setup_mcp_clients

logger = logging.getLogger(__name__)
settings = get_settings()


class WorkflowWorker:
    def __init__(self) -> None:
        self._running = False
        self._current_tasks: set[asyncio.Task[Any]] = set()

    async def start(self) -> None:
        self._running = True
        register_native_tools()
        setup_mcp_clients()
        await mcp_manager.initialize_all()
        # A worker may have died while a run was marked running. Graph checkpoints
        # and idempotency keys make re-queueing safe; the runner resumes its thread.
        async with async_session_factory() as session:
            await session.execute(
                update(WorkflowRun).where(WorkflowRun.status == "running").values(status="queued")
            )
            await session.commit()
        logger.info("Workflow worker started. Polling for queued workflow runs...")

        while self._running:
            try:
                await self._process_next_batch()
            except Exception as exc:
                logger.error("Error in worker polling loop: %s", exc)

            await asyncio.sleep(1.0)

    async def _process_next_batch(self) -> None:
        """Fetch next queued runs and execute them concurrently."""
        async with async_session_factory() as session:
            # Select queued runs
            stmt = (
                select(WorkflowRun)
                .where(WorkflowRun.status == "queued")
                .order_by(WorkflowRun.created_at)
                .limit(5)
            )
            res = await session.execute(stmt)
            queued_runs = res.scalars().all()
            run_ids: list[str] = []
            for queued_run in queued_runs:
                claim = await session.execute(
                    update(WorkflowRun)
                    .where(WorkflowRun.id == queued_run.id, WorkflowRun.status == "queued")
                    .values(status="running")
                    .returning(WorkflowRun.id)
                )
                claimed_id = claim.scalar_one_or_none()
                if claimed_id:
                    run_ids.append(claimed_id)
            await session.commit()

        for rid in run_ids:
            task = asyncio.create_task(self._safe_execute(rid))
            self._current_tasks.add(task)
            task.add_done_callback(self._current_tasks.discard)

    async def _safe_execute(self, run_id: str) -> None:
        logger.info("Worker picking up run %s", run_id)
        try:
            resume_value = await self._pending_resume_value(run_id)
            await runner.execute_run(run_id, resume_value=resume_value)
        except Exception as exc:
            logger.error("Worker execution failed for run %s: %s", run_id, exc)

    async def _pending_resume_value(self, run_id: str) -> dict[str, Any] | None:
        """Rebuild a resume command from the durable approval decision."""
        async with async_session_factory() as session:
            result = await session.execute(
                select(ApprovalRequest)
                .where(
                    ApprovalRequest.run_id == run_id,
                    ApprovalRequest.status.in_(("approved", "edited", "rejected")),
                )
                .order_by(ApprovalRequest.decided_at.desc())
                .limit(1)
            )
            approval = result.scalar_one_or_none()
            if approval is None:
                return None
            return {
                "status": approval.status,
                "resolved_arguments": approval.resolved_arguments,
                "rejection_reason": approval.rejection_reason,
            }

    async def resume_run(self, run_id: str, resume_value: dict[str, Any]) -> None:
        """Explicitly resume an interrupted run following approval/rejection decision."""
        logger.info("Worker resuming interrupted run %s with decision", run_id)
        task = asyncio.create_task(runner.execute_run(run_id, resume_value=resume_value))
        self._current_tasks.add(task)
        task.add_done_callback(self._current_tasks.discard)

    def stop(self) -> None:
        logger.info("Stopping workflow worker...")
        self._running = False


worker = WorkflowWorker()


async def run_worker() -> None:
    setup_logging(level=settings.LOG_LEVEL)
    loop = asyncio.get_running_loop()

    for sig in (signal.SIGINT, signal.SIGTERM):
        with suppress(NotImplementedError):
            loop.add_signal_handler(sig, worker.stop)

    await worker.start()


if __name__ == "__main__":
    asyncio.run(run_worker())
