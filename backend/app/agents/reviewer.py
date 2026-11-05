"""Reviewer Agent: audits outcomes against policy and original request (bounded loop)."""

from typing import Literal

from pydantic import BaseModel, Field


class ReviewOutput(BaseModel):
    decision: Literal["approved", "revision_needed"] = Field(
        ..., description="Whether outcome satisfies SLA and policy"
    )
    policy_compliant: bool = Field(..., description="Whether all policy rules were honored")
    quality_score: int = Field(default=100, ge=0, le=100)
    notes: str = Field(..., description="Audit review justification")
    revision_instructions: str | None = Field(
        default=None, description="Instructions for planner if revision is needed"
    )


REVIEWER_SYSTEM_PROMPT = """You are the Reviewer Agent.
Audit the outcome of the Action Agent against:
1. The original ticket and customer SLA
2. Company policy and approval decisions
3. Verification that required emails and status updates occurred

If the resolution is deficient, output decision 'revision_needed' with clear feedback.
Otherwise, output decision 'approved'."""

REVIEWER_ALLOWLIST: list[str] = ["get_sent_emails", "get_payment_details"]
