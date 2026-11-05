"""Email MCP Server: outbound customer notifications and sent mail audit log."""

import json
import os
import sqlite3
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import uvicorn

from backend.mcp_servers.common import MCPServer, MCPToolDef

server = MCPServer(name="email-mcp", version="1.0.0")

# Outbound email log and idempotency records survive MCP server restarts.
SENT_EMAILS: list[dict[str, Any]] = []
DB_PATH = os.environ.get(
    "EMAIL_DB_PATH",
    "./data/email-test.sqlite" if os.environ.get("ENVIRONMENT") == "test" else "./data/email.sqlite",
)


def connect_db() -> sqlite3.Connection:
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DB_PATH, timeout=10)
    connection.row_factory = sqlite3.Row
    return connection


def initialize_db() -> None:
    if os.environ.get("ENVIRONMENT") == "test" and os.path.exists(DB_PATH):
        os.remove(DB_PATH)
    with connect_db() as connection:
        connection.execute(
            "CREATE TABLE IF NOT EXISTS sent_emails (idempotency_key TEXT PRIMARY KEY, data TEXT NOT NULL)"
        )


initialize_db()


def handle_send_email(args: dict[str, Any]) -> dict[str, Any]:
    to_email = args.get("to_email")
    subject = args.get("subject")
    body = args.get("body")
    template_id = args.get("template_id", "custom")
    idempotency_key = args.get("idempotency_key")

    if not to_email or "@" not in to_email:
        raise ValueError(f"Invalid recipient email address: '{to_email}'")
    if not idempotency_key:
        raise ValueError("idempotency_key is required for outbound email")

    with connect_db() as connection:
        connection.execute("BEGIN IMMEDIATE")
        existing = connection.execute(
            "SELECT data FROM sent_emails WHERE idempotency_key = ?", (idempotency_key,)
        ).fetchone()
        if existing:
            record = json.loads(existing["data"])
            connection.commit()
            return {
                "message_id": record["message_id"],
                "status": "sent",
                "recipient": record["to_email"],
                "subject": record["subject"],
                "idempotent_replay": True,
            }

        record = {
            "message_id": f"msg-{uuid.uuid4().hex[:8]}",
            "to_email": to_email,
            "subject": subject,
            "body": body,
            "template_id": template_id,
            "idempotency_key": idempotency_key,
            "sent_at": datetime.now(UTC).isoformat(),
            "status": "delivered",
        }
        connection.execute(
            "INSERT INTO sent_emails(idempotency_key, data) VALUES (?, ?)",
            (idempotency_key, json.dumps(record)),
        )
        connection.commit()
    SENT_EMAILS.append(record)
    return {
        "message_id": record["message_id"],
        "status": "sent",
        "recipient": to_email,
        "subject": subject,
        "idempotent_replay": False,
    }


def handle_get_sent_emails(args: dict[str, Any]) -> list[dict[str, Any]]:
    to_email = args.get("to_email")
    with connect_db() as connection:
        rows = connection.execute("SELECT data FROM sent_emails ORDER BY rowid").fetchall()
    messages = [json.loads(row["data"]) for row in rows]
    if to_email:
        return [e for e in messages if e["to_email"].lower() == to_email.lower()]
    return messages


server.register_tool(
    MCPToolDef(
        name="send_email",
        description="Send an official resolution or notification email to a customer.",
        inputSchema={
            "type": "object",
            "properties": {
                "to_email": {
                    "type": "string",
                    "format": "email",
                    "description": "Recipient address",
                },
                "subject": {"type": "string", "description": "Email subject line"},
                "body": {"type": "string", "description": "Message content in markdown/text"},
                "idempotency_key": {"type": "string", "description": "Stable key preventing duplicate sends"},
                "template_id": {"type": "string", "description": "Optional email template code"},
            },
            "required": ["to_email", "subject", "body", "idempotency_key"],
        },
        side_effect="write",
        risk="medium",
        requires_approval=False,
    ),
    handle_send_email,
)

server.register_tool(
    MCPToolDef(
        name="get_sent_emails",
        description="Fetch sent email history for audit and verification.",
        inputSchema={
            "type": "object",
            "properties": {
                "to_email": {"type": "string", "description": "Filter by recipient email"}
            },
        },
        side_effect="read",
        risk="low",
        requires_approval=False,
    ),
    handle_get_sent_emails,
)

app = server.app

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8003))
    uvicorn.run(app, host="0.0.0.0", port=port)
