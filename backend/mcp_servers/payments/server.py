"""Payments MCP Server: payment inspection and idempotent refund execution."""

import json
import os
import sqlite3
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

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
DB_PATH = os.environ.get(
    "PAYMENTS_DB_PATH",
    "./data/payments-test.sqlite"
    if os.environ.get("ENVIRONMENT") == "test"
    else "./data/payments.sqlite",
)


def connect_db() -> sqlite3.Connection:
    if DB_PATH != ":memory:":
        Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DB_PATH, timeout=10)
    connection.row_factory = sqlite3.Row
    return connection


def initialize_db() -> None:
    with connect_db() as connection:
        connection.execute(
            "CREATE TABLE IF NOT EXISTS payment_records (payment_id TEXT PRIMARY KEY, data TEXT NOT NULL)"
        )
        connection.execute(
            "CREATE TABLE IF NOT EXISTS refund_records (idempotency_key TEXT PRIMARY KEY, data TEXT NOT NULL)"
        )
        for payment_id, record in PAYMENTS.items():
            connection.execute(
                "INSERT OR IGNORE INTO payment_records(payment_id, data) VALUES (?, ?)",
                (payment_id, json.dumps(record)),
            )


if os.environ.get("ENVIRONMENT") == "test" and os.path.exists(DB_PATH):
    os.remove(DB_PATH)
initialize_db()


def handle_get_payment_details(args: dict[str, Any]) -> dict[str, Any]:
    pid = args.get("payment_id")
    with connect_db() as connection:
        row = connection.execute(
            "SELECT data FROM payment_records WHERE payment_id = ?", (pid,)
        ).fetchone()
    if row is None:
        raise ValueError(f"Payment record '{pid}' not found")
    return cast(dict[str, Any], json.loads(row["data"]))


def handle_issue_refund(args: dict[str, Any]) -> dict[str, Any]:
    pid = str(args.get("payment_id", ""))
    amount = float(args.get("amount", 0.0))
    reason = args.get("reason", "Customer resolution")
    idempotency_key = args.get("idempotency_key")

    if not idempotency_key:
        raise ValueError("idempotency_key is strictly required for financial refund operations")

    with connect_db() as connection:
        connection.execute("BEGIN IMMEDIATE")
        cached_row = connection.execute(
            "SELECT data FROM refund_records WHERE idempotency_key = ?", (idempotency_key,)
        ).fetchone()
        if cached_row is not None:
            cached = cast(dict[str, Any], json.loads(cached_row["data"]))
            cached["idempotent_replay"] = True
            connection.commit()
            return cached

        payment_row = connection.execute(
            "SELECT data FROM payment_records WHERE payment_id = ?", (pid,)
        ).fetchone()
        if payment_row is None:
            raise ValueError(f"Payment record '{pid}' not found")
        payment = json.loads(payment_row["data"])
        available_to_refund = payment["original_amount_usd"] - payment["refunded_amount_usd"]
        if amount <= 0:
            raise ValueError(f"Invalid refund amount: ${amount:.2f}")
        if amount > available_to_refund:
            raise ValueError(
                f"Requested refund amount ${amount:.2f} exceeds available remaining amount ${available_to_refund:.2f}"
            )

        refund_id = f"ref-{uuid.uuid4().hex[:8]}"
        payment["refunded_amount_usd"] += amount
        payment["status"] = (
            "fully_refunded"
            if payment["refunded_amount_usd"] >= payment["original_amount_usd"]
            else "partially_refunded"
        )
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
        connection.execute(
            "UPDATE payment_records SET data = ? WHERE payment_id = ?",
            (json.dumps(payment), pid),
        )
        connection.execute(
            "INSERT INTO refund_records(idempotency_key, data) VALUES (?, ?)",
            (idempotency_key, json.dumps(result)),
        )
        connection.commit()

    PAYMENTS[pid] = payment
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
