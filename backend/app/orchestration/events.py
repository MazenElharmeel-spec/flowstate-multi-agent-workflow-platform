"""Persistent run events with Redis fanout for multi-instance SSE delivery."""

import asyncio
import json
import logging
from collections import defaultdict
from collections.abc import AsyncGenerator
from contextlib import suppress
from datetime import UTC, datetime
from typing import Any

from redis.asyncio import Redis
from sqlalchemy import func, select

from backend.app.core.config import get_settings
from backend.app.core.logging import redact_data
from backend.app.db.models import RunEvent, WorkflowRun
from backend.app.db.session import async_session_factory
from backend.app.observability.metrics import APPROVALS_TOTAL, RUNS_TOTAL, TOOL_CALLS_TOTAL

logger = logging.getLogger(__name__)
settings = get_settings()
EVENT_CHANNEL = "workflow:run-events"
TERMINAL_EVENTS = {"run.completed", "run.failed", "run.cancelled", "run.timed_out"}


class EventBus:
    """Persist once, then fan out through Redis to subscribers on every API instance."""

    def __init__(self) -> None:
        self._subscribers: dict[str, set[asyncio.Queue[dict[str, Any]]]] = defaultdict(set)
        self._lock = asyncio.Lock()
        self._redis: Redis[Any] | None = None
        self._listener_task: asyncio.Task[None] | None = None

    async def start(self, *, listen: bool = False) -> None:
        """Initialize the shared Redis connection and optional instance listener."""
        if self._redis is None:
            self._redis = Redis.from_url(settings.REDIS_URL, decode_responses=True)
        if listen and (self._listener_task is None or self._listener_task.done()):
            self._listener_task = asyncio.create_task(self._listen_for_events())

    async def stop(self) -> None:
        """Stop the Redis listener and release its connection pool."""
        if self._listener_task is not None:
            self._listener_task.cancel()
            with suppress(asyncio.CancelledError):
                await self._listener_task
            self._listener_task = None
        if self._redis is not None:
            await self._redis.close()
            self._redis = None

    async def _listen_for_events(self) -> None:
        """Consume the shared channel and dispatch events to local SSE clients."""
        while True:
            pubsub = None
            try:
                if self._redis is None:
                    return
                pubsub = self._redis.pubsub()
                await pubsub.subscribe(EVENT_CHANNEL)
                async for message in pubsub.listen():
                    if message.get("type") != "message":
                        continue
                    try:
                        event = json.loads(str(message["data"]))
                        if isinstance(event, dict) and isinstance(event.get("run_id"), str):
                            await self._dispatch_local(event["run_id"], event)
                    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
                        logger.warning("Discarding malformed event received on Redis channel")
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Redis event listener failed; retrying")
                await asyncio.sleep(1)
            finally:
                if pubsub is not None:
                    await pubsub.close()

    async def _dispatch_local(self, run_id: str, event: dict[str, Any]) -> None:
        async with self._lock:
            queues = self._subscribers.get(run_id, set()).copy()
        for queue in queues:
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                logger.warning("Subscriber queue full for run %s, dropping event", run_id)

    @staticmethod
    def _serialize_record(event: RunEvent) -> dict[str, Any]:
        return {
            "id": event.id,
            "run_id": event.run_id,
            "sequence_number": event.sequence_number,
            "event_type": event.event_type,
            "node_name": event.node_name,
            "payload": event.payload,
            "duration_ms": event.duration_ms,
            "trace_id": event.trace_id,
            "timestamp": event.timestamp.isoformat(),
        }

    async def _fetch_events_after(self, run_id: str, sequence: int) -> list[dict[str, Any]]:
        async with async_session_factory() as session:
            stmt = (
                select(RunEvent)
                .where(RunEvent.run_id == run_id, RunEvent.sequence_number > sequence)
                .order_by(RunEvent.sequence_number)
            )
            result = await session.execute(stmt)
            return [self._serialize_record(event) for event in result.scalars().all()]

    async def publish(
        self,
        run_id: str,
        event_type: str,
        payload: dict[str, Any] | None = None,
        node_name: str | None = None,
        duration_ms: float | None = None,
        trace_id: str | None = None,
    ) -> dict[str, Any]:
        """Persist an ordered event, then publish it to every connected API instance."""
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

        async with async_session_factory() as session:
            # Serialize sequence allocation per run when different processes publish.
            await session.execute(
                select(WorkflowRun.id).where(WorkflowRun.id == run_id).with_for_update()
            )
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
            event_dict = self._serialize_record(event_record)

        if self._redis is None:
            await self._dispatch_local(run_id, event_dict)
        else:
            try:
                await self._redis.publish(
                    EVENT_CHANNEL, json.dumps(event_dict, separators=(",", ":"))
                )
            except Exception:
                # The append-only event table remains authoritative if Redis is unavailable.
                logger.exception("Redis event publish failed for run %s", run_id)
                await self._dispatch_local(run_id, event_dict)
        return event_dict

    async def subscribe(self, run_id: str) -> AsyncGenerator[str, None]:
        """Replay persisted events then yield deduplicated live Redis events as SSE."""
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=100)
        async with self._lock:
            self._subscribers[run_id].add(queue)

        last_sequence = 0
        first_read = True
        try:
            while True:
                timed_out = False
                try:
                    if first_read:
                        first_read = False
                        events = await self._fetch_events_after(run_id, last_sequence)
                    else:
                        await asyncio.wait_for(queue.get(), timeout=15.0)
                        events = await self._fetch_events_after(run_id, last_sequence)
                except TimeoutError:
                    # The database replay also covers transient Redis disconnects.
                    events = await self._fetch_events_after(run_id, last_sequence)
                    timed_out = not events

                if not events:
                    if timed_out:
                        yield ": ping\n\n"
                    continue

                for event in events:
                    last_sequence = int(event["sequence_number"])
                    event_type = str(event.get("event_type", "message"))
                    yield f"event: {event_type}\ndata: {json.dumps(event)}\n\n"
                    if event_type in TERMINAL_EVENTS:
                        return
        finally:
            async with self._lock:
                if run_id in self._subscribers:
                    self._subscribers[run_id].discard(queue)
                    if not self._subscribers[run_id]:
                        del self._subscribers[run_id]


event_bus = EventBus()
