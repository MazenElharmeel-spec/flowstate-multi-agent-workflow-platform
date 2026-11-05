"""Triage Agent: classifies severity, intent, and customer tier."""

from typing import Literal

from pydantic import BaseModel, Field


class TriageOutput(BaseModel):
    severity: Literal["low", "medium", "high", "critical"] = Field(
        ..., description="Assessed escalation urgency"
    )
    intent: Literal["damaged_goods", "billing_inquiry", "shipping_delay", "complaint", "other"] = (
        Field(..., description="Primary classification of customer issue")
    )
    customer_tier: Literal["VIP", "Standard", "Basic"] = Field(
        ..., description="Customer tier classification"
    )
    reasoning: str = Field(..., description="Step-by-step reasoning for classification")


TRIAGE_SYSTEM_PROMPT = """You are the specialized Triage Agent for an enterprise customer escalation platform.
Analyze incoming support tickets and customer communications to classify severity, intent, and customer tier.
You have NO write tools. Adhere strictly to least privilege. Return structured JSON matching the TriageOutput schema."""

TRIAGE_ALLOWLIST: list[str] = []
