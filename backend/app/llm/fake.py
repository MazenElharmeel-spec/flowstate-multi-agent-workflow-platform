"""Deterministic scripted Fake LLM provider for tests and zero-API-key demo mode."""

import json
from typing import Any

from pydantic import BaseModel

from backend.app.llm.base import BaseLLMProvider, LLMMessage, LLMResponse, LLMToolCall


class ScriptedFakeLLM(BaseLLMProvider):
    """Deterministic, scriptable LLM provider exercising full workflow cycles with zero API keys."""

    def __init__(self, scenario: str = "happy_path"):
        self.scenario = scenario
        self.call_history: list[dict[str, Any]] = []

    async def generate(
        self,
        messages: list[LLMMessage],
        tools: list[dict[str, Any]] | None = None,
        response_schema: type[BaseModel] | None = None,
        temperature: float = 0.0,
    ) -> LLMResponse:
        self.call_history.append({"messages": messages, "tools": tools})

        system_prompt = next((m.content for m in messages if m.role == "system"), "")
        last_user = next((m.content for m in reversed(messages) if m.role in ("user", "tool")), "")
        data: dict[str, Any]

        # 1. Triage Agent
        if "Triage Agent" in system_prompt:
            if "CRITICAL SYSTEM DIRECTIVE" in last_user:
                data = {
                    "severity": "high",
                    "intent": "complaint",
                    "customer_tier": "Basic",
                    "reasoning": "Detected high-priority escalated complaint mentioning billing directive. Customer tier is Basic.",
                }
            else:
                data = {
                    "severity": "high",
                    "intent": "damaged_goods",
                    "customer_tier": "VIP",
                    "reasoning": "Customer reported damaged headset on arrival. Identified as VIP customer tier.",
                }
            return LLMResponse(
                content=json.dumps(data),
                structured_output=data,
                prompt_tokens=180,
                completion_tokens=85,
                total_tokens=265,
                estimated_cost_usd=0.0012,
            )

        # 2. Research Agent
        elif "Research Agent" in system_prompt:
            # If tools are provided and not yet called in the trajectory:
            last_message_is_tool = any(m.role == "tool" for m in messages)
            if not last_message_is_tool:
                # Propose calling research tools
                return LLMResponse(
                    content="Gathering customer history and order details.",
                    tool_calls=[
                        LLMToolCall(
                            id="call_crm_1",
                            name="get_customer",
                            arguments={"customer_id": "cust-101"},
                        ),
                        LLMToolCall(
                            id="call_tick_1",
                            name="get_ticket",
                            arguments={"ticket_id": "tick-501"},
                        ),
                        LLMToolCall(
                            id="call_pay_1",
                            name="get_payment_details",
                            arguments={"payment_id": "pay-801"},
                        ),
                        LLMToolCall(
                            id="call_kb_1",
                            name="search_knowledge_base",
                            arguments={"query": "damaged goods refund policy"},
                        ),
                    ],
                    prompt_tokens=220,
                    completion_tokens=120,
                    total_tokens=340,
                    estimated_cost_usd=0.0015,
                )
            else:
                # Synthesize research output
                data = {
                    "customer_name": "Alice Johnson",
                    "customer_tier": "VIP",
                    "lifetime_spend": 2450.0,
                    "order_id": "ord-901",
                    "item_damaged": "Pro Wireless Headset",
                    "paid_amount_usd": 120.0,
                    "payment_id": "pay-801",
                    "eligible_for_full_refund": True,
                    "summary": "Customer Alice Johnson is a VIP member with high lifetime spend. Item arrived broken within 4 days of delivery. Policy grants full 100% refund or replacement.",
                }
                return LLMResponse(
                    content=json.dumps(data),
                    structured_output=data,
                    prompt_tokens=450,
                    completion_tokens=140,
                    total_tokens=590,
                    estimated_cost_usd=0.0025,
                )

        # 3. Resolution Planner Agent
        elif "Resolution Planner" in system_prompt or "Planner Agent" in system_prompt:
            # Check if this is a replan after human rejection
            rejection_detected = any("REJECTED" in m.content for m in messages)
            if rejection_detected:
                data = {
                    "proposed_action": "replacement",
                    "refund_amount": 0.0,
                    "risk_level": "low",
                    "reasoning": "Previous refund plan was rejected. Revised plan: issue expedited replacement item and credit $20 loyalty coupon.",
                    "requires_supervisor_approval": False,
                    "planned_tools": ["send_email", "update_ticket_status"],
                }
            else:
                data = {
                    "proposed_action": "refund",
                    "payment_id": "pay-801",
                    "refund_amount": 120.0,
                    "risk_level": "high",
                    "reasoning": "VIP customer received broken merchandise. Proposing full refund of $120.00 to original payment method and notification email.",
                    "requires_supervisor_approval": True,  # $120 > $50 policy threshold!
                    "planned_tools": ["issue_refund", "send_email", "update_ticket_status"],
                }
            return LLMResponse(
                content=json.dumps(data),
                structured_output=data,
                prompt_tokens=350,
                completion_tokens=160,
                total_tokens=510,
                estimated_cost_usd=0.0022,
            )

        # 4. Action Agent
        elif "Action Agent" in system_prompt or "action" in system_prompt.lower():
            # The action agent generates tool calls based on the plan
            return LLMResponse(
                content="Executing approved customer resolution plan.",
                tool_calls=[
                    LLMToolCall(
                        id="call_ref_1",
                        name="issue_refund",
                        arguments={
                            "payment_id": "pay-801",
                            "amount": 120.0,
                            "reason": "Damaged headset resolution for VIP customer",
                            "idempotency_key": "idemp-action-escalation-901",
                        },
                    ),
                    LLMToolCall(
                        id="call_email_1",
                        name="send_email",
                        arguments={
                            "to_email": "alice@example.com",
                            "subject": "Your Refund for Order #ord-901 has been processed",
                            "body": "Dear Alice,\n\nWe apologize for the damaged headset. A full refund of $120.00 has been issued to your Visa ending in 4242.\n\nBest regards,\nExecutive Support",
                        },
                    ),
                    LLMToolCall(
                        id="call_ticket_1",
                        name="update_ticket_status",
                        arguments={
                            "ticket_id": "tick-501",
                            "status": "resolved",
                            "internal_notes": "Full refund of $120 processed with supervisor approval.",
                        },
                    ),
                ],
                prompt_tokens=320,
                completion_tokens=180,
                total_tokens=500,
                estimated_cost_usd=0.0020,
            )

        # 5. Reviewer Agent
        elif "Reviewer Agent" in system_prompt or "reviewer" in system_prompt.lower():
            data = {
                "decision": "approved",
                "policy_compliant": True,
                "notes": "Verified refund and email sent. Customer ticket marked resolved in compliance with VIP SLA.",
                "quality_score": 100,
            }
            return LLMResponse(
                content=json.dumps(data),
                structured_output=data,
                prompt_tokens=290,
                completion_tokens=90,
                total_tokens=380,
                estimated_cost_usd=0.0016,
            )

        # 6. Report Step or Ops Digest
        elif "Ops Digest" in system_prompt or "ops" in system_prompt.lower():
            data = {
                "metrics_analyzed": {
                    "active_agents": 6,
                    "runs_completed": 142,
                    "error_rate": 0.015,
                },
                "anomalies": ["Slight latency uptick on payments-mcp around 14:00 UTC"],
                "summary": "Weekly system performance is within normal SLOs. Error rate 1.5% is well below 5% target.",
                "status": "completed",
            }
            return LLMResponse(
                content=json.dumps(data),
                structured_output=data,
                prompt_tokens=250,
                completion_tokens=110,
                total_tokens=360,
                estimated_cost_usd=0.0015,
            )

        # Fallback generic structured output
        default_data = {
            "status": "completed",
            "message": "Processed successfully by scripted provider.",
        }
        return LLMResponse(
            content=json.dumps(default_data),
            structured_output=default_data,
            prompt_tokens=100,
            completion_tokens=50,
            total_tokens=150,
            estimated_cost_usd=0.0006,
        )
