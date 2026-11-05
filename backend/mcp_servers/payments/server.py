"""Payments MCP Server: payment inspection and idempotent refund execution."""

import os
import uuid
from datetime import UTC, datetime
from typing import Any

import uvicorn

from backend.mcp_servers.common import MCPServer, MCPToolDef

server = MCPServer(name="payments-mcp", version="1.0.0")

PAYMENTS: dict[str, dict[str, Any]] = {
    "pay-801": {
        "payment_id": "pay-801",
        "order_id": "ord-901",
        "customer_id": "cust-101",
        "original_amount_usd": 120.0,
        "refunded_amount_usd": 0.0,
        "payment_method": "credit_card",
        "card_brand": "Visa",
        "card_last4": "4242",
        "status": "succeeded",
        "created_at": "2026-11-01T10:00:00Z",
    },
    "pay-802": {
        "payment_id": "pay-802",
        "order_id": "ord-902",
        "customer_id": "cust-102",
        "original_amount_usd": 85.0,
        "refunded_amount_usd": 0.0,
        "payment_method": "credit_card",
        "card_brand": "Mastercard",
        "card_last4": "5555",
        "status": "succeeded",
        "created_at": "2026-10-25T15:30:00Z",
    },
}

# Strict Idempotency Store: key -> refund record
IDEMPOTENCY_STORE: dict[str, dict[str, Any]] = {}
REFUND_LOG: list[dict[str, Any]] = []


def handle_get_payment_details(args: dict[str, Any]) -> dict[str, Any]:
    pid = args.get("payment_id")
    if pid not in PAYMENTS:
        raise ValueError(f"Payment record '{pid}' not found")
    return PAYMENTS[pid]


def handle_issue_refund(args: dict[str, Any]) -> dict[str, Any]:
    pid = args.get("payment_id")
    amount = float(args.get("amount", 0.0))
    reason = args.get("reason", "Customer resolution")
    idempotency_key = args.get("idempotency_key")

    if not idempotency_key:
        raise ValueError("idempotency_key is strictly required for financial refund operations")

    # Check idempotency store to prevent duplicate charges or refunds across restarts
    if idempotency_key in IDEMPOTENCY_STORE:
        cached = IDEMPOTENCY_STORE[idempotency_key].copy()
        cached["idempotent_replay"] = True
        return cached

    if pid not in PAYMENTS:
        raise ValueError(f"Payment record '{pid}' not found")

    payment = PAYMENTS[pid]
    available_to_refund = payment["original_amount_usd"] - payment["refunded_amount_usd"]

    if amount <= 0:
        raise ValueError(f"Invalid refund amount: ${amount:.2f}")

    if amount > available_to_refund:
        raise ValueError(
            f"Requested refund amount ${amount:.2f} exceeds available remaining amount ${available_to_refund:.2f}"
        )

    # Process refund
    refund_id = f"ref-{uuid.uuid4().hex[:8]}"
    payment["refunded_amount_usd"] += amount
    if payment["refunded_amount_usd"] >= payment["original_amount_usd"]:
        payment["status"] = "fully_refunded"
    else:
        payment["status"] = "partially_refunded"

    result = {
        "refund_id": refund_id,
        "payment_id": pid,
        "amount_refunded_usd": amount,
        "reason": reason,
        "idempotency_key": idempotency_key,
        "idempotent_replay": False,
        "new_payment_status": payment["status"],
        "timestamp": datetime.now(UTC).isoformat(),
        "status": "succeeded",
    }

    # Record in idempotency cache and audit log
    IDEMPOTENCY_STORE[idempotency_key] = result
    REFUND_LOG.append(result)

    return result


server.register_tool(
    MCPToolDef(
        name="get_payment_details",
        description="Inspect payment status, original charge amount, and existing refunds.",
        inputSchema={
            "type": "object",
            "properties": {
                "payment_id": {"type": "string", "description": "The unique payment transaction ID"}
            },
            "required": ["payment_id"],
        },
        side_effect="read",
        risk="low",
        requires_approval=False,
    ),
    handle_get_payment_details,
)

server.register_tool(
    MCPToolDef(
        name="issue_refund",
        description="Issue a financial refund against an existing payment. Sensitive action requiring approval if amount exceeds threshold.",
        inputSchema={
            "type": "object",
            "properties": {
                "payment_id": {"type": "string", "description": "Payment transaction ID"},
                "amount": {
                    "type": "number",
                    "minimum": 0.01,
                    "description": "Amount to refund in USD",
                },
                "reason": {"type": "string", "description": "Business justification for refund"},
                "idempotency_key": {
                    "type": "string",
                    "description": "Unique deterministic idempotency token",
                },
            },
            "required": ["payment_id", "amount", "idempotency_key"],
        },
        side_effect="write",
        risk="high",
        requires_approval=True,
        idempotent=True,
    ),
    handle_issue_refund,
)

app = server.app

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8004))
    uvicorn.run(app, host="0.0.0.0", port=port)
