"""Action Agent: executes approved actions using write tools with idempotency."""

from typing import Any

from pydantic import BaseModel, Field


class ActionExecutionOutput(BaseModel):
    executed_tools: list[str] = Field(default_factory=list)
    refund_result: dict[str, Any] | None = None
    email_result: dict[str, Any] | None = None
    ticket_result: dict[str, Any] | None = None
    summary: str = Field(..., description="Summary of executed side effects")


ACTION_SYSTEM_PROMPT = """You are the Action Agent. You are the ONLY agent authorized to perform write side-effects.
Execute the approved resolution plan strictly using authorized tools.
Always include deterministic idempotency keys for financial transactions.
Never execute actions that were not authorized by the plan or human approver."""

ACTION_ALLOWLIST: list[str] = [
    "issue_refund",
    "send_email",
    "update_ticket_status",
    "update_customer_status",
]
