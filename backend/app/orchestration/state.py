"""Typed graph state for LangGraph multi-agent workflow execution."""

from typing import Annotated, Any, TypedDict


def merge_dicts(a: dict[str, Any], b: dict[str, Any]) -> dict[str, Any]:
    merged = a.copy()
    merged.update(b)
    return merged


def append_list(a: list[Any], b: list[Any] | Any) -> list[Any]:
    lst = list(a)
    if isinstance(b, list):
        lst.extend(b)
    else:
        lst.append(b)
    return lst


class WorkflowState(TypedDict, total=False):
    # Execution & Workflow identity
    run_id: str
    workflow_key: str
    workflow_version: int
    inputs: dict[str, Any]

    # Node tracking
    current_node: str | None
    next_node: str | None

    # Agent outputs: triage, research, planner, action, reviewer, report
    agent_outputs: Annotated[dict[str, Any], merge_dicts]

    # Tool calls tracking
    tool_call_records: Annotated[list[dict[str, Any]], append_list]

    # Approvals tracking
    active_approval: dict[str, Any] | None
    approval_decision: dict[str, Any] | None

    # Budgets and execution bounds
    step_count: int
    tool_call_count: int
    total_tokens: int
    estimated_cost_usd: float
    review_revisions_count: int
    max_review_revisions: int

    # Error handling & status
    errors: Annotated[list[dict[str, Any]], append_list]
    is_failed: bool
    is_completed: bool
    fallback_escalated: bool
