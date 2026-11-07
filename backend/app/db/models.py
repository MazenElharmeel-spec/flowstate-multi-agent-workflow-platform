"""SQLAlchemy 2.0 database models."""

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.app.core.security import Role
from backend.app.db.session import Base


def utc_now() -> datetime:
    return datetime.now(UTC)


def generate_uuid() -> str:
    return str(uuid.uuid4())


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(50), default=Role.VIEWER.value, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    # Relationships
    runs: Mapped[list["WorkflowRun"]] = relationship("WorkflowRun", back_populates="initiator")
    decided_approvals: Mapped[list["ApprovalRequest"]] = relationship(
        "ApprovalRequest", back_populates="decided_by_user"
    )


class WorkflowDefinition(Base):
    __tablename__ = "workflow_definitions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    key: Mapped[str] = mapped_column(String(100), index=True, nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    input_schema: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    graph_definition: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    # Unique index on key + version
    __table_args__ = (Index("ix_wf_key_version", "key", "version", unique=True),)

    runs: Mapped[list["WorkflowRun"]] = relationship("WorkflowRun", back_populates="definition")


class WorkflowRun(Base):
    __tablename__ = "workflow_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    workflow_definition_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("workflow_definitions.id"), nullable=False
    )
    workflow_version: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(50), default="queued", index=True, nullable=False)
    # queued, running, waiting_approval, completed, failed, cancelled, timed_out

    inputs: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    outputs: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    state_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    current_node: Mapped[str | None] = mapped_column(String(100), nullable=True)

    step_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    estimated_cost_usd: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)

    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    worker_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    initiated_by_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    # Relationships
    definition: Mapped["WorkflowDefinition"] = relationship(
        "WorkflowDefinition", back_populates="runs"
    )
    initiator: Mapped["User | None"] = relationship("User", back_populates="runs")
    events: Mapped[list["RunEvent"]] = relationship(
        "RunEvent",
        back_populates="run",
        cascade="all, delete-orphan",
        order_by="RunEvent.sequence_number",
    )
    approvals: Mapped[list["ApprovalRequest"]] = relationship(
        "ApprovalRequest", back_populates="run", cascade="all, delete-orphan"
    )


class RunEvent(Base):
    __tablename__ = "run_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    run_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("workflow_runs.id", ondelete="CASCADE"), index=True, nullable=False
    )
    sequence_number: Mapped[int] = mapped_column(Integer, nullable=False)
    event_type: Mapped[str] = mapped_column(String(100), index=True, nullable=False)
    node_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    duration_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    trace_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    __table_args__ = (Index("ix_run_sequence", "run_id", "sequence_number", unique=True),)

    run: Mapped["WorkflowRun"] = relationship("WorkflowRun", back_populates="events")


class ApprovalRequest(Base):
    __tablename__ = "approval_requests"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    run_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("workflow_runs.id", ondelete="CASCADE"), index=True, nullable=False
    )
    checkpoint_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    tool_name: Mapped[str] = mapped_column(String(100), nullable=False)
    original_arguments: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    resolved_arguments: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    risk_level: Mapped[str] = mapped_column(String(20), default="high", nullable=False)
    reason: Mapped[str] = mapped_column(Text, default="", nullable=False)

    status: Mapped[str] = mapped_column(String(30), default="pending", index=True, nullable=False)
    # pending, approved, rejected, edited, expired

    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    decided_by_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=True
    )
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    run: Mapped["WorkflowRun"] = relationship("WorkflowRun", back_populates="approvals")
    decided_by_user: Mapped["User | None"] = relationship(
        "User", back_populates="decided_approvals"
    )


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    run_id: Mapped[str | None] = mapped_column(String(36), index=True, nullable=True)
    user_id: Mapped[str | None] = mapped_column(String(36), index=True, nullable=True)
    action: Mapped[str] = mapped_column(String(100), nullable=False)
    details: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    ip_address: Mapped[str | None] = mapped_column(String(50), nullable=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class CheckpointRecord(Base):
    """Stores LangGraph thread state snapshots for durable replay and recovery."""

    __tablename__ = "checkpoints"

    thread_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    checkpoint_ns: Mapped[str] = mapped_column(String(100), primary_key=True, default="")
    checkpoint_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    parent_checkpoint_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    checkpoint_data: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    metadata_data: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
