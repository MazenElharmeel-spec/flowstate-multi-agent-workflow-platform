"""Background workflow execution worker process with crash-resilience and checkpoint resumption."""

import asyncio
import logging
import signal
from contextlib import suppress
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from uuid import uuid4

from prometheus_client import start_http_server
from sqlalchemy import func, select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.config import get_settings
from backend.app.core.logging import setup_logging
from backend.app.db.models import ApprovalRequest, WorkflowRun
from backend.app.db.session import async_session_factory
from backend.app.observability.metrics import QUEUE_DEPTH
from backend.app.observability.tracing import setup_tracing
from backend.app.orchestration.events import event_bus
from backend.app.orchestration.runner import runner
from backend.app.tools.mcp_client import mcp_manager
from backend.app.tools.setup import register_native_tools, setup_mcp_clients

logger = logging.getLogger(__name__)
settings = get_settings()


class WorkflowWorker:
    def __init__(self) -> None:
        self._running = False
        self._current_tasks: set[asyncio.Task[Any]] = set()
        self.worker_id = uuid4().hex

    async def start(self) -> None:
        self._running = True
        setup_tracing()
        await event_bus.start()
        register_native_tools()
        setup_mcp_clients()
        await mcp_manager.initialize_all()
        await self._recover_expired_leases()
        logger.info("Workflow worker started. Polling for queued workflow runs...")

        while self._running:
            try:
                await self._process_next_batch()
            except Exception as exc:
                logger.error("Error in worker polling loop: %s", exc)

            await asyncio.sleep(1.0)

        if self._current_tasks:
            await asyncio.gather(*self._current_tasks, return_exceptions=True)
        await event_bus.stop()

    async def _recover_expired_leases(self) -> None:
        """Requeue only abandoned work; never disturb a lease held by another worker."""
        now = datetime.now(UTC)
        async with async_session_factory() as session:
            await self._requeue_expired_leases(session, now)
            # Compatibility for rows marked running before lease columns were introduced.
            await session.execute(
                update(WorkflowRun)
                .where(
                    WorkflowRun.status == "running",
                    WorkflowRun.lease_expires_at.is_(None),
                )
                .values(status="queued", worker_id=None)
            )
            await session.commit()

    @staticmethod
    async def _requeue_expired_leases(session: AsyncSession, now: datetime) -> None:
        await session.execute(
            update(WorkflowRun)
            .where(
                WorkflowRun.status == "running",
                WorkflowRun.lease_expires_at.is_not(None),
                WorkflowRun.lease_expires_at < now,
            )
            .values(status="queued", worker_id=None, lease_expires_at=None)
        )

    async def _process_next_batch(self) -> None:
        """Fetch next queued runs and execute them concurrently."""
        async with async_session_factory() as session:
            now = datetime.now(UTC)
            await self._requeue_expired_leases(session, now)
            available_slots = max(0, settings.WORKER_MAX_CONCURRENCY - len(self._current_tasks))
            if available_slots == 0:
                queue_count = await session.scalar(
                    select(func.count(WorkflowRun.id)).where(WorkflowRun.status == "queued")
                )
                QUEUE_DEPTH.set(int(queue_count or 0))
                return
            stmt = (
                select(WorkflowRun.id)
                .where(WorkflowRun.status == "queued")
                .order_by(WorkflowRun.created_at)
                .limit(available_slots)
                .with_for_update(skip_locked=True)
            )
            res = await session.execute(stmt)
            queued_ids = list(res.scalars().all())
            run_ids: list[str] = []
            for queued_id in queued_ids:
                claim = await session.execute(
                    update(WorkflowRun)
                    .where(WorkflowRun.id == queued_id, WorkflowRun.status == "queued")
                    .values(
                        status="running",
                        worker_id=self.worker_id,
                        lease_expires_at=now + timedelta(seconds=settings.WORKER_LEASE_SECONDS),
                    )
                    .returning(WorkflowRun.id)
                )
                claimed_id = claim.scalar_one_or_none()
                if claimed_id:
                    run_ids.append(claimed_id)
            queue_count = await session.scalar(
                select(func.count(WorkflowRun.id)).where(WorkflowRun.status == "queued")
            )
            QUEUE_DEPTH.set(int(queue_count or 0))
            await session.commit()

        for rid in run_ids:
            task = asyncio.create_task(self._safe_execute(rid))
            self._current_tasks.add(task)
            task.add_done_callback(self._current_tasks.discard)

    async def _safe_execute(self, run_id: str) -> None:
        logger.info("Worker picking up run %s", run_id)
        execution = asyncio.create_task(self._execute_with_lease(run_id))
        try:
            await execution
        except Exception as exc:
            logger.error("Worker execution failed for run %s: %s", run_id, exc)

    async def _execute_with_lease(self, run_id: str) -> None:
        """Run a workflow while periodically extending its database lease."""
        execution = asyncio.create_task(self._run_claimed_workflow(run_id))
        heartbeat = asyncio.create_task(self._renew_lease(run_id, execution))
        try:
            await execution
        finally:
            heartbeat.cancel()
            with suppress(asyncio.CancelledError):
                await heartbeat
            await self._release_finished_lease(run_id)

    async def _run_claimed_workflow(self, run_id: str) -> None:
        resume_value = await self._pending_resume_value(run_id)
        await runner.execute_run(run_id, resume_value=resume_value)

    async def _renew_lease(self, run_id: str, execution: asyncio.Task[Any]) -> None:
        interval = max(
            1, min(settings.WORKER_HEARTBEAT_SECONDS, settings.WORKER_LEASE_SECONDS // 3)
        )
        while not execution.done():
            await asyncio.sleep(interval)
            if execution.done():
                return
            try:
                async with async_session_factory() as session:
                    result = cast(
                        CursorResult[Any],
                        await session.execute(
                            update(WorkflowRun)
                            .where(
                                WorkflowRun.id == run_id,
                                WorkflowRun.status == "running",
                                WorkflowRun.worker_id == self.worker_id,
                            )
                            .values(
                                lease_expires_at=datetime.now(UTC)
                                + timedelta(seconds=settings.WORKER_LEASE_SECONDS)
                            )
                        ),
                    )
                    await session.commit()
            except Exception:
                logger.exception("Could not renew worker lease for run %s", run_id)
                execution.cancel()
                return
            if result.rowcount != 1:
                logger.error("Worker %s lost the lease for run %s", self.worker_id, run_id)
                execution.cancel()
                return

    async def _release_finished_lease(self, run_id: str) -> None:
        async with async_session_factory() as session:
            await session.execute(
                update(WorkflowRun)
                .where(
                    WorkflowRun.id == run_id,
                    WorkflowRun.worker_id == self.worker_id,
                    WorkflowRun.status != "running",
                )
                .values(worker_id=None, lease_expires_at=None)
            )
            await session.commit()

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
    start_http_server(settings.WORKER_METRICS_PORT, addr="0.0.0.0")
    loop = asyncio.get_running_loop()

    for sig in (signal.SIGINT, signal.SIGTERM):
        with suppress(NotImplementedError):
            loop.add_signal_handler(sig, worker.stop)

    await worker.start()


if __name__ == "__main__":
    asyncio.run(run_worker())
