"""Declarative Policy Engine evaluating safety rules, risk thresholds, and human approval gates."""

from dataclasses import dataclass, field
from typing import Any, Literal

from backend.app.orchestration.state import WorkflowState


@dataclass
class PolicyDecision:
    requires_approval: bool
    risk_level: Literal["low", "medium", "high"]
    rule_name: str
    reason: str
    diff_summary: str = ""
    evidence: dict[str, Any] = field(default_factory=dict)


class PolicyEngine:
    """Evaluates declarative business and safety rules before any write side effect."""

    def evaluate_tool_call(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        state: WorkflowState,
    ) -> PolicyDecision:
        # Rule 1: Financial refunds above $50.00 always require human approval
        if tool_name == "issue_refund":
            amount = float(arguments.get("amount", 0.0))
            if amount > 50.0:
                return PolicyDecision(
                    requires_approval=True,
                    risk_level="high",
                    rule_name="REFUND_THRESHOLD_EXCEEDED",
                    reason=f"Refund amount of ${amount:.2f} exceeds the automatic authorization limit of $50.00",
                    diff_summary=f"Deduct ${amount:.2f} from company account and credit customer card",
                    evidence={
                        "payment_id": arguments.get("payment_id"),
                        "amount": amount,
                        "threshold": 50.0,
                    },
                )
            elif amount > 0:
                # Small refunds (<=$50) for VIP or verified defects can be auto-approved
                triage = state.get("agent_outputs", {}).get("triage", {})
                if triage.get("customer_tier") == "VIP":
                    return PolicyDecision(
                        requires_approval=False,
                        risk_level="low",
                        rule_name="VIP_AUTO_REFUND_POLICY",
                        reason=f"Refund of ${amount:.2f} for VIP customer auto-approved under satisfaction SLA",
                        diff_summary=f"Auto-refund ${amount:.2f}",
                    )

        # Rule 2: Basic tier accounts attempting large refunds require scrutiny
        triage = state.get("agent_outputs", {}).get("triage", {})
        if triage.get("customer_tier") == "Basic" and tool_name == "issue_refund":
            amount = float(arguments.get("amount", 0.0))
            if amount > 25.0:
                return PolicyDecision(
                    requires_approval=True,
                    risk_level="high",
                    rule_name="BASIC_TIER_REFUND_CAP",
                    reason=f"Basic tier customer requested refund ${amount:.2f} (> $25.00 limit)",
                    diff_summary=f"Review requested refund of ${amount:.2f}",
                )

        # Rule 3: Malicious instruction override check
        args_str = str(arguments).lower()
        if "ignore all previous" in args_str or "bypass" in args_str:
            return PolicyDecision(
                requires_approval=True,
                risk_level="high",
                rule_name="PROMPT_INJECTION_DEFENSE",
                reason="Detected potential prompt-injection attempt inside arguments. Quarantined for supervisor review.",
                diff_summary="Suspicious argument payload quarantined",
            )

        # Default low-risk read or minor write tools
        return PolicyDecision(
            requires_approval=False,
            risk_level="low",
            rule_name="STANDARD_LOW_RISK_PERMIT",
            reason=f"Tool '{tool_name}' matches standard automated execution policies",
            diff_summary=f"Execute {tool_name}",
        )


policy_engine = PolicyEngine()
