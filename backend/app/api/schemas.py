"""Pydantic schemas for API requests, responses, and validation."""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from backend.app.core.security import Role


# --- Auth Schemas ---
class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: Role


class UserCreate(BaseModel):
    email: EmailStr
    password: str
    role: Role = Role.VIEWER


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    email: str
    role: Role
    is_active: bool
    created_at: datetime


# --- Workflow Schemas ---
class WorkflowDefinitionCreate(BaseModel):
    key: str = Field(..., pattern=r"^[a-z0-9_-]+$")
    name: str
    description: str = ""
    input_schema: dict[str, Any] = Field(default_factory=dict)
    graph_definition: dict[str, Any] = Field(default_factory=dict)


class WorkflowDefinitionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    key: str
    version: int
    name: str
    description: str
    input_schema: dict[str, Any]
    is_active: bool
    created_at: datetime


class WorkflowRunCreate(BaseModel):
    workflow_key: str
    workflow_version: int | None = None
    inputs: dict[str, Any] = Field(default_factory=dict)


class WorkflowRunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    workflow_definition_id: str
    workflow_version: int
    status: str
    inputs: dict[str, Any]
    outputs: dict[str, Any]
    current_node: str | None
    step_count: int
    total_tokens: int
    estimated_cost_usd: float
    started_at: datetime | None
    finished_at: datetime | None
    created_at: datetime


# --- Event Schemas ---
class RunEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    run_id: str
    sequence_number: int
    event_type: str
    node_name: str | None
    payload: dict[str, Any]
    duration_ms: float | None
    trace_id: str | None
    timestamp: datetime


# --- Approval Schemas ---
class ApprovalRequestOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    run_id: str
    checkpoint_id: str | None
    tool_name: str
    original_arguments: dict[str, Any]
    resolved_arguments: dict[str, Any]
    risk_level: str
    reason: str
    status: str
    rejection_reason: str | None
    decided_by_id: str | None
    decided_at: datetime | None
    expires_at: datetime
    created_at: datetime


class ApprovalDecisionRequest(BaseModel):
    decision: Literal["approve", "reject", "edit"]
    rejection_reason: str | None = None
    edited_arguments: dict[str, Any] | None = None


# --- Tool Registry Schemas ---
class ToolDefinitionOut(BaseModel):
    name: str
    description: str
    parameters: dict[str, Any]
    side_effect: Literal["read", "write"]
    risk: Literal["low", "medium", "high"]
    requires_approval: bool
    idempotent: bool
    source: Literal["native", "mcp"]
    server_name: str | None = None
