"""Append-only event logger and live Server-Sent Events (SSE) broadcaster."""

import asyncio
import json
import logging
from collections import defaultdict
from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select

from backend.app.core.logging import redact_data
from backend.app.db.models import RunEvent
from backend.app.db.session import async_session_factory
from backend.app.observability.metrics import APPROVALS_TOTAL, RUNS_TOTAL, TOOL_CALLS_TOTAL

logger = logging.getLogger(__name__)


class EventBus:
    """Manages event persistence to DB and dispatching to live SSE subscribers."""

    def __init__(self) -> None:
        self._subscribers: dict[str, set[asyncio.Queue[dict[str, Any]]]] = defaultdict(set)
        self._lock = asyncio.Lock()

    async def publish(
        self,
        run_id: str,
        event_type: str,
        payload: dict[str, Any] | None = None,
        node_name: str | None = None,
        duration_ms: float | None = None,
        trace_id: str | None = None,
    ) -> dict[str, Any]:
        """Atomically persist event to DB with sequence number and broadcast to SSE."""
        sanitized_payload = redact_data(payload or {})
        now = datetime.now(UTC)
        if event_type in {
            "run.queued",
            "run.started",
            "run.waiting_approval",
            "run.completed",
            "run.failed",
            "run.cancelled",
            "run.timed_out",
        }:
            RUNS_TOTAL.labels(status=event_type.removeprefix("run.")).inc()
        elif event_type.startswith("approval."):
            APPROVALS_TOTAL.labels(event=event_type.removeprefix("approval.")).inc()
        elif event_type == "tool.call":
            TOOL_CALLS_TOTAL.labels(
                tool_name=str(sanitized_payload.get("tool_name", "unknown")),
                status=str(sanitized_payload.get("status", "unknown")),
            ).inc()

        # 1. Persist to DB with auto-incrementing sequence number for the run
        async with async_session_factory() as session:
            # Get max sequence number for this run
            seq_stmt = select(func.coalesce(func.max(RunEvent.sequence_number), 0)).where(
                RunEvent.run_id == run_id
            )
            result = await session.execute(seq_stmt)
            next_seq = int(result.scalar() or 0) + 1

            event_record = RunEvent(
                run_id=run_id,
                sequence_number=next_seq,
                event_type=event_type,
                node_name=node_name,
                payload=sanitized_payload,
                duration_ms=duration_ms,
                trace_id=trace_id,
                timestamp=now,
            )
            session.add(event_record)
            await session.commit()
            await session.refresh(event_record)

            event_dict: dict[str, Any] = {
                "id": event_record.id,
                "run_id": run_id,
                "sequence_number": next_seq,
                "event_type": event_type,
                "node_name": node_name,
                "payload": sanitized_payload,
                "duration_ms": duration_ms,
                "trace_id": trace_id,
                "timestamp": now.isoformat(),
            }

        # 2. Dispatch to live in-memory subscribers
        async with self._lock:
            queues = self._subscribers.get(run_id, set()).copy()

        for queue in queues:
            try:
                queue.put_nowait(event_dict)
            except asyncio.QueueFull:
                logger.warning("Subscriber queue full for run %s, dropping event", run_id)

        return event_dict

    async def subscribe(self, run_id: str) -> AsyncGenerator[str, None]:
        """Yield Server-Sent Events formatted data for a run."""
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=100)

        # Replay historical events from DB first so late joiners see full history
        async with async_session_factory() as session:
            stmt = (
                select(RunEvent)
                .where(RunEvent.run_id == run_id)
                .order_by(RunEvent.sequence_number)
            )
            res = await session.execute(stmt)
            history = res.scalars().all()
            for h in history:
                evt = {
                    "id": h.id,
                    "run_id": h.run_id,
                    "sequence_number": h.sequence_number,
                    "event_type": h.event_type,
                    "node_name": h.node_name,
                    "payload": h.payload,
                    "duration_ms": h.duration_ms,
                    "trace_id": h.trace_id,
                    "timestamp": h.timestamp.isoformat(),
                }
                yield f"event: {h.event_type}\ndata: {json.dumps(evt)}\n\n"

        async with self._lock:
            self._subscribers[run_id].add(queue)

        try:
            while True:
                # Wait for next live event with keep-alive ping
                try:
                    event_data = await asyncio.wait_for(queue.get(), timeout=15.0)
                    evt_type = event_data.get("event_type", "message")
                    yield f"event: {evt_type}\ndata: {json.dumps(event_data)}\n\n"

                    # Close stream on final events
                    if evt_type in (
                        "run.completed",
                        "run.failed",
                        "run.cancelled",
                        "run.timed_out",
                    ):
                        break
                except TimeoutError:
                    # SSE keep-alive comment
                    yield ": ping\n\n"
        finally:
            async with self._lock:
                if run_id in self._subscribers:
                    self._subscribers[run_id].discard(queue)
                    if not self._subscribers[run_id]:
                        del self._subscribers[run_id]


event_bus = EventBus()
