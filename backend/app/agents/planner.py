"""Resolution Planner Agent: formulates reasoned resolution plans with risk assessment."""

from typing import Literal

from pydantic import BaseModel, Field


class ResolutionPlanOutput(BaseModel):
    proposed_action: Literal["refund", "replacement", "credit", "escalate_to_human"] = Field(
        ..., description="Recommended resolution strategy"
    )
    refund_amount: float = Field(default=0.0, description="Proposed refund amount if applicable")
    payment_id: str | None = Field(default=None, description="Payment ID to refund if applicable")
    risk_level: Literal["low", "medium", "high"] = Field(
        ..., description="Risk assessment of the action"
    )
    reasoning: str = Field(..., description="Justification referencing policies and customer tier")
    requires_supervisor_approval: bool = Field(
        ..., description="Whether policy mandates human sign-off"
    )
    planned_tools: list[str] = Field(
        default_factory=list, description="Tools that the Action Agent should execute"
    )


PLANNER_SYSTEM_PROMPT = """You are the Resolution Planner Agent.
Evaluate the triage classification and research context to formulate a balanced, reasoned resolution plan.
Consult company refund calculation policies.
Flag whether sensitive actions (e.g. refunds > $50) require supervisor approval.
If a previous plan was rejected by a human approver, take into account the rejection reason and propose an alternative (e.g. replacement item or store credit)."""

PLANNER_ALLOWLIST: list[str] = ["calculate_refund_amount", "search_knowledge_base"]
