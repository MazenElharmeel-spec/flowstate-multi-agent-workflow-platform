"""Native tool: calculate allowable refund or compensation."""

from typing import Any

from backend.app.tools.base import BaseTool, ToolContext, ToolMetadata


class CalculateRefundTool(BaseTool):
    metadata = ToolMetadata(
        name="calculate_refund_amount",
        description="Calculate allowable refund amount based on order value, elapsed days, and customer tier.",
        parameters={
            "type": "object",
            "properties": {
                "order_amount": {
                    "type": "number",
                    "description": "Total original order value in USD",
                    "minimum": 0,
                },
                "days_since_purchase": {
                    "type": "integer",
                    "description": "Number of days elapsed since the purchase date",
                    "minimum": 0,
                },
                "customer_tier": {
                    "type": "string",
                    "enum": ["VIP", "Standard", "Basic"],
                    "description": "Customer membership tier",
                },
                "item_defective": {
                    "type": "boolean",
                    "description": "Whether the item was delivered damaged or defective",
                },
            },
            "required": ["order_amount", "days_since_purchase", "customer_tier"],
        },
        side_effect="read",
        risk="low",
        requires_approval=False,
        idempotent=True,
    )

    async def _execute(self, arguments: dict[str, Any], context: ToolContext) -> dict[str, Any]:
        order_amount = float(arguments["order_amount"])
        days = int(arguments["days_since_purchase"])
        tier = arguments["customer_tier"]
        defective = bool(arguments.get("item_defective", False))

        if defective or days <= 30 or tier == "VIP":
            max_refund = order_amount
            percent = 100
            eligible = True
            reason = "Eligible for 100% full refund under satisfaction guarantee / VIP policy"
        elif days <= 60:
            max_refund = round(order_amount * 0.75, 2)
            percent = 75
            eligible = True
            reason = "Eligible for 75% partial refund (31-60 days)"
        else:
            max_refund = round(order_amount * 0.50, 2)
            percent = 50
            eligible = True
            reason = "Eligible for 50% store credit or exception refund (>60 days)"

        return {
            "eligible": eligible,
            "max_refund_allowed": max_refund,
            "percentage": percent,
            "reason": reason,
        }
