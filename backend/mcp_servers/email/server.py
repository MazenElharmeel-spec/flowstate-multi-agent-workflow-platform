"""Email MCP Server: outbound customer notifications and sent mail audit log."""

import os
import uuid
from datetime import UTC, datetime
from typing import Any

import uvicorn

from backend.mcp_servers.common import MCPServer, MCPToolDef

server = MCPServer(name="email-mcp", version="1.0.0")

# Outbound email log
SENT_EMAILS: list[dict[str, Any]] = []


def handle_send_email(args: dict[str, Any]) -> dict[str, Any]:
    to_email = args.get("to_email")
    subject = args.get("subject")
    body = args.get("body")
    template_id = args.get("template_id", "custom")

    if not to_email or "@" not in to_email:
        raise ValueError(f"Invalid recipient email address: '{to_email}'")

    msg_id = f"msg-{uuid.uuid4().hex[:8]}"
    record = {
        "message_id": msg_id,
        "to_email": to_email,
        "subject": subject,
        "body": body,
        "template_id": template_id,
        "sent_at": datetime.now(UTC).isoformat(),
        "status": "delivered",
    }
    SENT_EMAILS.append(record)

    return {
        "message_id": msg_id,
        "status": "sent",
        "recipient": to_email,
        "subject": subject,
    }


def handle_get_sent_emails(args: dict[str, Any]) -> list[dict[str, Any]]:
    to_email = args.get("to_email")
    if to_email:
        return [e for e in SENT_EMAILS if e["to_email"].lower() == to_email.lower()]
    return SENT_EMAILS


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
                "template_id": {"type": "string", "description": "Optional email template code"},
            },
            "required": ["to_email", "subject", "body"],
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
