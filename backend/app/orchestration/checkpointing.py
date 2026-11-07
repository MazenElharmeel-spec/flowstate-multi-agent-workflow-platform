"""Durable LangGraph checkpoint saver backed by SQLAlchemy database models."""

import base64
import json
from collections.abc import AsyncIterator, Iterator, Sequence
from datetime import UTC, datetime
from typing import Any, cast

from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import (
    BaseCheckpointSaver,
    ChannelVersions,
    Checkpoint,
    CheckpointMetadata,
    CheckpointTuple,
    get_checkpoint_id,
)
from sqlalchemy import desc, select

from backend.app.db.models import CheckpointRecord
from backend.app.db.session import async_session_factory


class DatabaseCheckpointSaver(BaseCheckpointSaver[str]):
    """Durable checkpoint saver storing thread states into the database."""

    def __init__(self) -> None:
        super().__init__()

    def get_tuple(self, config: RunnableConfig) -> CheckpointTuple | None:
        """Sync version of get_tuple (raises NotImplementedError to enforce async)."""
        raise NotImplementedError("Use aget_tuple for database checkpoint saver")

    async def aget_tuple(self, config: RunnableConfig) -> CheckpointTuple | None:
        """Fetch checkpoint tuple for given thread_id and optional checkpoint_id."""
        thread_id = config["configurable"]["thread_id"]
        checkpoint_ns = config["configurable"].get("checkpoint_ns", "")
        checkpoint_id = get_checkpoint_id(config)

        async with async_session_factory() as session:
            stmt = select(CheckpointRecord).where(
                CheckpointRecord.thread_id == thread_id,
                CheckpointRecord.checkpoint_ns == checkpoint_ns,
            )
            if checkpoint_id:
                stmt = stmt.where(CheckpointRecord.checkpoint_id == checkpoint_id)
            else:
                stmt = stmt.order_by(desc(CheckpointRecord.created_at)).limit(1)

            result = await session.execute(stmt)
            record = result.scalar_one_or_none()
            if not record:
                return None

            config_out: RunnableConfig = {
                "configurable": {
                    "thread_id": thread_id,
                    "checkpoint_ns": checkpoint_ns,
                    "checkpoint_id": record.checkpoint_id,
                }
            }
            parent_config: RunnableConfig | None = (
                {
                    "configurable": {
                        "thread_id": thread_id,
                        "checkpoint_ns": checkpoint_ns,
                        "checkpoint_id": record.parent_checkpoint_id,
                    }
                }
                if record.parent_checkpoint_id
                else None
            )

            # Deserialize
            raw_bytes = (
                base64.b64decode(record.checkpoint_data["b64"])
                if isinstance(record.checkpoint_data, dict) and "b64" in record.checkpoint_data
                else json.dumps(record.checkpoint_data).encode("utf-8")
            )
            checkpoint: Checkpoint = self.serde.loads_typed((record.type or "json", raw_bytes))
            metadata = cast(CheckpointMetadata, record.metadata_data or {})

            return CheckpointTuple(
                config=config_out,
                checkpoint=checkpoint,
                metadata=metadata,
                parent_config=parent_config,
            )

    def list(
        self,
        config: RunnableConfig | None,
        *,
        filter: dict[str, Any] | None = None,
        before: RunnableConfig | None = None,
        limit: int | None = None,
    ) -> Iterator[CheckpointTuple]:
        raise NotImplementedError("Use alist for database checkpoint saver")

    async def alist(
        self,
        config: RunnableConfig | None,
        *,
        filter: dict[str, Any] | None = None,
        before: RunnableConfig | None = None,
        limit: int | None = None,
    ) -> AsyncIterator[CheckpointTuple]:
        """List historical checkpoints for replay and time travel."""
        if not config:
            return

        thread_id = config["configurable"]["thread_id"]
        checkpoint_ns = config["configurable"].get("checkpoint_ns", "")

        async with async_session_factory() as session:
            stmt = select(CheckpointRecord).where(
                CheckpointRecord.thread_id == thread_id,
                CheckpointRecord.checkpoint_ns == checkpoint_ns,
            )
            if before:
                before_id = get_checkpoint_id(before)
                if before_id:
                    stmt = stmt.where(CheckpointRecord.checkpoint_id < before_id)

            stmt = stmt.order_by(desc(CheckpointRecord.created_at))
            if limit:
                stmt = stmt.limit(limit)

            result = await session.execute(stmt)
            records = result.scalars().all()

            for record in records:
                config_out: RunnableConfig = {
                    "configurable": {
                        "thread_id": thread_id,
                        "checkpoint_ns": checkpoint_ns,
                        "checkpoint_id": record.checkpoint_id,
                    }
                }
                parent_config: RunnableConfig | None = (
                    {
                        "configurable": {
                            "thread_id": thread_id,
                            "checkpoint_ns": checkpoint_ns,
                            "checkpoint_id": record.parent_checkpoint_id,
                        }
                    }
                    if record.parent_checkpoint_id
                    else None
                )
                raw_bytes = (
                    base64.b64decode(record.checkpoint_data["b64"])
                    if isinstance(record.checkpoint_data, dict) and "b64" in record.checkpoint_data
                    else json.dumps(record.checkpoint_data).encode("utf-8")
                )
                checkpoint: Checkpoint = self.serde.loads_typed((record.type or "json", raw_bytes))
                yield CheckpointTuple(
                    config=config_out,
                    checkpoint=checkpoint,
                    metadata=cast(CheckpointMetadata, record.metadata_data or {}),
                    parent_config=parent_config,
                )

    def put(
        self,
        config: RunnableConfig,
        checkpoint: Checkpoint,
        metadata: CheckpointMetadata,
        new_versions: ChannelVersions,
    ) -> RunnableConfig:
        raise NotImplementedError("Use aput for database checkpoint saver")

    async def aput(
        self,
        config: RunnableConfig,
        checkpoint: Checkpoint,
        metadata: CheckpointMetadata,
        new_versions: ChannelVersions,
    ) -> RunnableConfig:
        """Persist a new checkpoint snapshot."""
        thread_id = config["configurable"]["thread_id"]
        checkpoint_ns = config["configurable"].get("checkpoint_ns", "")
        checkpoint_id = checkpoint["id"]
        parent_checkpoint_id = config["configurable"].get("checkpoint_id")

        type_str, serialized_bytes = self.serde.dumps_typed(checkpoint)
        checkpoint_dict = {"b64": base64.b64encode(serialized_bytes).decode("ascii")}

        async with async_session_factory() as session:
            record = CheckpointRecord(
                thread_id=thread_id,
                checkpoint_ns=checkpoint_ns,
                checkpoint_id=checkpoint_id,
                parent_checkpoint_id=parent_checkpoint_id,
                type=type_str,
                checkpoint_data=checkpoint_dict,
                metadata_data=metadata,
                created_at=datetime.now(UTC),
            )
            await session.merge(record)
            await session.commit()

        return {
            "configurable": {
                "thread_id": thread_id,
                "checkpoint_ns": checkpoint_ns,
                "checkpoint_id": checkpoint_id,
            }
        }

    def put_writes(
        self,
        config: RunnableConfig,
        writes: Sequence[tuple[str, Any]],
        task_id: str,
        task_path: str = "",
    ) -> None:
        pass

    async def aput_writes(
        self,
        config: RunnableConfig,
        writes: Sequence[tuple[str, Any]],
        task_id: str,
        task_path: str = "",
    ) -> None:
        pass
