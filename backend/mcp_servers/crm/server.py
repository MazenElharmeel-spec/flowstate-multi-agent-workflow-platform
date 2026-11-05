"""CRM MCP Server: customer profiles and order history."""

import os
from typing import Any

import uvicorn

from backend.mcp_servers.common import MCPServer, MCPToolDef

server = MCPServer(name="crm-mcp", version="1.0.0")

# Realistic in-memory/seed database
CUSTOMERS: dict[str, dict[str, Any]] = {
    "cust-101": {
        "id": "cust-101",
        "name": "Alice Johnson",
        "email": "alice@example.com",
        "tier": "VIP",
        "lifetime_spend_usd": 2450.0,
        "joined_date": "2023-01-15",
        "status": "active",
        "orders": [
            {
                "order_id": "ord-901",
                "date": "2026-11-01",
                "amount_usd": 120.0,
                "status": "delivered",
                "items": [{"sku": "HEADSET-PRO", "name": "Pro Wireless Headset", "price": 120.0}],
            },
            {
                "order_id": "ord-802",
                "date": "2026-08-10",
                "amount_usd": 450.0,
                "status": "delivered",
                "items": [{"sku": "MONITOR-4K", "name": "Ultra HD 4K Monitor", "price": 450.0}],
            },
        ],
    },
    "cust-102": {
        "id": "cust-102",
        "name": "Bob Smith",
        "email": "bob@example.com",
        "tier": "Standard",
        "lifetime_spend_usd": 320.0,
        "joined_date": "2024-05-10",
        "status": "active",
        "orders": [
            {
                "order_id": "ord-902",
                "date": "2026-10-25",
                "amount_usd": 85.0,
                "status": "in_transit",
                "items": [
                    {"sku": "KEYBOARD-RGB", "name": "Mechanical RGB Keyboard", "price": 85.0}
                ],
            }
        ],
    },
    "cust-103": {
        "id": "cust-103",
        "name": "Charlie Brown",
        "email": "charlie@example.com",
        "tier": "Basic",
        "lifetime_spend_usd": 45.0,
        "joined_date": "2024-09-01",
        "status": "active",
        "orders": [
            {
                "order_id": "ord-903",
                "date": "2026-10-30",
                "amount_usd": 45.0,
                "status": "delivered",
                "items": [{"sku": "MOUSE-PAD", "name": "Ergonomic Mouse Pad", "price": 45.0}],
            }
        ],
    },
}


def handle_get_customer(args: dict[str, Any]) -> dict[str, Any]:
    cid = args.get("customer_id")
    if cid not in CUSTOMERS:
        raise ValueError(f"Customer '{cid}' not found in CRM")
    cust = CUSTOMERS[cid].copy()
    cust_data = {k: v for k, v in cust.items() if k != "orders"}
    return cust_data


def handle_get_customer_orders(args: dict[str, Any]) -> list[dict[str, Any]]:
    cid = args.get("customer_id")
    if cid not in CUSTOMERS:
        raise ValueError(f"Customer '{cid}' not found in CRM")
    return CUSTOMERS[cid]["orders"]


def handle_update_customer_status(args: dict[str, Any]) -> dict[str, Any]:
    cid = args.get("customer_id")
    new_status = args.get("status")
    if cid not in CUSTOMERS:
        raise ValueError(f"Customer '{cid}' not found in CRM")
    CUSTOMERS[cid]["status"] = new_status
    return {"customer_id": cid, "updated_status": new_status, "success": True}


server.register_tool(
    MCPToolDef(
        name="get_customer",
        description="Fetch customer CRM profile including tier, membership date, and lifetime spend.",
        inputSchema={
            "type": "object",
            "properties": {
                "customer_id": {
                    "type": "string",
                    "description": "The unique customer ID (e.g. 'cust-101')",
                }
            },
            "required": ["customer_id"],
        },
        side_effect="read",
        risk="low",
        requires_approval=False,
    ),
    handle_get_customer,
)

server.register_tool(
    MCPToolDef(
        name="get_customer_orders",
        description="Retrieve past order history, line items, and delivery status for a customer.",
        inputSchema={
            "type": "object",
            "properties": {
                "customer_id": {"type": "string", "description": "The unique customer ID"}
            },
            "required": ["customer_id"],
        },
        side_effect="read",
        risk="low",
        requires_approval=False,
    ),
    handle_get_customer_orders,
)

server.register_tool(
    MCPToolDef(
        name="update_customer_status",
        description="Update CRM customer status (e.g. VIP_escalation, flagged, active).",
        inputSchema={
            "type": "object",
            "properties": {
                "customer_id": {"type": "string", "description": "The unique customer ID"},
                "status": {"type": "string", "description": "New status for the customer record"},
            },
            "required": ["customer_id", "status"],
        },
        side_effect="write",
        risk="medium",
        requires_approval=False,
    ),
    handle_update_customer_status,
)

app = server.app

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8001))
    uvicorn.run(app, host="0.0.0.0", port=port)
